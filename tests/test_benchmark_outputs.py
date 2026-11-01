import json
import unittest

import pyarrow as pa
import pyarrow.parquet as pq
from benchmark_fixtures import BenchmarkFixture


class BenchmarkOutputTests(BenchmarkFixture):
    def read_snappy_output(self, name):
        parquet = pq.ParquetFile(self.root / "data/out" / name)
        self.assertEqual(
            {
                parquet.metadata.row_group(group).column(column).compression
                for group in range(parquet.metadata.num_row_groups)
                for column in range(parquet.metadata.num_columns)
            },
            {"SNAPPY"},
        )
        return parquet

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


if __name__ == "__main__":
    unittest.main()
