import argparse
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import utils

ROOT = Path(__file__).resolve().parents[1]


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class BenchmarkRepetitionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(contextlib.chdir(self.root))
        self.clock = Clock()
        self.stack.enter_context(patch.object(utils, "perf_counter", self.clock))
        self.stack.enter_context(patch.dict(os.environ, BENCHMARK_BATCH_ID="fixture-batch"))
        self.source_probe = self.stack.enter_context(
            patch.object(
                utils, "_source_metadata", return_value={"benchmark_revision": "abc123", "benchmark_dirty": False}
            )
        )
        self.resource_probe = self.stack.enter_context(
            patch.object(utils, "_resource_metadata", return_value={"cpu_count": 2})
        )

    def record(self, *, duration=2.0, error=None, dataset="fixture.csv"):
        utils.save_execution_time(
            "Fixture", duration, "CPU", "test", dataset, "SIMPLE", version="1.0", total_duration=999.0, error=error
        )

    def records(self):
        return [json.loads(line) for line in Path("benchmarks.jsonl").read_text().splitlines()]

    def test_default_phases_and_untimed_metadata_and_serialization(self):
        calls = []
        Path("fixture.csv").write_text("input")
        stat = Path("fixture.csv").stat()
        serialize = json.dumps

        def source():
            self.clock.advance(100)
            return {"benchmark_revision": "abc123", "benchmark_dirty": False}

        def resources():
            self.clock.advance(400)
            return {"spark_master": "local[1]"}

        def output(path, succeeded):
            self.clock.advance(200)
            return {"path": str(path), "rows": 2, "attempt_succeeded": succeeded}

        def dumps(*args, **kwargs):
            self.clock.advance(50)
            return serialize(*args, **kwargs)

        def execute():
            calls.append(os.getpid())
            self.clock.advance(3)
            self.record(dataset=f"attempt-{len(calls)}")
            self.clock.advance(7)
            return True

        self.source_probe.side_effect = source
        with (
            patch.object(utils, "_output_metadata", side_effect=output),
            patch.object(utils.json, "dumps", side_effect=dumps),
        ):
            self.assertTrue(
                utils.run_benchmark(
                    execute,
                    process_started=75,
                    input_paths=("fixture.csv",),
                    output_path="result.parquet",
                    resources=resources,
                )
            )
        rows = self.records()
        self.assertEqual(calls, [os.getpid()] * 7)
        self.assertEqual([row["phase"] for row in rows], ["cold"] + ["warm"] * 5)
        self.assertEqual([row["repetition"] for row in rows], [1, 1, 2, 3, 4, 5])
        self.assertEqual([row["dataset"] for row in rows], [f"attempt-{index}" for index in (1, 3, 4, 5, 6, 7)])
        self.assertEqual([row["total_seconds"] for row in rows], [28.0] + [3.0] * 5)
        self.assertEqual([row["startup_seconds"] for row in rows], [25.0] + [0.0] * 5)
        self.assertEqual([row["duration_seconds"] for row in rows], [2.0] * 6)
        for row in rows:
            self.assertEqual(row["batch_id"], "fixture-batch")
            self.assertEqual((row["warmups"], row["repetitions"]), (1, 5))
            self.assertEqual(
                row["input_snapshot"], [{"path": "fixture.csv", "size_bytes": 5, "mtime_ns": stat.st_mtime_ns}]
            )
            self.assertIsNone(row["error"])

    def test_phase_failures_persist_and_abort_without_retries(self):
        for failed_attempt, expected in (
            (1, [("cold", 1)]),
            (2, [("cold", 1), ("warmup", 1)]),
            (4, [("cold", 1), ("warm", 1), ("warm", 2)]),
        ):
            with self.subTest(failed_attempt=failed_attempt):
                Path("benchmarks.jsonl").unlink(missing_ok=True)
                attempts = []

                def execute(attempts=attempts, failed_attempt=failed_attempt):
                    attempts.append(len(attempts) + 1)
                    self.clock.advance(3)
                    failed = len(attempts) == failed_attempt
                    self.record(error="RuntimeError: fixture failure" if failed else None)
                    return not failed

                self.assertFalse(utils.run_benchmark(execute, process_started=self.clock.now - 10))
                rows = self.records()
                self.assertEqual(len(attempts), failed_attempt)
                self.assertEqual([(row["phase"], row["repetition"]) for row in rows], expected)
                self.assertIsNone(rows[-1]["duration_seconds"])
                self.assertIsNone(rows[-1]["total_seconds"])
                self.assertEqual(rows[-1]["error"], "RuntimeError: fixture failure")
                self.assertTrue(all(row["duration_seconds"] == 2 for row in rows[:-1]))

    def test_false_return_and_error_record_cannot_be_reported_successful(self):
        for status, error in ((False, None), (True, "OSError: partial write")):
            with self.subTest(status=status, error=error):
                Path("benchmarks.jsonl").unlink(missing_ok=True)

                def execute(error=error, status=status):
                    self.record(error=error)
                    return status

                self.assertFalse(utils.run_benchmark(execute))
                (row,) = self.records()
                self.assertIsNone(row["duration_seconds"])
                self.assertIsNone(row["total_seconds"])
                self.assertEqual(row["error"], error or "Benchmark execution returned false")

    def test_scoped_state_does_not_leak_into_direct_calls_or_later_runs(self):
        def execute():
            self.clock.advance(3)
            self.record()
            return True

        self.assertTrue(utils.run_benchmark(execute, warmups=0, repetitions=1, process_started=90))
        prefix = Path("benchmarks.jsonl").read_bytes()
        self.record()
        direct = self.records()[-1]
        self.assertEqual(direct["total_seconds"], 999)
        self.assertNotIn("phase", direct)
        self.assertNotIn("batch_id", direct)
        self.record(error="ValueError: direct failure")
        self.assertIsNone(self.records()[-1]["total_seconds"])
        self.assertIsNone(self.records()[-1]["duration_seconds"])
        self.assertTrue(utils.run_benchmark(execute, warmups=0, repetitions=1))
        rows = self.records()
        self.assertEqual([row["total_seconds"] for row in rows[-2:]], [3.0, 3.0])
        self.assertTrue(Path("benchmarks.jsonl").read_bytes().startswith(prefix))

    def test_context_resets_when_execute_raises(self):
        def execute():
            raise ValueError("configuration validation")

        with self.assertRaisesRegex(ValueError, "configuration validation"):
            utils.run_benchmark(execute)
        self.record()
        self.assertNotIn("phase", self.records()[0])

    def test_metadata_probe_failures_preserve_successful_measurements(self):
        Path("broken.parquet").write_bytes(b"not parquet")
        utils.save_execution_time("Legacy", 9.0, "CPU", "test", "old.csv", "simple", version="0")
        prefix = Path("benchmarks.jsonl").read_bytes()

        def execute():
            self.clock.advance(3)
            self.record()
            return True

        def resources():
            self.clock.advance(100)
            raise OSError("session resource probe failed")

        self.assertTrue(
            utils.run_benchmark(
                execute,
                warmups=0,
                repetitions=1,
                input_paths=("missing.csv",),
                output_path="broken.parquet",
                resources=resources,
            )
        )
        rows = self.records()[1:]
        self.assertEqual([row["total_seconds"] for row in rows], [3.0, 3.0])
        for row in rows:
            self.assertIsNone(row["error"])
            self.assertIn("metadata_error", row["input_snapshot"][0])
            self.assertIsNone(row["input_snapshot"][0]["size_bytes"])
            self.assertIn("metadata_error", row["output"])
            self.assertIsNone(row["output"]["rows"])
            self.assertIn("session_resources", row["resources"]["metadata_errors"])
        self.assertTrue(Path("benchmarks.jsonl").read_bytes().startswith(prefix))

    def test_parser_and_programmatic_count_validation(self):
        parser = argparse.ArgumentParser()
        utils.add_benchmark_arguments(parser)
        args = parser.parse_args(["--warmups", "0", "--repetitions", "2"])
        self.assertEqual((args.warmups, args.repetitions), (0, 2))
        for flag, value in (("--warmups", "-1"), ("--warmups", "1.5"), ("--repetitions", "0"), ("--repetitions", "x")):
            with self.subTest(flag=flag, value=value), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    parser.parse_args([flag, value])
                self.assertEqual(raised.exception.code, 2)
        for kwargs in ({"warmups": -1}, {"warmups": True}, {"repetitions": 0}, {"repetitions": 1.5}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                utils.run_benchmark(lambda: self.fail("invalid count executed"), **kwargs)


class BenchmarkProvenanceTests(unittest.TestCase):
    def test_output_metadata_reads_footers_and_actual_native_schema(self):
        import pyarrow as arrow
        from pyarrow import parquet

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            table = arrow.table(
                {
                    "product_id": arrow.array([1, 3], type=arrow.int64()),
                    "price": arrow.array([700, 600], type=arrow.float32()),
                }
            )
            parquet.write_table(table, root / "part-000.parquet", compression="snappy")
            parquet.write_table(table.slice(0, 1), root / "part-001.parquet", compression=None)
            (root / "_SUCCESS").touch()
            with patch.object(parquet, "read_table", side_effect=AssertionError("metadata must not scan rows")):
                metadata = utils._output_metadata(root, True)
            self.assertEqual(metadata["file_count"], 2)
            self.assertEqual(metadata["rows"], 3)
            self.assertEqual(metadata["compression"], ["SNAPPY", "UNCOMPRESSED"])
            self.assertEqual(metadata["schema"][1]["type"], "float")
            self.assertEqual([item["rows"] for item in metadata["files"]], [2, 1])
            self.assertNotIn("metadata_error", metadata)
            (root / "part-broken.parquet").write_bytes(b"partial output")
            partial = utils._output_metadata(root, False)
            self.assertEqual(partial["file_count"], 3)
            self.assertFalse(partial["attempt_succeeded"])
            self.assertIsNone(partial["rows"])
            self.assertIsNone(partial["schema"])
            self.assertIsNone(partial["compression"])
            self.assertIn("metadata_error", partial)
            self.assertEqual(sum(item["rows"] or 0 for item in partial["files"]), 3)

    @unittest.skipUnless(shutil.which("git"), "git unavailable")
    def test_source_dirty_excludes_generated_history_reports_and_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("utils.py", "benchmarks.jsonl", "BENCHMARKS.html"):
                (root / name).write_text("original\n")
            environment = dict(
                os.environ,
                GIT_AUTHOR_NAME="Fixture",
                GIT_AUTHOR_EMAIL="fixture@example.invalid",
                GIT_COMMITTER_NAME="Fixture",
                GIT_COMMITTER_EMAIL="fixture@example.invalid",
            )
            for command in (("init",), ("add", "."), ("commit", "-m", "fixture")):
                subprocess.run(
                    ["git", "-c", "commit.gpgsign=false", *command],
                    cwd=root,
                    env=environment,
                    check=True,
                    capture_output=True,
                )
            (root / "benchmarks.jsonl").write_text("new timing\n")
            (root / "BENCHMARKS.html").write_text("new report\n")
            (root / "data").mkdir()
            (root / "data" / "output.parquet").write_text("generated\n")
            with patch.object(utils, "__file__", str(root / "utils.py")):
                metadata = utils._source_metadata()
                self.assertIn(len(metadata["benchmark_revision"]), (40, 64))
                self.assertFalse(metadata["benchmark_dirty"])
                (root / "utils.py").write_text("changed source\n")
                self.assertTrue(utils._source_metadata()["benchmark_dirty"])
                (root / "utils.py").write_text("original\n")
                (root / "new_source.py").write_text("new code\n")
                self.assertTrue(utils._source_metadata()["benchmark_dirty"])

    def test_resource_metadata_keeps_observed_limits_and_unknown_affinity(self):
        environment = {"OMP_NUM_THREADS": "2", "POLARS_MAX_THREADS": "3"}
        with (
            patch.dict(os.environ, environment, clear=True),
            patch.object(utils.os, "cpu_count", return_value=None),
            patch.object(utils.os, "sched_getaffinity", side_effect=OSError("not available"), create=True),
        ):
            metadata = utils._resource_metadata()
        self.assertIsNone(metadata["cpu_count"])
        self.assertIsNone(metadata["cpu_affinity_count"])
        self.assertEqual(metadata["thread_environment"], environment)
        self.assertIn("cpu_affinity_count", metadata["metadata_errors"])
        self.assertIn("os_limits", metadata)


class BenchmarkRunnerRepetitionTests(unittest.TestCase):
    def test_invalid_environment_counts_abort_before_any_setup(self):
        for name, value in (
            ("BENCHMARK_WARMUPS", "-1"),
            ("BENCHMARK_WARMUPS", ""),
            ("BENCHMARK_WARMUPS", "１"),
            ("BENCHMARK_REPETITIONS", ""),
            ("BENCHMARK_REPETITIONS", "0"),
            ("BENCHMARK_REPETITIONS", "1.5"),
            ("BENCHMARK_REPETITIONS", " 2"),
            ("BENCHMARK_REPETITIONS", "$(touch unsafe)"),
        ):
            with self.subTest(name=name, value=value), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                uv = root / "uv"
                uv.write_text("#!/bin/sh\ntouch setup-started\nexit 99\n")
                uv.chmod(0o755)
                environment = dict(
                    os.environ, PATH=f"{root}:{os.environ['PATH']}", BENCHMARK_WARMUPS="1", BENCHMARK_REPETITIONS="5"
                )
                environment[name] = value
                result = subprocess.run(
                    [sys.executable, str(ROOT / "run_benchmark.py"), "--plain"],
                    cwd=directory,
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn(name, result.stdout + result.stderr)
                self.assertEqual(list(root.iterdir()), [uv])


if __name__ == "__main__":
    unittest.main()
