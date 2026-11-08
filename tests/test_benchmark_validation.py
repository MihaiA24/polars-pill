import json
import math
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from benchmark_validation import ResultValidator


class ResultValidationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.output = self.root / "result.parquet"

    def validator(self, *inputs):
        validator = ResultValidator(inputs)
        self.addCleanup(validator.close)
        return validator

    def ecommerce(self, parquet=False):
        path = self.root / ("events.parquet" if parquet else "events.csv")
        if parquet:
            pq.write_table(
                pa.table(
                    {
                        "product_id": pa.array([1, 1, 2, 3, None], pa.int32()),
                        "price": pa.array([600, 800, 100, 900, 1000], pa.float32()),
                    }
                ),
                path,
            )
        else:
            path.write_text(
                "event_time,event_type,product_id,category_id,category_code,brand,price,user_id,user_session\n"
                "2019-10-01 00:00:00 UTC,view,1,1,x,b,600,1,s\n"
                "2019-10-01 00:00:00 UTC,view,1,1,x,b,800,1,s\n"
                "2019-10-01 00:00:00 UTC,view,2,1,x,b,100,1,s\n"
                "2019-10-01 00:00:00 UTC,view,3,1,x,b,900,1,s\n"
                "2019-10-01 00:00:00 UTC,view,,1,x,b,1000,1,s\n"
            )
        return path

    def write_ecommerce_output(self, keys=(None, 1, 3), values=(1000, 700, 900), precision=None):
        precision = pa.float32() if precision is None else precision
        pq.write_table(
            pa.table({"product_id": pa.array(keys, pa.int64()), "sum_price": pa.array(values, precision)}), self.output
        )

    def validate_ecommerce(self, validator, path):
        return validator.validate(
            {
                "dataset": str(path),
                "query": "simple",
                "input_format": "parquet" if path.suffix == ".parquet" else "csv",
            },
            self.output,
        )["validation"]

    def test_ecommerce_csv_and_parquet_validate_native_precision_without_order_or_integer_width_equality(self):
        for parquet in (False, True):
            with self.subTest(parquet=parquet):
                path = self.ecommerce(parquet)
                self.write_ecommerce_output(keys=(3, None, 1), values=(900, 1000, 700))
                result = self.validate_ecommerce(self.validator(path), path)
                self.assertEqual(result["status"], "passed", result)
                self.assertEqual((result["expected_rows"], result["observed_rows"]), (3, 3))
                self.assertEqual(result["float_tolerance"]["columns"], {"sum_price": "float32"})

    def test_wrong_values_keys_duplicates_and_nulls_never_pass(self):
        path = self.ecommerce()
        validator = self.validator(path)
        for keys, values in (
            ((None, 1, 3), (1000, 701, 900)),
            ((None, 1, 4), (1000, 700, 900)),
            ((None, 1, 3, 3), (1000, 700, 900, 900)),
            ((None, 1, 3), (None, 700, 900)),
            ((1, 3), (700, 900)),
        ):
            with self.subTest(keys=keys, values=values):
                self.write_ecommerce_output(keys, values)
                self.assertEqual(self.validate_ecommerce(validator, path)["status"], "mismatch")
        pq.write_table(pa.table({"product_id": [1], "incorrect": [700.0]}), self.output)
        self.assertEqual(self.validate_ecommerce(validator, path)["status"], "mismatch")

    def test_tolerances_follow_output_precision_not_engine_name(self):
        path = self.ecommerce()
        validator = self.validator(path)
        for precision, value, status in (
            (pa.float32(), 700.021, "passed"),
            (pa.float64(), 700.021, "mismatch"),
            (pa.float32(), 700.2, "mismatch"),
            (pa.float64(), 700.0000001, "passed"),
        ):
            with self.subTest(precision=precision, value=value):
                self.write_ecommerce_output(values=(1000, value, 900), precision=precision)
                self.assertEqual(self.validate_ecommerce(validator, path)["status"], status)

    def test_reference_is_cached_on_disk_and_close_removes_it(self):
        path = self.ecommerce()
        validator = self.validator(path)
        self.write_ecommerce_output()
        self.assertIsNone(validator._temporary)
        self.assertEqual(self.validate_ecommerce(validator, path)["status"], "passed")
        cache = Path(validator._temporary.name)
        reference = cache / "ecommerce.parquet"
        original = reference.stat().st_mtime_ns
        # The second subprocess can validate entirely against the persisted reference, without rereading inputs.
        path.unlink()
        self.assertEqual(self.validate_ecommerce(validator, path)["status"], "passed")
        self.assertEqual(reference.stat().st_mtime_ns, original)
        validator.close()
        validator.close()
        self.assertFalse(cache.exists())

    def test_validation_uses_another_process_and_does_not_import_duckdb_into_caller(self):
        import subprocess
        import sys

        path = self.ecommerce()
        self.write_ecommerce_output()
        script = (
            "import json,sys; from benchmark_validation import ResultValidator; "
            "v=ResultValidator([sys.argv[1]]); "
            "r=v.validate({'dataset':sys.argv[1],'query':'simple','input_format':'csv'},sys.argv[2]); v.close(); "
            "print(json.dumps({'result':r,'duckdb_loaded':'duckdb' in sys.modules}))"
        )
        result = subprocess.run(
            [sys.executable, "-c", script, str(path), str(self.output)],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=True,
            env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])},
        )
        response = json.loads(result.stdout)
        self.assertEqual(response["result"]["validation"]["status"], "passed")
        self.assertFalse(response["duckdb_loaded"])

    def nyc_input(self):
        path = self.root / "green.parquet"
        pq.write_table(
            pa.table(
                {
                    "PULocationID": pa.array([1, 1, 2, 999, 1, None], pa.uint16()),
                    "DOLocationID": pa.array([2, 2, 1, 1, 2, 1], pa.uint16()),
                    "trip_distance": pa.array([1, 1, 2, 3, None, 4], pa.float32()),
                    "fare_amount": pa.array([10, 20, 30, 40, 50, 60], pa.float32()),
                    "tip_amount": pa.array([2, None, 3, 4, 5, 6], pa.float32()),
                }
            ),
            path,
        )
        zones = self.root / "zones.csv"
        zones.write_text("LocationID,Borough,Zone,service_zone\n1,A,Zone A,Boro\n2,B,,Boro\n")
        return path, zones

    def write_nyc_output(self, keys, counts, revenues, fares, distances, tips, **extra_keys):
        columns = {
            name: pa.array(values, pa.float32())
            for name, values in (
                ("total_revenue", revenues),
                ("avg_fare", fares),
                ("avg_distance", distances),
                ("avg_tip", tips),
            )
        }
        columns = {**keys, **extra_keys, "trip_count": pa.array(counts, pa.uint32()), **columns}
        pq.write_table(pa.table(columns), self.output)

    def test_simple_complex_and_filtered_use_independent_join_and_group_semantics(self):
        path, zones = self.nyc_input()
        validator = self.validator(path, zones)
        for query in ("simple", "complex", "filtered"):
            with self.subTest(query=query):
                if query == "filtered":
                    self.write_nyc_output(
                        {"PULocationID": pa.array([None, 1, 2, 999], pa.uint16())},
                        [1, 2, 1, 1],
                        [60, 30, 30, 40],
                        [60, 15, 30, 40],
                        [4, 1, 2, 3],
                        [6, 2, 3, 4],
                    )
                else:
                    extra = (
                        {}
                        if query == "simple"
                        else {
                            "DO_Zone": pa.array([None, None, "Zone A"], pa.string()),
                            "DO_Borough": pa.array(["B", "B", "A"]),
                            "PU_Borough": pa.array(["A", "A", "B"]),
                        }
                    )
                    self.write_nyc_output(
                        {"trip_distance": pa.array([None, 1, 2], pa.float32())},
                        [1, 2, 1],
                        [50, 30, 30],
                        [50, 15, 30],
                        [None, 1, 2],
                        [5, 2, 3],
                        **extra,
                    )
                result = validator.validate({"dataset": "nyc-green", "query": query}, self.output)
                self.assertEqual(result["validation"]["status"], "passed", result)
                table = pq.read_table(self.output)
                # Counts are exact, unlike floating point aggregates.
                bad_counts = pa.array([value + 1 for value in table["trip_count"].to_pylist()], pa.uint32())
                pq.write_table(
                    table.set_column(table.schema.get_field_index("trip_count"), "trip_count", bad_counts), self.output
                )
                self.assertEqual(
                    validator.validate({"dataset": "nyc-green", "query": query}, self.output)["validation"]["status"],
                    "mismatch",
                )

    def test_float_grouping_keys_are_exact_even_when_aggregate_tolerance_would_allow_difference(self):
        path, zones = self.nyc_input()
        self.write_nyc_output(
            {"trip_distance": pa.array([None, 1.00001, 2], pa.float32())},
            [1, 2, 1],
            [50, 30, 30],
            [50, 15, 30],
            [None, 1, 2],
            [5, 2, 3],
        )
        result = self.validator(path, zones).validate({"dataset": "nyc-green", "query": "simple"}, self.output)
        self.assertEqual(result["validation"]["status"], "mismatch")
        self.assertEqual(result["validation"]["missing_keys"], 1)

    def test_integer_group_keys_cannot_be_rounded_into_float_keys(self):
        path = self.root / "large-ids.parquet"
        for keys in ((16777217,), (16777216, 16777217)):
            with self.subTest(keys=keys):
                pq.write_table(
                    pa.table(
                        {"product_id": pa.array(keys, pa.int32()), "price": pa.array([700] * len(keys), pa.float32())}
                    ),
                    path,
                )
                pq.write_table(
                    pa.table(
                        {"product_id": pa.array([16777216], pa.float32()), "sum_price": pa.array([700], pa.float32())}
                    ),
                    self.output,
                )
                self.assertEqual(self.validate_ecommerce(self.validator(path), path)["status"], "mismatch")
                self.write_ecommerce_output(keys=keys, values=[700] * len(keys))
                self.assertEqual(self.validate_ecommerce(self.validator(path), path)["status"], "passed")

    def test_date_window_observes_half_open_selectivity_including_null_unknown_keys(self):
        path = self.root / "yellow.parquet"
        pq.write_table(
            pa.table(
                {
                    "tpep_pickup_datetime": pa.array(
                        [
                            datetime(2019, 10, 1),
                            datetime(2019, 10, 1, 23, 59, 59),
                            datetime(2019, 10, 2),
                            datetime(2019, 9, 30, 23, 59, 59),
                            None,
                            datetime(2019, 10, 1),
                        ],
                        pa.timestamp("us"),
                    ),
                    "PULocationID": pa.array([None, 999, 1, 1, 1, 1], pa.uint16()),
                    "trip_distance": pa.array([1, 2, 1, 1, 1, 0], pa.float32()),
                    "fare_amount": pa.array([10, 20, 30, 40, 50, 60], pa.float32()),
                    "tip_amount": pa.array([None, 2, 3, 4, 5, 6], pa.float32()),
                }
            ),
            path,
            row_group_size=2,
        )
        self.write_nyc_output(
            {"PULocationID": pa.array([None, 999], pa.uint16())}, [1, 1], [10, 20], [10, 20], [1, 2], [None, 2]
        )
        result = self.validator(path).validate({"dataset": "nyc-yellow", "query": "date-window"}, self.output)
        self.assertEqual(result["validation"]["status"], "passed", result)
        self.assertEqual(
            result["selectivity"],
            {
                "input_rows": 6,
                "matched_rows": 2,
                "fraction": 1 / 3,
                "window_start": "2019-10-01T00:00:00",
                "window_end": "2019-10-02T00:00:00",
            },
        )

    def test_null_nan_and_infinities_match_only_like_for_like(self):
        path = self.root / "green.parquet"
        pq.write_table(
            pa.table(
                {
                    "PULocationID": [1, 2, 3, 4],
                    "trip_distance": [1.0] * 4,
                    "fare_amount": [10.0] * 4,
                    "tip_amount": [None, math.nan, math.inf, -math.inf],
                }
            ),
            path,
        )
        self.write_nyc_output(
            {"PULocationID": [1, 2, 3, 4]}, [1] * 4, [10] * 4, [10] * 4, [1] * 4, [None, math.nan, math.inf, -math.inf]
        )
        validator = self.validator(path)
        record = {"dataset": "nyc-green", "query": "filtered"}
        self.assertEqual(validator.validate(record, self.output)["validation"]["status"], "passed")
        for tips in (
            [0, math.nan, math.inf, -math.inf],
            [None, None, math.inf, -math.inf],
            [None, math.nan, -math.inf, -math.inf],
            [None, math.nan, 1, -math.inf],
        ):
            with self.subTest(tips=tips):
                self.write_nyc_output({"PULocationID": [1, 2, 3, 4]}, [1] * 4, [10] * 4, [10] * 4, [1] * 4, tips)
                self.assertEqual(validator.validate(record, self.output)["validation"]["status"], "mismatch")

    def test_empty_input_and_empty_output_are_valid_with_unknown_fraction(self):
        path = self.root / "green.parquet"
        pq.write_table(
            pa.table(
                {
                    "tpep_pickup_datetime": pa.array([], pa.timestamp("us")),
                    "PULocationID": pa.array([], pa.uint16()),
                    **{name: pa.array([], pa.float32()) for name in ("trip_distance", "fare_amount", "tip_amount")},
                }
            ),
            path,
        )
        self.write_nyc_output({"PULocationID": pa.array([], pa.uint16())}, [], [], [], [], [])
        result = self.validator(path).validate({"dataset": "nyc-green", "query": "date-window"}, self.output)
        self.assertEqual(result["validation"]["status"], "passed", result)
        self.assertEqual(result["selectivity"]["input_rows"], 0)
        self.assertEqual(result["selectivity"]["matched_rows"], 0)
        self.assertIsNone(result["selectivity"]["fraction"])

    def test_partitioned_outputs_and_empty_ecommerce_are_supported(self):
        path = self.ecommerce()
        self.write_ecommerce_output()
        table = pq.read_table(self.output)
        self.output.unlink()
        self.output.mkdir()
        pq.write_table(table.slice(0, 1), self.output / "part-000.parquet")
        pq.write_table(table.slice(1), self.output / "part-001.parquet")
        (self.output / "_SUCCESS").touch()
        self.assertEqual(self.validate_ecommerce(self.validator(path), path)["status"], "passed")
        empty = self.root / "empty.parquet"
        pq.write_table(pa.table({"product_id": pa.array([], pa.int32()), "price": pa.array([], pa.float32())}), empty)
        pq.write_table(table.slice(0, 0), self.root / "empty-output.parquet")
        result = self.validator(empty).validate(
            {"dataset": str(empty), "query": "simple", "input_format": "parquet"}, self.root / "empty-output.parquet"
        )
        self.assertEqual(result["validation"]["status"], "passed", result)

    def test_missing_or_invalid_outputs_and_invalid_input_are_errors_not_approved(self):
        path = self.ecommerce()
        validator = self.validator(path)
        self.assertEqual(self.validate_ecommerce(validator, path)["status"], "error")
        self.output.write_bytes(b"invalid parquet")
        self.assertEqual(self.validate_ecommerce(validator, path)["status"], "error")
        path.write_text("not,the,expected,schema\n1,2,3,4\n")
        self.write_ecommerce_output()
        self.assertEqual(self.validate_ecommerce(self.validator(path), path)["status"], "error")

    def test_actual_polars_cli_attempts_include_validation_and_disabled_memory_measurements(self):
        import subprocess
        import sys

        path = self.ecommerce()
        repository = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            [
                sys.executable,
                str(repository / "polars_evaluation.py"),
                "--file_path",
                str(path),
                "--warmups",
                "0",
                "--repetitions",
                "1",
            ],
            check=False,
            timeout=180,
            cwd=self.root,
            capture_output=True,
            text=True,
            env={**os.environ, "BENCHMARK_PROFILE_MEMORY": "0", "POLARS_MAX_THREADS": "2"},
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        records = [json.loads(line) for line in (self.root / "benchmarks.jsonl").read_text().splitlines()]
        self.assertEqual([record["phase"] for record in records], ["cold", "warm"])
        for record in records:
            self.assertEqual(record["validation"]["status"], "passed")
            self.assertEqual(record["validation"]["reference"], "duckdb-sql-v1")
            self.assertFalse(record["memory_profile"]["enabled"])
            self.assertIsNone(record["memory_profile"]["peak_rss_bytes"])
            self.assertIsNone(record["memory_profile"]["peak_gpu_memory_bytes"])
            self.assertGreaterEqual(record["total_seconds"], record["duration_seconds"])

    def test_real_validation_mismatch_exits_nonzero_and_keeps_measured_timings(self):
        import subprocess
        import sys

        path = self.ecommerce()
        repository = Path(__file__).resolve().parents[1]
        script = """
import sys
from time import perf_counter
import pyarrow as pa
import pyarrow.parquet as pq
from utils import run_benchmark, save_execution_time
def execute():
    start = perf_counter()
    pq.write_table(pa.table({'product_id': [1], 'sum_price': [42.0]}), sys.argv[2])
    duration = perf_counter() - start
    save_execution_time('Fixture', duration, 'CPU', 'test', sys.argv[1], 'simple', version='1', input_format='csv')
    return True
raise SystemExit(0 if run_benchmark(execute, input_paths=[sys.argv[1]], output_path=sys.argv[2]) else 1)
"""
        completed = subprocess.run(
            [sys.executable, "-c", script, str(path), str(self.output)],
            check=False,
            timeout=180,
            cwd=self.root,
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": str(repository), "BENCHMARK_PROFILE_MEMORY": "0"},
        )
        self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
        records = [json.loads(line) for line in (self.root / "benchmarks.jsonl").read_text().splitlines()]
        self.assertEqual(len(records), 1, records)
        record = records[0]
        self.assertEqual(record["validation"]["status"], "mismatch")
        self.assertIsNone(record["error"])
        self.assertGreater(record["duration_seconds"], 0)
        self.assertGreaterEqual(record["total_seconds"], record["duration_seconds"])
        self.assertTrue(record["output"]["attempt_succeeded"])

    def test_generic_calls_are_unchecked_without_creating_a_cache(self):
        validator = self.validator("fixture.csv")
        result = validator.validate({"dataset": "unknown", "query": "simple"}, None)
        self.assertEqual(result["validation"]["status"], "unchecked")


if __name__ == "__main__":
    unittest.main()
