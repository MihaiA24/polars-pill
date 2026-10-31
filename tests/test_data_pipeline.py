import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import polars as pl
from pyspark.sql import SparkSession
from pyspark.sql.types import FloatType

from schemas import default_schema, pd_schema, pl_schema, spark_schema

ROOT = Path(__file__).resolve().parents[1]


class DataPipelineTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.taxi = self.root / "data/nyc-taxi"
        self.taxi.mkdir(parents=True)

    def run_script(self, script, *args):
        environment = {
            **os.environ,
            "PYTHONPATH": str(ROOT),
            "POLARS_MAX_THREADS": "2",
            "SPARK_LOCAL_IP": "127.0.0.1",
            "PYSPARK_PYTHON": sys.executable,
            "PYSPARK_SUBMIT_ARGS": (
                "--driver-memory 1g --conf spark.sql.shuffle.partitions=2 "
                "--conf spark.default.parallelism=2 --conf spark.ui.enabled=false pyspark-shell"
            ),
        }
        result = subprocess.run(
            [sys.executable, str(ROOT / script), *map(str, args)],
            cwd=self.root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def trips(self):
        pickup = datetime.fromisoformat("2081-01-01 12:00:00")
        frame = pl.DataFrame(
            {
                "tpep_pickup_datetime": [pickup] * 3,
                "tpep_dropoff_datetime": [pickup + timedelta(seconds=seconds) for seconds in (30, 90, 90)],
                "PULocationID": [1, 1, 2],
                "DOLocationID": [2, 2, 1],
                "trip_distance": [1.0, 2.0, 2.0],
                "fare_amount": [2.0, 6.0, 6.0],
                "total_amount": [3.0, 7.0, 7.0],
                "tip_amount": [1.0, 1.0, 1.0],
                "airport_fee": [0.0, 0.0, 0.0],
            }
        )
        return frame.cast({name: default_schema[name] for name in frame.columns})

    def write_month(self, color, month, frame):
        path = self.taxi / color / "2024" / f"{color}_tripdata-2024-{month:02}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.write_parquet(path)
        return path

    def write_ecommerce(self):
        for month in ("Oct", "Nov"):
            (self.root / f"data/2019-{month}.csv").write_text(
                "event_time,event_type,product_id,category_id,category_code,brand,price,user_id,user_session\n"
                "2019-10-01 00:00:00 UTC,view,1,1,phones,brand,500.000001,1,session\n"
                "2019-10-01 00:00:00 UTC,view,2,1,phones,brand,500,1,session\n"
                "2019-10-01 00:00:00 UTC,view,3,1,phones,brand,499.999999,1,session\n"
                "2019-10-01 00:00:00 UTC,view,4,1,phones,brand,500.01,1,session\n",
                encoding="utf-8",
            )

    def test_preprocessing_normalization_idempotence_and_price_precision(self):
        canonical = self.trips().head(1)
        green = canonical.rename(
            {
                "tpep_pickup_datetime": "lpep_pickup_datetime",
                "tpep_dropoff_datetime": "lpep_dropoff_datetime",
                "airport_fee": "ehail_fee",
            }
        ).with_columns(pl.lit(1, dtype=pl.Int64).alias("trip_type"))
        yellow = canonical.rename({"airport_fee": "Airport_fee"})
        files = [self.write_month("green", 1, green), self.write_month("yellow", 1, yellow)]
        files.append(self.write_month("green", 2, canonical))
        files.append(self.write_month("yellow", 2, canonical.with_columns(pl.col("fare_amount").cast(pl.Float64))))
        self.write_ecommerce()
        self.run_script("00_preprocess.py")

        def assert_normalized(paths):
            for path in paths:
                with self.subTest(path=path.name):
                    frame = pl.read_parquet(path)
                    self.assertEqual(frame.columns, [*canonical.columns, "year", "month"])
                    self.assertEqual(frame.drop("year", "month").schema, canonical.schema)
                    self.assertEqual(frame["year"].to_list(), [2024])
                    self.assertEqual(frame["month"].to_list(), [int(path.stem[-2:])])

        def snapshots(paths):
            return [(path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns) for path in paths]

        assert_normalized(files)
        before = snapshots(files)
        mixed = [self.write_month("green", 3, green), self.write_month("yellow", 3, yellow)]
        self.run_script("00_preprocess.py")
        self.assertEqual(snapshots(files), before)
        files.extend(mixed)
        assert_normalized(files)
        for color in ("green", "yellow"):
            self.assertEqual(pl.read_parquet(self.taxi / f"{color}.parquet").height, 3)
        before = snapshots(files)
        self.run_script("00_preprocess.py")
        self.assertEqual(snapshots(files), before)

        parquet = self.root / "data/2019-Oct.parquet"
        self.assertEqual(pl.read_parquet_schema(parquet)["price"], pl.Float32)
        csv = self.root / "data/2019-Oct.csv"
        for frame in (pl.read_csv(csv, schema=pl_schema), pl.read_parquet(parquet)):
            self.assertEqual(frame["price"].to_list(), [500.0, 500.0, 500.0, 500.010009765625])
            self.assertEqual(frame.filter(pl.col("price") > 500)["product_id"].to_list(), [4])
        pandas = pd.read_csv(csv, engine="pyarrow", dtype=pd_schema)
        self.assertEqual(pandas["price"].tolist(), [500.0, 500.0, 500.0, 500.010009765625])
        self.assertEqual(pandas.loc[pandas["price"] > 500, "product_id"].tolist(), [4])

    @unittest.skipUnless(shutil.which("java"), "Spark requires Java")
    def test_spark_float32_csv_matches_existing_parquet(self):
        self.write_ecommerce()
        csv = self.root / "data/2019-Oct.csv"
        parquet = csv.with_suffix(".parquet")
        pl.scan_csv(csv, schema=pl_schema).sink_parquet(parquet)
        previous_directory = Path.cwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, previous_directory)

        with (
            SparkSession.builder.master("local[1]")
            .config("spark.ui.enabled", "false")
            .config("spark.driver.memory", "1g")
            .getOrCreate()
        ) as spark:
            for frame in (
                spark.read.option("header", "true").schema(spark_schema).csv(str(csv)),
                spark.read.parquet(str(parquet)),
            ):
                self.assertIsInstance(frame.schema["price"].dataType, FloatType)
                self.assertEqual([row[0] for row in frame.filter("price > 500").select("product_id").collect()], [4])

    def check_nyc(self, script):
        self.trips().write_parquet(self.taxi / "trips.parquet")
        (self.taxi / "taxi_zone_lookup.csv").write_text(
            "LocationID,Borough,Zone,service_zone\n1,A,Zone A,Boro\n2,B,Zone B,Boro\n", encoding="utf-8"
        )
        self.run_script(script, "--file_path", "data/nyc-taxi/trips.parquet")
        output = self.taxi / "out"
        efficiency_path = output / "efficiency.parquet"
        efficiency = pl.read_parquet(
            str(efficiency_path / "*.parquet") if efficiency_path.is_dir() else efficiency_path
        ).sort("tpep_dropoff_datetime")
        self.assertEqual(efficiency["trip_duration_minutes"].to_list(), [0.5, 1.5, 1.5])
        self.assertEqual(efficiency["revenue_per_minute"].to_list(), [4.0, 4.0, 4.0])
        borough_path = output / "efficiency_by_borough.csv"
        boroughs = pl.read_csv(str(borough_path / "part-*.csv") if borough_path.is_dir() else borough_path)
        boroughs = boroughs.sort("PU_Borough")
        self.assertEqual(boroughs["trip_count"].to_list(), [2, 1])
        self.assertAlmostEqual(boroughs["percentage_of_trips"][0], 200 / 3)
        self.assertAlmostEqual(boroughs["percentage_of_trips"][1], 100 / 3)
        self.assertAlmostEqual(boroughs["percentage_of_trips"].sum(), 100)

    def test_nyc_polars_fractional_durations_and_shares(self):
        self.check_nyc("nyc/polars_evaluation.py")

    @unittest.skipUnless(shutil.which("java"), "Spark requires Java")
    def test_nyc_spark_fractional_durations_and_shares(self):
        self.check_nyc("nyc/pypsark_evaluation.py")

    @unittest.skipUnless(shutil.which("java"), "Spark requires Java")
    def test_spark_benchmark_zone_joins_keep_cross_zone_trips(self):
        trips = self.trips().head(2).with_columns(pl.Series("DOLocationID", [2, 1], dtype=pl.UInt16))
        trips.write_parquet(self.taxi / "green.parquet")
        (self.taxi / "taxi_zone_lookup.csv").write_text(
            "LocationID,Borough,Zone,service_zone\n1,A,Zone A,Boro\n2,B,Zone B,Boro\n", encoding="utf-8"
        )
        for query in ("simple", "complex"):
            with self.subTest(query=query):
                self.run_script("pyspark_evaluation.py", "--dataset_type", "nyc-green", "--execution_query", query)
                result = pl.read_parquet(str(self.root / "data/out/pyspark.parquet/*.parquet")).sort("trip_distance")
                self.assertEqual(result["trip_distance"].to_list(), [1.0, 2.0])
                self.assertEqual(result["trip_count"].to_list(), [1, 1])
                self.assertEqual(result["total_revenue"].to_list(), [2.0, 6.0])
                if query == "complex":
                    self.assertEqual(result["DO_Zone"].to_list(), ["Zone B", "Zone A"])


if __name__ == "__main__":
    unittest.main()
