from datetime import datetime

import polars as pl
from schemas import pl_schema
import argparse
from utils import save_execution_time

parser = argparse.ArgumentParser()
parser.add_argument("--file_path", type=str)
parser.add_argument("--file_type", type=str, default="csv")

args = parser.parse_args()

start_time = datetime.now()
# Data load on memory
if args.file_type == "parquet":
    df = pl.read_parquet(args.file_path)
else:
    df = pl.read_csv(args.file_path, schema=pl_schema)

# Operations done
df = (
    df.with_columns(pl.col("event_time").str.to_datetime(format="%Y-%m-%d %H:%M:%S %Z"))
    .group_by("product_id")
    .agg(pl.col("price").median().alias("sum_price"))
    .filter(pl.col("sum_price") > 500)
)



df.write_parquet(f"{args.file_path}_polars.parquet", compression="snappy")
duration = (datetime.now() - start_time).total_seconds()
save_execution_time("Polars Eager", args.file_path, duration)
