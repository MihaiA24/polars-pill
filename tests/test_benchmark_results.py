import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import polars as pl

from polars_evaluation import ecommerce_execution, nyc_taxi_execution
from utils import save_execution_time


class BenchmarkRecordingTests(unittest.TestCase):
    def test_runtime_versions_and_failures_append_without_losing_results(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.chdir(directory):
            Path("README.md").write_text("documentation\n")
            Path("events.csv").write_text(
                "event_time,event_type,product_id,category_id,category_code,brand,price,user_id,user_session\n"
                "2019-10-01 00:00:00 UTC,view,1,1,phones,brand,600,1,session\n"
            )
            ecommerce_execution("csv", "events.csv", "eager")
            path = Path("benchmarks.jsonl")
            original = path.read_text()
            with contextlib.redirect_stderr(io.StringIO()):
                nyc_taxi_execution("nyc-green")
            self.assertTrue(path.read_text().startswith(original))
            success, failure = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(success["version"], pl.__version__)
            self.assertEqual(success["library"], "Polars eager")
            self.assertIsInstance(success["duration_seconds"], float)
            self.assertGreaterEqual(success["duration_seconds"], 0)
            self.assertIsNone(success["error"])
            self.assertEqual(failure["version"], pl.__version__)
            self.assertIsNone(failure["duration_seconds"])
            self.assertIn("FileNotFoundError", failure["error"])
            self.assertEqual(Path("README.md").read_text(), "documentation\n")

    def test_non_finite_duration_cannot_corrupt_existing_history(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.chdir(directory):
            save_execution_time(
                "PySpark", 1.234567, "CPU", "lazy", "sample.csv", "simple", version="4.3.0", total_duration=2.5
            )
            path = Path("benchmarks.jsonl")
            original = path.read_text()
            with self.assertRaises(ValueError):
                save_execution_time("PySpark", float("nan"), "CPU", "lazy", "sample.csv", "simple", version="4.3.0")
            self.assertEqual(path.read_text(), original)
            record = json.loads(original)
            self.assertEqual(record["duration_seconds"], 1.234567)
            self.assertEqual(record["total_seconds"], 2.5)


if __name__ == "__main__":
    unittest.main()
