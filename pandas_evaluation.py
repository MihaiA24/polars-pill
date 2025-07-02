from datetime import datetime

import pandas as pd
from schemas import pd_schema
import argparse
from utils import save_execution_time

parser = argparse.ArgumentParser()
parser.add_argument("--file_path", type=str)
parser.add_argument("--file_type", type=str, default="csv")

args = parser.parse_args()

start_time = datetime.now()
# Read the CSV with the schema
df = pd.read_csv(args.file_path, engine="pyarrow", dtype=pd_schema)
df["event_time"] = pd.to_datetime(df["event_time"], format="%Y-%m-%d %H:%M:%S %Z")
df = df.groupby("product_id", as_index=False).agg(sum_price=("price", "median")).query("sum_price > 500")
df.to_parquet(f"{args.file_path}_pandas.parquet")

duration = (datetime.now() - start_time).total_seconds()
save_execution_time("Pandas", args.file_path, duration)
