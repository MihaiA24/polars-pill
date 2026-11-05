import json
import unittest

import duckdb
import pyarrow as pa
import pyarrow.csv as pc
import pyarrow.parquet as pq
from benchmark_fixtures import BenchmarkFixture


class DuckDBBenchmarkTests(BenchmarkFixture):
    def records(self):
        return [json.loads(line) for line in (self.root / "benchmarks.jsonl").read_text().splitlines()]

    def read_output(self):
        parquet = pq.ParquetFile(self.root / "data/out/duckdb.parquet")
        self.assertEqual(
            {
                parquet.metadata.row_group(group).column(column).compression
                for group in range(parquet.metadata.num_row_groups)
                for column in range(parquet.metadata.num_columns)
            },
            {"SNAPPY"},
        )
        return parquet

    def assert_success_records(self, dataset, query):
        records = self.records()[-2:]
        self.assertEqual([(row["phase"], row["repetition"]) for row in records], [("cold", 1), ("warm", 1)])
        self.assertEqual(records[0]["batch_id"], records[1]["batch_id"])
        for row in records:
            self.assertEqual(
                (row["library"], row["version"], row["device"], row["engine"], row["backend_version"]),
                ("DuckDB", duckdb.__version__, "CPU", "native", None),
            )
            self.assertEqual((row["dataset"], row["query"]), (str(dataset), query))
            self.assertIsNone(row["error"])
            self.assertGreaterEqual(row["duration_seconds"], 0)
            self.assertGreaterEqual(row["total_seconds"], row["duration_seconds"])
            self.assertTrue(row["output"]["attempt_succeeded"])

    def test_ecommerce_csv_and_float32_parquet_have_native_medians(self):
        events = self.write_ecommerce().rename(self.root / "customer's events.csv")
        with events.open("a", encoding="utf-8") as output:
            for product, price in ((4, ""), (5, "500.000001"), (6, "600"), (6, "800"), (6, "1000")):
                output.write(f"2019-10-01 00:00:00 UTC,view,{product},1,phones,brand,{price},1,session\n")
        prepared = self.root / "prepared events.parquet"
        table = pc.read_csv(
            events,
            convert_options=pc.ConvertOptions(
                column_types={"event_time": pa.string(), "product_id": pa.int32(), "price": pa.float32()}
            ),
        )
        pq.write_table(table, prepared)
        (self.root / "data/out").rmdir()
        history = self.root / "benchmarks.jsonl"
        prefix = b""
        for file_type, path in (("csv", events), ("parquet", prepared)):
            with self.subTest(file_type=file_type):
                self.run_cli("duckdb_evaluation.py", "--file_path", path, "--file_type", file_type)
                parquet = self.read_output()
                self.assertEqual(
                    [(field.name, field.type) for field in parquet.schema_arrow],
                    [("product_id", pa.int32()), ("sum_price", pa.float32())],
                )
                self.assertEqual(
                    sorted(parquet.read().to_pylist(), key=lambda row: row["product_id"]),
                    [
                        {"product_id": 1, "sum_price": 700.0},
                        {"product_id": 3, "sum_price": 600.0},
                        {"product_id": 6, "sum_price": 800.0},
                    ],
                )
                self.assert_success_records(path, "simple")
                if prefix:
                    self.assertTrue(history.read_bytes().startswith(prefix))
                prefix = history.read_bytes()
        self.assertEqual(len(self.records()), 4)

    def test_nyc_joins_multiply_and_filter_rows_with_null_first_group_order(self):
        taxi = self.root / "data/nyc-taxi"
        taxi.mkdir(parents=True)
        (taxi / "taxi_zone_lookup.csv").write_text(
            "LocationID,Borough,Zone,service_zone\n"
            "1,,Pickup,Boro\n1,A,Pickup,Boro\n1,A,Pickup,Boro\n"
            "2,,,Boro\n2,,Zone B,Boro\n2,B,Zone B,Boro\n3,C,Zone C,Boro\n",
            encoding="utf-8",
        )
        schema = pa.schema(
            [("PULocationID", pa.uint16()), ("DOLocationID", pa.uint16())]
            + [(name, pa.float32()) for name in ("trip_distance", "fare_amount", "tip_amount")]
        )
        for color, fare, tip in (("green", 10.0, 4.0), ("yellow", 14.0, 6.0)):
            pq.write_table(
                pa.Table.from_pydict(
                    {
                        "PULocationID": [3, 1, 1, 3, 99, 1],
                        "DOLocationID": [3, 2, 2, 3, 2, 99],
                        "trip_distance": [None, 1.0, 1.0, 2.0, 99.0, 98.0],
                        "fare_amount": [2.0, 4.0, 8.0, fare, 100.0, 100.0],
                        "tip_amount": [None, 1.0, 3.0, tip, 100.0, 100.0],
                    },
                    schema=schema,
                ),
                taxi / f"{color}.parquet",
            )
        null_group = {
            "trip_distance": None,
            "trip_count": 1,
            "total_revenue": 2.0,
            "avg_fare": 2.0,
            "avg_distance": None,
            "avg_tip": None,
        }
        for query, color, fare, tip in (("simple", "green", 10.0, 4.0), ("complex", "yellow", 14.0, 6.0)):
            with self.subTest(query=query, color=color):
                self.run_cli("duckdb_evaluation.py", "--dataset_type", f"nyc-{color}", "--execution_query", query)
                parquet = self.read_output()
                for name, dtype in (
                    ("trip_distance", pa.float32()),
                    ("trip_count", pa.int64()),
                    ("total_revenue", pa.float64()),
                    ("avg_fare", pa.float64()),
                    ("avg_distance", pa.float64()),
                    ("avg_tip", pa.float64()),
                ):
                    self.assertEqual(parquet.schema_arrow.field(name).type, dtype)
                last = {
                    "trip_distance": 2.0,
                    "trip_count": 1,
                    "total_revenue": fare,
                    "avg_fare": fare,
                    "avg_distance": 2.0,
                    "avg_tip": tip,
                }
                if query == "simple":
                    expected = [
                        null_group,
                        {
                            "trip_distance": 1.0,
                            "trip_count": 18,
                            "total_revenue": 108.0,
                            "avg_fare": 6.0,
                            "avg_distance": 1.0,
                            "avg_tip": 2.0,
                        },
                        last,
                    ]
                else:
                    middle = [
                        {
                            "trip_distance": 1.0,
                            "DO_Zone": zone,
                            "DO_Borough": dropoff,
                            "PU_Borough": pickup,
                            "trip_count": count,
                            "total_revenue": revenue,
                            "avg_fare": 6.0,
                            "avg_distance": 1.0,
                            "avg_tip": 2.0,
                        }
                        for zone, dropoff, pickup, count, revenue in (
                            (None, None, None, 2, 12.0),
                            (None, None, "A", 4, 24.0),
                            ("Zone B", None, None, 2, 12.0),
                            ("Zone B", None, "A", 4, 24.0),
                            ("Zone B", "B", None, 2, 12.0),
                            ("Zone B", "B", "A", 4, 24.0),
                        )
                    ]
                    zones = {"DO_Zone": "Zone C", "DO_Borough": "C", "PU_Borough": "C"}
                    expected = [null_group | zones, *middle, last | zones]
                self.assertEqual(parquet.read().to_pylist(), expected)
                self.assert_success_records(f"nyc-{color}", query)

    def test_usage_errors_do_not_append_history(self):
        history = self.root / "benchmarks.jsonl"
        original = b'{"library":"historical fixture","duration_seconds":1.0,"error":null}\n'
        history.write_bytes(original)
        for args in ((), ("--file_path", " "), ("--unknown-option",)):
            with self.subTest(args=args):
                self.run_cli("duckdb_evaluation.py", *args, expected_status=2)
                self.assertEqual(history.read_bytes(), original)
        self.assertFalse((self.root / "data/out/duckdb.parquet").exists())

    def test_missing_input_appends_one_failure_with_null_timings(self):
        history = self.root / "benchmarks.jsonl"
        original = b'{"library":"historical fixture","duration_seconds":1.0,"error":null}\n'
        history.write_bytes(original)
        self.run_cli("duckdb_evaluation.py", "--file_path", "missing.csv", expected_status=1)
        self.assertTrue(history.read_bytes().startswith(original))
        self.assertEqual(len(self.records()), 2)
        failure = self.records()[-1]
        self.assertEqual(
            (failure["library"], failure["dataset"], failure["query"]), ("DuckDB", "missing.csv", "simple")
        )
        self.assertEqual((failure["phase"], failure["repetition"]), ("cold", 1))
        self.assertIsNone(failure["duration_seconds"])
        self.assertIsNone(failure["total_seconds"])
        self.assertIsInstance(failure["error"], str)
        self.assertTrue(failure["error"])
        self.assertFalse(failure["output"]["attempt_succeeded"])
        self.assertIsNone(failure["output"]["rows"])
        self.assertFalse((self.root / "data/out/duckdb.parquet").exists())


if __name__ == "__main__":
    unittest.main()
