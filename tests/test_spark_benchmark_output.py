import shutil
import unittest

import pyarrow.parquet as pq
from benchmark_fixtures import BenchmarkFixture


class SparkBenchmarkOutputTests(BenchmarkFixture):
    @unittest.skipUnless(shutil.which("java"), "Spark requires Java")
    def test_ecommerce_writes_one_nonempty_snappy_part_with_exact_medians(self):
        events = self.write_ecommerce()
        self.run_cli("pyspark_evaluation.py", "--file_path", events, "--file_type", "csv")

        output = self.root / "data/out/pyspark_ecommerce"
        parts = sorted(output.rglob("part-*.parquet"))
        self.assertEqual(len(parts), 1, parts)
        self.assertTrue(parts[0].is_file())
        self.assertGreater(parts[0].stat().st_size, 0)

        parquet = pq.ParquetFile(parts[0])
        self.assertEqual(parquet.schema_arrow.names, ["product_id", "sum_price"])
        self.assertEqual(parquet.metadata.num_rows, 2)
        rows = sorted((row["product_id"], row["sum_price"]) for row in parquet.read().to_pylist())
        self.assertEqual(rows, [(1, 700.0), (3, 600.0)])
        self.assertGreater(parquet.metadata.num_row_groups, 0)
        codecs = {
            parquet.metadata.row_group(group).column(column).compression
            for group in range(parquet.metadata.num_row_groups)
            for column in range(parquet.metadata.num_columns)
        }
        self.assertEqual(codecs, {"SNAPPY"})


if __name__ == "__main__":
    unittest.main()
