import argparse
import logging
import sys
from time import perf_counter

from utils import PROCESS_STARTED, add_benchmark_arguments, run_benchmark, save_execution_time

# isort: split

import pandas as pd

from schemas import pd_schema

logger = logging.getLogger(__name__)


def ecommerce_execution(file_path: str) -> bool:
    duration = error = None
    try:
        start_time = perf_counter()
        df = pd.read_csv(file_path, engine="pyarrow", dtype=pd_schema)
        df["event_time"] = pd.to_datetime(df["event_time"], format="%Y-%m-%d %H:%M:%S %Z")
        df = df.groupby("product_id", as_index=False).agg(sum_price=("price", "median")).query("sum_price > 500")
        df.to_parquet("data/out/pandas.parquet", index=False, compression="snappy")

        duration = perf_counter() - start_time
    except Exception as e:
        logger.exception("Pandas benchmark failed")
        error = f"{type(e).__name__}: {e}"
    save_execution_time(
        "Pandas", duration, "CPU", "eager", file_path, "simple", version=pd.__version__, error=error, input_format="csv"
    )
    return error is None


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--file_path", type=str)
    add_benchmark_arguments(parser)

    args = parser.parse_args()
    if not args.file_path or not args.file_path.strip():
        parser.error("--file_path is required for ecommerce")

    success = run_benchmark(
        lambda: ecommerce_execution(args.file_path),
        warmups=args.warmups,
        repetitions=args.repetitions,
        process_started=PROCESS_STARTED,
        input_paths=(args.file_path,),
        output_path="data/out/pandas.parquet",
        profile_memory=args.profile_memory,
    )
    sys.exit(0 if success else 1)
