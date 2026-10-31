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


if __name__ == "__main__":
    unittest.main()
