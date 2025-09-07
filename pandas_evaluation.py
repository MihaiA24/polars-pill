from datetime import datetime
from typing import Literal

import pandas as pd
from schemas import pd_schema
import argparse
from utils import save_execution_time


def ecommerce_execution(file_type: Literal["csv", "parquet"], file_path: str) -> None:
    try:
        start_time = datetime.now()
        # Read the CSV with the schema
        df = pd.read_csv(file_path, engine="pyarrow", dtype=pd_schema)
        df["event_time"] = pd.to_datetime(df["event_time"], format="%Y-%m-%d %H:%M:%S %Z")
        df = df.groupby("product_id", as_index=False).agg(sum_price=("price", "median")).query("sum_price > 500")
        df.to_parquet("data/out/pandas.parquet")

        duration = (datetime.now() - start_time).total_seconds()
    except Exception as e:
        duration = "Error"
    save_execution_time("Pandas", duration, "CPU", "eager", file_path, "Simple")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--file_path", type=str)
    parser.add_argument("--file_type", type=str, default="csv")

    args = parser.parse_args()

    ecommerce_execution(args.file_type, args.file_path)
