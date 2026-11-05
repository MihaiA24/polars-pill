import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class BenchmarkSetupTests(unittest.TestCase):
    def test_failed_sync_preserves_existing_results(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            executable = work / "uv"
            executable.write_text("#!/bin/sh\nexit 23\n")
            executable.chmod(0o755)
            (work / "benchmarks.jsonl").write_text('{"duration_seconds": 1.25}\n')
            (work / "README.md").write_text("previous README\n")
            (work / "BENCHMARKS.html").write_text("previous report\n")
            environment = dict(os.environ, PATH=f"{work}:{os.environ['PATH']}")
            result = subprocess.run(
                ["bash", str(ROOT / "run_benchmark.sh")],
                check=False,
                cwd=work,
                env=environment,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
            self.assertEqual((work / "benchmarks.jsonl").read_text(), '{"duration_seconds": 1.25}\n')
            self.assertEqual((work / "README.md").read_text(), "previous README\n")
            self.assertEqual((work / "BENCHMARKS.html").read_text(), "previous report\n")

    def test_matrix_preserves_failures_and_still_generates_report(self):
        for benchmark_status, report_status, expected_status in ((17, 0, 1), (0, 29, 29), (17, 29, 29), (0, 0, 0)):
            with (
                self.subTest(benchmark_status=benchmark_status, report_status=report_status),
                tempfile.TemporaryDirectory() as directory,
            ):
                work = Path(directory)
                (work / ".venv/bin").mkdir(parents=True)
                (work / ".venv/bin/activate").write_text("deactivate() { :; }\n")
                executable = work / "python"
                executable.write_text(
                    "#!/bin/sh\n"
                    'if [ "$1" = "pandas_evaluation.py" ]; then exit "$BENCHMARK_STATUS"; fi\n'
                    "touch later-case-ran\n"
                )
                executable.chmod(0o755)
                executable = work / "uv"
                executable.write_text(
                    '#!/bin/sh\nif [ "$1" = "run" ]; then\n  touch report-generated\n  exit "$REPORT_STATUS"\nfi\n'
                )
                executable.chmod(0o755)
                environment = dict(
                    os.environ,
                    PATH=f"{work}:{os.environ['PATH']}",
                    BENCHMARK_STATUS=str(benchmark_status),
                    REPORT_STATUS=str(report_status),
                )
                result = subprocess.run(
                    ["bash", str(ROOT / "run_benchmark.sh")],
                    check=False,
                    cwd=work,
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                self.assertTrue((work / "later-case-ran").exists(), result.stdout + result.stderr)
                self.assertTrue((work / "report-generated").exists(), result.stdout + result.stderr)
                self.assertEqual(result.returncode, expected_status, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
