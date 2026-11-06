import json
import os
import shutil
import unittest
from datetime import datetime, timedelta

import pyarrow as pa
import pyarrow.parquet as pq
from benchmark_fixtures import BenchmarkFixture

COLUMNS = ["PULocationID", "trip_count", "total_revenue", "avg_fare", "avg_distance", "avg_tip"]
EXPECTED = [
    (None, 1, 16.0, 16.0, 4.0, None),
    (1, 2, 12.0, 6.0, 3.0, 2.0),
    (2, 1, 12.0, 12.0, 3.0, -3.0),
    (999, 1, 24.0, 24.0, 6.0, 6.0),
]


class DateWindowBenchmarkTests(BenchmarkFixture):
    def write_window_fixture(self, color, *, empty=False):
        start = datetime(2019, 10, 1)
        end = datetime(2019, 10, 2)
        # No zones or dropoff columns: neither snapshots nor queries may require a join.
        rows = [
            (start - timedelta(milliseconds=1), 1, 1, 1024, 1024),
            (start, 1, 1, 4, None),
            (start + timedelta(hours=12), 1, 5, 8, 2),
            (end - timedelta(milliseconds=1), 2, 3, 12, -3),
            (end, 1, 1, 1024, 1024),
            (end + timedelta(milliseconds=1), 1, 1, 1024, 1024),
            (None, 1, 1, 1024, 1024),
            (start, None, 4, 16, None),
            (start, 999, 6, 24, 6),
            (start, 1, 0, 1024, 1024),
            (start, 1, -1, 1024, 1024),
            (start, 1, None, 1024, 1024),
            (start, 1, 1, 0, 1024),
            (start, 1, 1, -1, 1024),
            (start, 1, 1, None, 1024),
        ]
        schema = pa.schema(
            [("tpep_pickup_datetime", pa.timestamp("ms")), ("PULocationID", pa.uint16())]
            + [(name, pa.float32()) for name in ("trip_distance", "fare_amount", "tip_amount")]
        )
        names = schema.names
        table = pa.Table.from_pylist(
            [dict(zip(names, (end if empty and row[0] is not None else row[0], *row[1:]))) for row in rows],
            schema=schema,
        )
        path = self.root / f"data/nyc-taxi/{color}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        # Several row groups make the fixture independent of pruning assumptions.
        pq.write_table(table, path, row_group_size=3, compression="snappy")
        return path

    def check_window(self, script, output, color, *args, empty=False):
        source = self.write_window_fixture(color, empty=empty)
        self.assertFalse((source.parent / "taxi_zone_lookup.csv").exists())
        input_schema = pq.read_schema(source)
        self.assertEqual(input_schema.field("tpep_pickup_datetime").type, pa.timestamp("ms"))
        self.run_cli(script, "--dataset_type", f"nyc-{color}", "--execution_query", "date-window", *args)
        output_path = self.root / "data/out" / output
        table = pq.read_table(output_path)
        self.assertEqual(table.column_names, COLUMNS)
        rows = [tuple(row[name] for name in COLUMNS) for row in table.to_pylist()]
        ordered = sorted(rows, key=lambda row: (row[0] is not None, row[0] or 0))
        self.assertEqual(ordered, [] if empty else EXPECTED)
        if script != "pyspark_evaluation.py":
            self.assertEqual(rows, ordered)
        if script == "polars_evaluation.py":
            self.assertEqual(table.schema.field("PULocationID").type, pa.uint16())
            for name in COLUMNS[2:]:
                self.assertEqual(table.schema.field(name).type, pa.float32())
        for part in [output_path] if output_path.is_file() else output_path.glob("*.parquet"):
            parquet = pq.ParquetFile(part)
            for group in range(parquet.metadata.num_row_groups):
                for column in range(parquet.metadata.num_columns):
                    self.assertEqual(parquet.metadata.row_group(group).column(column).compression, "SNAPPY")

        records = [json.loads(line) for line in (self.root / "benchmarks.jsonl").read_text().splitlines()][-2:]
        self.assertEqual(len(records), 2)
        for record in records:
            self.assertEqual(record["query"], "date-window")
            self.assertEqual([item["path"] for item in record["input_snapshot"]], [f"data/nyc-taxi/{color}.parquet"])
            self.assertEqual(record["validation"]["status"], "passed")
            self.assertEqual(
                record["selectivity"],
                {
                    "input_rows": 15,
                    "matched_rows": 0 if empty else 5,
                    "fraction": 0.0 if empty else 5 / 15,
                    "window_start": "2019-10-01T00:00:00",
                    "window_end": "2019-10-02T00:00:00",
                },
            )
        return ordered

    def test_cpu_clis_agree_on_half_open_window_for_both_taxi_colors(self):
        for color in ("green", "yellow"):
            for script, output, args in (
                ("duckdb_evaluation.py", "duckdb.parquet", ()),
                ("polars_evaluation.py", "polars.parquet", ("--engine", "in-memory")),
                ("polars_evaluation.py", "polars.parquet", ("--engine", "streaming")),
            ):
                with self.subTest(color=color, script=script, args=args):
                    self.check_window(script, output, color, *args)

    @unittest.skipUnless(shutil.which("java"), "Spark requires Java")
    def test_spark_agrees_on_boundaries_nulls_and_aggregates_for_both_colors(self):
        for color in ("green", "yellow"):
            with self.subTest(color=color):
                self.check_window("pyspark_evaluation.py", "pyspark.parquet", color)

    def test_cpu_clis_accept_empty_date_windows(self):
        for script, output, args in (
            ("duckdb_evaluation.py", "duckdb.parquet", ()),
            ("polars_evaluation.py", "polars.parquet", ("--engine", "in-memory")),
            ("polars_evaluation.py", "polars.parquet", ("--engine", "streaming")),
        ):
            with self.subTest(script=script, args=args):
                self.check_window(script, output, "green", *args, empty=True)

    @unittest.skipUnless(shutil.which("java"), "Spark requires Java")
    def test_spark_accepts_empty_date_windows(self):
        self.check_window("pyspark_evaluation.py", "pyspark.parquet", "yellow", empty=True)

    @unittest.skipUnless(os.environ.get("BENCHMARK_TEST_GPU") == "1", "GPU integration requires opt-in")
    def test_gpu_executors_agree_without_cpu_fallback(self):
        for engine in ("in-memory", "streaming"):
            for color in ("green", "yellow"):
                with self.subTest(engine=engine, color=color):
                    self.check_window(
                        "polars_evaluation.py", "polars.parquet", color, "--engine", engine, "--gpu_engine", "True"
                    )


if __name__ == "__main__":
    unittest.main()
