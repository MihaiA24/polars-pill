import json
import shutil
import unittest

import pyarrow as pa
import pyarrow.parquet as pq
from benchmark_fixtures import BenchmarkFixture


class BenchmarkOutputTests(BenchmarkFixture):
    def test_pandas_output_has_only_native_product_medians_and_snappy(self):
        events = self.write_ecommerce()
        self.run_cli("pandas_evaluation.py", "--file_path", events)
        parquet = self.read_snappy_output("pandas.parquet")
        self.assertEqual(parquet.schema_arrow.names, ["product_id", "sum_price"])
        self.assertEqual(parquet.schema_arrow.field("sum_price").type, pa.float32())
        self.assertEqual(json.loads(parquet.schema_arrow.metadata[b"pandas"])["index_columns"], [])
        self.assertEqual(
            sorted(parquet.read().to_pylist(), key=lambda row: row["product_id"]),
            [{"product_id": 1, "sum_price": 700.0}, {"product_id": 3, "sum_price": 600.0}],
        )

    def test_polars_nyc_simple_and_complex_sinks_preserve_native_aggregates_and_snappy(self):
        source = self.write_nyc()
        input_schema = pq.read_schema(source)
        for name in ("trip_distance", "fare_amount", "tip_amount"):
            self.assertEqual(input_schema.field(name).type, pa.float32())
        expected_aggregates = [
            {
                "trip_distance": 1.0,
                "trip_count": 1,
                "total_revenue": 2.0,
                "avg_fare": 2.0,
                "avg_distance": 1.0,
                "avg_tip": 1.0,
            },
            {
                "trip_distance": 2.0,
                "trip_count": 1,
                "total_revenue": 6.0,
                "avg_fare": 6.0,
                "avg_distance": 2.0,
                "avg_tip": 1.0,
            },
        ]
        for query, engine in (("simple", "in-memory"), ("complex", "streaming")):
            with self.subTest(query=query, engine=engine):
                self.run_cli(
                    "polars_evaluation.py",
                    "--dataset_type",
                    "nyc-green",
                    "--execution_query",
                    query,
                    "--engine",
                    engine,
                )
                parquet = self.read_snappy_output("polars.parquet")
                for name in ("trip_distance", "total_revenue", "avg_fare", "avg_distance", "avg_tip"):
                    self.assertEqual(parquet.schema_arrow.field(name).type, pa.float32())
                expected = expected_aggregates
                if query == "complex":
                    expected = [
                        expected_aggregates[0] | {"DO_Zone": "Zone B", "DO_Borough": "B", "PU_Borough": "A"},
                        expected_aggregates[1] | {"DO_Zone": "Zone A", "DO_Borough": "A", "PU_Borough": "B"},
                    ]
                self.assertEqual(sorted(parquet.read().to_pylist(), key=lambda row: row["trip_distance"]), expected)

    def check_filtered_nyc(self, script, output, dataset, *args):
        taxi = self.root / "data/nyc-taxi"
        taxi.mkdir(parents=True, exist_ok=True)
        path = f"data/nyc-taxi/{dataset.removeprefix('nyc-')}.parquet"
        # No zone lookup or dropoff column: this workload must not perform joins.
        pq.write_table(
            pa.table(
                {
                    "PULocationID": [2, 1, 1, 1, 1, 1, 1, 1, 1, None, 999],
                    "trip_distance": [3, 1, 5, 0, -1, None, 2, 2, 2, 4, 6],
                    "fare_amount": [12, 4, 8, 100, 100, 100, 0, -1, None, 16, 24],
                    "tip_amount": [-3, None, 2, 100, 100, 100, 100, 100, 100, None, 6],
                },
                schema=pa.schema(
                    [("PULocationID", pa.uint16())]
                    + [(name, pa.float32()) for name in ("trip_distance", "fare_amount", "tip_amount")]
                ),
            ),
            self.root / path,
        )
        self.run_cli(script, "--dataset_type", dataset, "--execution_query", "filtered", *args)
        table = pq.read_table(self.root / "data/out" / output)
        columns = ["PULocationID", "trip_count", "total_revenue", "avg_fare", "avg_distance", "avg_tip"]
        self.assertEqual(table.column_names, columns)
        rows = sorted(
            (tuple(row[name] for name in columns) for row in table.to_pylist()),
            key=lambda row: (row[0] is not None, row[0] or 0),
        )
        self.assertEqual(
            rows,
            [
                (None, 1, 16.0, 16.0, 4.0, None),
                (1, 2, 12.0, 6.0, 3.0, 2.0),
                (2, 1, 12.0, 12.0, 3.0, -3.0),
                (999, 1, 24.0, 24.0, 6.0, 6.0),
            ],
        )
        records = [json.loads(line) for line in (self.root / "benchmarks.jsonl").read_text().splitlines()][-2:]
        self.assertEqual(
            [(row["query"], [item["path"] for item in row["input_snapshot"]]) for row in records],
            [("filtered", [path]), ("filtered", [path])],
        )

    def test_filtered_nyc_polars_and_duckdb_keep_only_positive_trips_without_zone_joins(self):
        for script, output, dataset, args in (
            ("polars_evaluation.py", "polars.parquet", "nyc-green", ("--engine", "in-memory")),
            ("polars_evaluation.py", "polars.parquet", "nyc-yellow", ("--engine", "streaming")),
            ("duckdb_evaluation.py", "duckdb.parquet", "nyc-green", ()),
        ):
            with self.subTest(script=script, dataset=dataset, args=args):
                self.check_filtered_nyc(script, output, dataset, *args)

    @unittest.skipUnless(shutil.which("java"), "Spark requires Java")
    def test_filtered_nyc_spark_keeps_only_positive_trips_without_zone_joins(self):
        self.check_filtered_nyc("pyspark_evaluation.py", "pyspark.parquet", "nyc-yellow")


if __name__ == "__main__":
    unittest.main()
