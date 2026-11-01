import os
import subprocess
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl

from schemas import default_schema

ROOT = Path(__file__).resolve().parents[1]


class BenchmarkFixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "data/out").mkdir(parents=True)

    def write_ecommerce(self):
        path = self.root / "events.csv"
        path.write_text(
            "event_time,event_type,product_id,category_id,category_code,brand,price,user_id,user_session\n"
            "2019-10-01 00:00:00 UTC,view,1,1,phones,brand,600,1,session\n"
            "2019-10-01 00:00:00 UTC,view,1,1,phones,brand,800,1,session\n"
            "2019-10-01 00:00:00 UTC,view,2,1,phones,brand,499,1,session\n"
            "2019-10-01 00:00:00 UTC,view,2,1,phones,brand,501,1,session\n"
            "2019-10-01 00:00:00 UTC,view,3,1,phones,brand,,1,session\n"
            "2019-10-01 00:00:00 UTC,view,3,1,phones,brand,600,1,session\n",
            encoding="utf-8",
        )
        return path

    def write_nyc(self):
        taxi = self.root / "data/nyc-taxi"
        taxi.mkdir(parents=True, exist_ok=True)
        pickup = datetime(2081, 1, 1, 12, tzinfo=UTC)
        frame = pl.DataFrame(
            {
                "tpep_pickup_datetime": [pickup, pickup],
                "tpep_dropoff_datetime": [pickup + timedelta(seconds=30), pickup + timedelta(seconds=90)],
                "PULocationID": [1, 2],
                "DOLocationID": [2, 1],
                "trip_distance": [1.0, 2.0],
                "fare_amount": [2.0, 6.0],
                "total_amount": [3.0, 7.0],
                "tip_amount": [1.0, 1.0],
                "airport_fee": [0.0, 0.0],
            }
        )
        path = taxi / "green.parquet"
        frame.cast({name: default_schema[name] for name in frame.columns}).write_parquet(path)
        (taxi / "taxi_zone_lookup.csv").write_text(
            "LocationID,Borough,Zone,service_zone\n1,A,Zone A,Boro\n2,B,Zone B,Boro\n", encoding="utf-8"
        )
        return path

    def run_cli(self, script, *args, expected_status=0):
        environment = {
            **os.environ,
            "PYTHONPATH": str(ROOT),
            "POLARS_MAX_THREADS": "2",
            "OMP_NUM_THREADS": "2",
            "OPENBLAS_NUM_THREADS": "2",
            "SPARK_LOCAL_IP": "127.0.0.1",
            "PYSPARK_PYTHON": sys.executable,
            "PYSPARK_SUBMIT_ARGS": (
                "--driver-memory 1g --conf spark.sql.shuffle.partitions=3 "
                "--conf spark.default.parallelism=2 --conf spark.sql.adaptive.enabled=false "
                "--conf spark.ui.enabled=false pyspark-shell"
            ),
            "JAVA_TOOL_OPTIONS": f"{os.environ.get('JAVA_TOOL_OPTIONS', '')} -XX:ActiveProcessorCount=2",
        }
        result = subprocess.run(
            [sys.executable, str(ROOT / script), *map(str, args), "--warmups", "0", "--repetitions", "1"],
            cwd=self.root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        self.assertEqual(result.returncode, expected_status, result.stdout + result.stderr)
        return result
