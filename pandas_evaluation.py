import argparse
from time import perf_counter
from typing import Literal

import pandas as pd

from schemas import pd_schema
from utils import save_execution_time


def ecommerce_execution(file_type: Literal["csv", "parquet"], file_path: str) -> None:
    duration = error = None
    try:
        start_time = perf_counter()
        # Read the CSV with the schema
        df = pd.read_csv(file_path, engine="pyarrow", dtype=pd_schema)
        df["event_time"] = pd.to_datetime(df["event_time"], format="%Y-%m-%d %H:%M:%S %Z")
        df = df.groupby("product_id", as_index=False).agg(sum_price=("price", "median")).query("sum_price > 500")
        df.to_parquet("data/out/pandas.parquet")

        duration = perf_counter() - start_time
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
    save_execution_time("Pandas", duration, "CPU", "eager", file_path, "simple", version=pd.__version__, error=error)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--file_path", type=str)
    parser.add_argument("--file_type", type=str, default="csv")

    args = parser.parse_args()

    ecommerce_execution(args.file_type, args.file_path)
