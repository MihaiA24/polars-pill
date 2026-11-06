import json
import shutil
import unittest

from benchmark_fixtures import BenchmarkFixture


class BenchmarkFailureTests(BenchmarkFixture):
    def assert_failed_attempt(self, script, *args):
        history = self.root / "benchmarks.jsonl"
        original = b'{"library":"historical fixture","duration_seconds":1.0,"error":null}\n'
        history.write_bytes(original)
        self.run_cli(script, *args, expected_status=1)
        contents = history.read_bytes()
        self.assertTrue(contents.startswith(original))
        records = [json.loads(line) for line in contents.splitlines()]
        self.assertEqual(len(records), 2, "Failure must abort before warm repetitions")
        failure = records[-1]
        self.assertIsNone(failure["duration_seconds"])
        self.assertIsNone(failure["total_seconds"])
        self.assertTrue(failure["error"])
        self.assertEqual(failure["phase"], "cold")
        self.assertEqual(failure["repetition"], 1)
        return failure

    def test_polars_ecommerce_read_failures_are_saved_and_exit_nonzero(self):
        for mode in ("eager", "lazy"):
            with self.subTest(mode=mode):
                failure = self.assert_failed_attempt(
                    "polars_evaluation.py", "--file_path", "missing.csv", "--mode", mode
                )
                self.assertIn("FileNotFoundError", failure["error"])

    def test_polars_nyc_read_failure_is_saved_and_exits_nonzero(self):
        failure = self.assert_failed_attempt("polars_evaluation.py", "--dataset_type", "nyc-green")
        self.assertIn("FileNotFoundError", failure["error"])

    def test_pandas_read_failure_is_saved_and_exits_nonzero(self):
        failure = self.assert_failed_attempt("pandas_evaluation.py", "--file_path", "missing.csv")
        self.assertIn("FileNotFoundError", failure["error"])

    def test_output_write_failures_are_saved_and_exit_nonzero(self):
        events = self.write_ecommerce()
        for script, sink, args in (
            ("polars_evaluation.py", "polars.parquet", ("--mode", "eager")),
            ("polars_evaluation.py", "polars.parquet", ("--mode", "lazy")),
            ("pandas_evaluation.py", "pandas.parquet", ()),
        ):
            with self.subTest(script=script, args=args):
                (self.root / "data/out" / sink).mkdir(exist_ok=True)
                self.assert_failed_attempt(script, "--file_path", events, *args)

    @unittest.skipUnless(shutil.which("java"), "Spark requires Java")
    def test_spark_read_failures_are_saved_and_exit_nonzero(self):
        for args in (("--file_path", "missing.csv"), ("--dataset_type", "nyc-green")):
            with self.subTest(args=args):
                self.assert_failed_attempt("pyspark_evaluation.py", *args)

    def test_invalid_arguments_keep_argparse_exit_status_without_record(self):
        self.run_cli("polars_evaluation.py", "--unknown-option", expected_status=2)
        self.assertFalse((self.root / "benchmarks.jsonl").exists())

    def test_missing_ecommerce_path_is_usage_error_without_corrupting_history(self):
        for script in ("polars_evaluation.py", "pandas_evaluation.py", "pyspark_evaluation.py"):
            if script.startswith("pyspark") and not shutil.which("java"):
                continue
            for args in ((), ("--file_path", " ")):
                with self.subTest(script=script, args=args):
                    self.run_cli(script, *args, expected_status=2)
                    self.assertFalse((self.root / "benchmarks.jsonl").exists())
