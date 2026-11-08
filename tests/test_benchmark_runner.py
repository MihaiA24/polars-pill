import json
import os
import selectors
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class BenchmarkRunnerTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.work = Path(directory.name)
        self.environment = dict(
            os.environ,
            PATH=f"{self.work}:{os.environ['PATH']}",
            BENCHMARK_WARMUPS="0",
            BENCHMARK_REPETITIONS="2",
            BENCHMARK_STATUS="0",
            GPU_SETUP_STATUS="0",
            REPORT_STATUS="0",
            BENCHMARK_PROFILE_MEMORY="0",
        )
        self.previous_results = {
            "benchmarks.jsonl": '{"duration_seconds": 1.25}\n',
            "README.md": "previous README\n",
            "BENCHMARKS.html": "previous report\n",
        }
        for name, contents in self.previous_results.items():
            (self.work / name).write_text(contents)
        self.write_executable(
            ".venv/bin/python",
            "#!/bin/sh\n"
            'if [ "$1" = "pandas_evaluation.py" ]; then\n'
            '  if [ "$BENCHMARK_STATUS" != "0" ]; then\n'
            '    echo "fixture: benchmark could not read its input" >&2\n'
            "  fi\n"
            '  exit "$BENCHMARK_STATUS"\n'
            "fi\n"
            "touch later-case-ran\n",
        )
        self.write_executable(
            "uv",
            "#!/bin/sh\n"
            'if [ "$1" = "run" ]; then\n'
            '  [ "$4" = "$(cat active-group)" ] || exit 39\n'
            '  echo "$4" > report-group\n'
            "  touch report-generated\n"
            '  exit "$REPORT_STATUS"\n'
            "fi\n"
            'for argument in "$@"; do\n'
            '  if [ "$argument" = "gpu_polars" ]; then\n'
            "    echo gpu_polars > active-group\n"
            "    echo gpu_polars >> setup-groups\n"
            "    touch gpu-setup-started\n"
            '    exit "$GPU_SETUP_STATUS"\n'
            "  fi\n"
            "done\n"
            "echo cpu_polars > active-group\n"
            "echo cpu_polars >> setup-groups\n",
        )

    def write_executable(self, name, contents):
        executable = self.work / name
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.write_text(contents)
        executable.chmod(0o755)

    def run_runner(self, *arguments, **environment):
        return subprocess.run(
            [sys.executable, str(ROOT / "run_benchmark.py"), *arguments],
            check=False,
            cwd=self.work,
            env={**self.environment, **environment},
            capture_output=True,
            text=True,
            timeout=30,
        )

    def assert_previous_results_preserved(self):
        for name, contents in self.previous_results.items():
            self.assertEqual((self.work / name).read_text(), contents)

    def test_failed_sync_preserves_existing_results(self):
        self.write_executable("uv", "#!/bin/sh\necho 'fixture: CPU setup failed' >&2\nexit 23\n")
        result = self.run_runner("--plain")
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 23, output)
        self.assertIn("fixture: CPU setup failed", output)
        self.assertFalse((self.work / "later-case-ran").exists())
        self.assertFalse((self.work / "report-generated").exists())
        self.assert_previous_results_preserved()

    def test_matrix_preserves_failures_and_still_generates_report(self):
        for benchmark_status, report_status, expected_status in ((17, 0, 1), (0, 29, 29), (17, 29, 29), (0, 0, 0)):
            with self.subTest(benchmark_status=benchmark_status, report_status=report_status):
                for name in ("later-case-ran", "report-generated"):
                    (self.work / name).unlink(missing_ok=True)
                result = self.run_runner(
                    "--plain", BENCHMARK_STATUS=str(benchmark_status), REPORT_STATUS=str(report_status)
                )
                output = result.stdout + result.stderr
                self.assertTrue((self.work / "later-case-ran").exists(), output)
                self.assertTrue((self.work / "report-generated").exists(), output)
                self.assertEqual(result.returncode, expected_status, output)
                if benchmark_status:
                    self.assertIn("fixture: benchmark could not read its input", output)
                self.assertNotIn("\x1b", output)

    def install_protocol_fixture(self):
        self.write_executable(
            ".venv/bin/python",
            f"#!{sys.executable}\n"
            + textwrap.dedent(
                f"""\
                import sys
                from pathlib import Path
                from unittest.mock import patch

                sys.path.insert(0, {str(ROOT)!r})
                import utils

                options = dict(zip(sys.argv[2::2], sys.argv[3::2]))

                def execute():
                    utils.save_execution_time(
                        sys.argv[1].removesuffix("_evaluation.py"),
                        0.25,
                        "GPU" if options.get("--gpu_engine") == "True" else "CPU",
                        options.get("--engine", "native"),
                        options.get("--dataset_type", "ecommerce"),
                        options.get("--execution_query", "simple"),
                        version=Path("active-group").read_text().strip(),
                    )
                    return True

                with (
                    patch.object(utils, "_source_metadata", return_value={{}}),
                    patch.object(utils, "_resource_metadata", return_value={{
                        "hardware": {{"host_id": "fixture-host", "cpu_model": "Fixture CPU", "memory_bytes": 1024, "gpus": []}}
                    }}),
                ):
                    raise SystemExit(not utils.run_benchmark(
                        execute, warmups=int(options["--warmups"]), repetitions=int(options["--repetitions"])
                    ))
                """
            ),
        )

    def protocol_rows(self):
        return [
            json.loads(line)
            for line in (self.work / "benchmarks.jsonl").read_text().splitlines()
            if "suite_id" in json.loads(line)
        ]

    def test_real_protocol_rows_keep_suites_and_configuration_batches_separate(self):
        self.install_protocol_fixture()
        previous = (self.work / "benchmarks.jsonl").read_bytes()
        suites = []
        for suite_override in ("", "", "explicit-fixture-suite"):
            result = self.run_runner(
                "--plain",
                BENCHMARK_BATCH_ID="inherited-matrix-batch",
                BENCHMARK_SUITE_ID=suite_override,
                BENCHMARK_SUITE_STARTED_AT="2000-01-01T00:00:00+00:00",
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            rows = self.protocol_rows()
            current_suite = rows[-1]["suite_id"]
            current = [row for row in rows if row["suite_id"] == current_suite]
            cold = [row for row in current if row["phase"] == "cold"]
            self.assertEqual(len(cold), 84)
            self.assertEqual({row["dataset"] for row in cold}, {"ecommerce", "nyc-green", "nyc-yellow"})
            self.assertEqual({row["query"] for row in cold}, {"simple", "complex", "filtered", "date-window"})
            self.assertEqual(sum(row["query"] == "date-window" for row in cold), 16)
            self.assertTrue(current_suite)
            self.assertNotIn(current_suite, suites)
            if suite_override:
                self.assertEqual(current_suite, suite_override)
            suites.append(current_suite)
            self.assertEqual(len({row["suite_started_at"] for row in current}), 1)
            self.assertIsNotNone(datetime.fromisoformat(current[0]["suite_started_at"]).utcoffset())
            self.assertNotEqual(current[0]["suite_started_at"], "2000-01-01T00:00:00+00:00")
            batches = defaultdict(list)
            for row in current:
                batches[row["batch_id"]].append(row)
            self.assertGreater(len(batches), 1)
            self.assertNotIn("inherited-matrix-batch", batches)
            for batch_rows in batches.values():
                self.assertEqual(
                    [(row["phase"], row["repetition"]) for row in batch_rows], [("cold", 1), ("warm", 1), ("warm", 2)]
                )
                self.assertEqual(len({row["engine"] for row in batch_rows}), 1)
                self.assertTrue(all(row["error"] is None for row in batch_rows))
            self.assertEqual({row["suite_id"] for row in rows}, set(suites))
            self.assertEqual(len({row["batch_id"] for row in rows}), len(batches) * len(suites))
        self.assertTrue((self.work / "benchmarks.jsonl").read_bytes().startswith(previous))

    def test_targeted_gpu_queries_profile_only_selected_workloads(self):
        self.install_protocol_fixture()
        result = self.run_runner(
            "--plain",
            "--dataset",
            "nyc-green",
            "--query",
            "filtered",
            "date-window",
            "--device",
            "gpu",
            "--profile-memory",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        rows = self.protocol_rows()
        cold = [row for row in rows if row["phase"] == "cold"]
        self.assertEqual(
            [(row["library"], row["dataset"], row["query"], row["device"], row["engine"]) for row in cold],
            [
                ("polars", "nyc-green", "filtered", "GPU", "in-memory"),
                ("polars", "nyc-green", "date-window", "GPU", "in-memory"),
                ("polars", "nyc-green", "filtered", "GPU", "streaming"),
                ("polars", "nyc-green", "date-window", "GPU", "streaming"),
            ],
        )
        self.assertEqual(len(rows), 12)
        self.assertTrue(all(row["memory_profile"]["enabled"] for row in rows))
        self.assertEqual(len({row["suite_id"] for row in rows}), 1)
        self.assertEqual(len({row["batch_id"] for row in rows}), 4)
        self.assertEqual((self.work / "setup-groups").read_text().splitlines(), ["gpu_polars"])
        self.assertEqual((self.work / "report-group").read_text().strip(), "gpu_polars")

    def test_cpu_selection_keeps_both_polars_versions_and_date_window_engines(self):
        self.install_protocol_fixture()
        result = self.run_runner("--plain", "--dataset", "nyc-yellow", "--query", "date-window", "--device", "cpu")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        rows = self.protocol_rows()
        cold = [row for row in rows if row["phase"] == "cold"]
        self.assertEqual(
            [(row["library"], row["version"], row["engine"]) for row in cold],
            [
                ("polars", "cpu_polars", "in-memory"),
                ("polars", "cpu_polars", "streaming"),
                ("pyspark", "cpu_polars", "native"),
                ("duckdb", "cpu_polars", "native"),
                ("polars", "gpu_polars", "in-memory"),
                ("polars", "gpu_polars", "streaming"),
            ],
        )
        self.assertTrue(all(row["dataset"] == "nyc-yellow" and row["query"] == "date-window" for row in rows))
        self.assertTrue(all(row["device"] == "CPU" and not row["memory_profile"]["enabled"] for row in rows))
        self.assertEqual((self.work / "setup-groups").read_text().splitlines(), ["cpu_polars", "gpu_polars"])
        self.assertEqual((self.work / "report-group").read_text().strip(), "gpu_polars")

    def test_queries_without_ecommerce_workload_skip_it_and_keep_matrix_order(self):
        self.install_protocol_fixture()
        result = self.run_runner(
            "--plain", "--dataset", "nyc-yellow", "ecommerce", "nyc-green", "--query", "complex", "--device", "gpu"
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        cold = [row for row in self.protocol_rows() if row["phase"] == "cold"]
        self.assertEqual(
            [(row["dataset"], row["query"], row["engine"]) for row in cold],
            [
                ("nyc-green", "complex", "in-memory"),
                ("nyc-green", "complex", "streaming"),
                ("nyc-yellow", "complex", "in-memory"),
                ("nyc-yellow", "complex", "streaming"),
            ],
        )

    def test_empty_selection_fails_before_environment_setup_or_report(self):
        for selection in (
            ("--dataset", "ecommerce", "--device", "gpu"),
            ("--dataset", "ecommerce", "--query", "filtered", "date-window"),
        ):
            with self.subTest(selection=selection):
                result = self.run_runner("--plain", *selection)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertFalse((self.work / "setup-groups").exists())
                self.assertFalse((self.work / "later-case-ran").exists())
                self.assertFalse((self.work / "report-generated").exists())
                self.assert_previous_results_preserved()

    def test_failed_gpu_sync_aborts_before_gpu_cases_and_report(self):
        self.write_executable(
            ".venv/bin/python",
            "#!/bin/sh\nif [ -e gpu-setup-started ]; then touch case-after-failed-setup; fi\ntouch cpu-case-ran\n",
        )
        result = self.run_runner("--plain", GPU_SETUP_STATUS="31")
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 31, output)
        self.assertTrue((self.work / "cpu-case-ran").exists(), output)
        self.assertTrue((self.work / "gpu-setup-started").exists(), output)
        self.assertFalse((self.work / "case-after-failed-setup").exists())
        self.assertFalse((self.work / "report-generated").exists())
        self.assert_previous_results_preserved()

    def test_non_tty_output_exposes_raw_failures_without_cursor_controls(self):
        result = self.run_runner(BENCHMARK_STATUS="17")
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 1, output)
        self.assertIn("fixture: benchmark could not read its input", output)
        self.assertNotIn("\x1b", output)

    def test_ctrl_c_stops_active_command_and_descendant_without_later_cases(self):
        self.assert_interruption_stops_processes(ignore_descendant_signals=False)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Requires Linux process state")
    def test_ctrl_c_kills_orphan_descendant_that_ignores_interrupt_and_termination(self):
        self.assert_interruption_stops_processes(ignore_descendant_signals=True)

    def assert_interruption_stops_processes(self, *, ignore_descendant_signals):
        descendant = textwrap.dedent(
            f"""\
            import os
            import signal
            import sys
            from pathlib import Path

            def stop(signum, frame):
                Path("descendant-stopped").write_text(str(signum))
                raise SystemExit(0)

            signal.signal(signal.SIGINT, signal.SIG_IGN if {ignore_descendant_signals!r} else stop)
            signal.signal(signal.SIGTERM, signal.SIG_IGN if {ignore_descendant_signals!r} else stop)
            os.write(int(sys.argv[1]), b"ready")
            os.close(int(sys.argv[1]))
            while True:
                signal.pause()
            """
        )
        self.write_executable(
            ".venv/bin/python",
            f"#!{sys.executable}\n"
            + textwrap.dedent(
                f"""\
                import os
                import signal
                import subprocess
                import sys
                from pathlib import Path

                if Path("active-started").exists():
                    Path("later-case-ran").touch()
                    raise SystemExit(0)
                Path("active-started").touch()

                def stop(signum, frame):
                    Path("active-stopped").write_text(str(signum))
                    if {ignore_descendant_signals!r}:
                        os._exit(0)
                    raise SystemExit(0)

                signal.signal(signal.SIGINT, stop)
                signal.signal(signal.SIGTERM, stop)
                reader, writer = os.pipe()
                child = subprocess.Popen([sys.executable, "-c", {descendant!r}, str(writer)], pass_fds=(writer,))
                os.close(writer)
                Path("active-pids").write_text(f"{{os.getpid()}}\\n{{child.pid}}\\n")
                try:
                    os.read(reader, 5)
                    os.close(reader)
                    print("fixture: active command and descendant ready", flush=True)
                    child.wait()
                finally:
                    child.wait(timeout=5)
                """
            ),
        )
        process = subprocess.Popen(
            [sys.executable, str(ROOT / "run_benchmark.py"), "--plain"],
            cwd=self.work,
            env=self.environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        output = b""
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                deadline = time.monotonic() + 10
                while b"fixture: active command and descendant ready" not in output:
                    remaining = deadline - time.monotonic()
                    self.assertGreater(remaining, 0, output.decode(errors="replace"))
                    self.assertTrue(selector.select(remaining), output.decode(errors="replace"))
                    chunk = os.read(process.stdout.fileno(), 65536)
                    self.assertTrue(chunk, output.decode(errors="replace"))
                    output += chunk
            process.send_signal(signal.SIGINT)
            remainder, _ = process.communicate(timeout=10)
            output += remainder
            self.assertEqual(process.returncode, 130, output.decode(errors="replace"))
            self.assertTrue((self.work / "active-stopped").exists(), output.decode(errors="replace"))
            if ignore_descendant_signals:
                descendant_pid = (self.work / "active-pids").read_text().splitlines()[-1]
                state_file = Path(f"/proc/{descendant_pid}/stat")
                deadline = time.monotonic() + 2
                while True:
                    try:
                        state = state_file.read_text().rsplit(")", 1)[1].split()[0]
                    except FileNotFoundError:
                        break
                    if state in ("Z", "X"):
                        break
                    self.assertLess(time.monotonic(), deadline, f"Descendant is still running: {state}")
                    time.sleep(0.01)
            else:
                self.assertTrue((self.work / "descendant-stopped").exists(), output.decode(errors="replace"))
            self.assertFalse((self.work / "later-case-ran").exists())
            self.assertFalse((self.work / "gpu-setup-started").exists())
            self.assertFalse((self.work / "report-generated").exists())
            self.assertNotIn(b"\x1b", output)
        finally:
            pids = self.work / "active-pids"
            if pids.exists():
                for pid in reversed(pids.read_text().splitlines()):
                    try:
                        os.kill(int(pid), signal.SIGKILL)
                    except ProcessLookupError:
                        pass
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)


if __name__ == "__main__":
    unittest.main()
