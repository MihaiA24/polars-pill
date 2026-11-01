import argparse
import logging
import os
import sys
from importlib.metadata import version as package_version
from time import perf_counter
from typing import Literal

from utils import PROCESS_STARTED, add_benchmark_arguments, run_benchmark, save_execution_time

# isort: split

import polars as pl

from schemas import pl_schema, zone_schema

logger = logging.getLogger(__name__)


def ecommerce_execution(
    file_type: str, file_path: str, mode: Literal["eager", "lazy"], engine: Literal["in-memory", "streaming"]
) -> bool:
    if mode == "eager" and engine != "in-memory":
        raise ValueError("Eager mode requires the in-memory engine")
    duration = error = None
    try:
        start_time = perf_counter()
        if file_type == "parquet":
            df = pl.read_parquet(file_path) if mode == "eager" else pl.scan_parquet(file_path)
        else:
            df = (
                pl.read_csv(file_path, schema=pl_schema)
                if mode == "eager"
                else pl.scan_csv(file_path, schema=pl_schema)
            )

        df = (
            df.with_columns(pl.col("event_time").str.to_datetime(format="%Y-%m-%d %H:%M:%S %Z"))
            .group_by("product_id")
            .agg(pl.col("price").median().alias("sum_price"))
            .filter(pl.col("sum_price") > 500)
        )
        if mode == "eager":
            # Eager operations always use the in-memory engine.
            df.write_parquet("data/out/polars.parquet", compression="snappy", mkdir=True)
        else:
            df.sink_parquet("data/out/polars.parquet", engine=engine, compression="snappy", mkdir=True)
        duration = perf_counter() - start_time
    except Exception as e:
        logger.exception("Polars %s %s %s failed", mode, engine, file_path)
        error = f"{type(e).__name__}: {e}"
    save_execution_time(
        f"Polars {mode}", duration, "CPU", engine, file_path, "simple", version=pl.__version__, error=error
    )
    return error is None


def nyc_taxi_execution(
    dataset_type: Literal["nyc-green", "nyc-yellow"],
    engine: Literal["in-memory", "streaming"],
    execution_query: Literal["simple", "complex"] = "simple",
    gpu_engine: bool = False,
) -> bool:
    cpu_gpu = "GPU" if gpu_engine else "CPU"  # Needed in the error path too, so resolve it before the try.
    duration = error = backend_version = None
    try:
        backend_version = package_version("cudf-polars-cu12") if gpu_engine else None
        start_time = perf_counter()
        if engine == "in-memory" and gpu_engine:
            os.environ["POLARS_GPU_ENABLE_CUDA_MANAGED_MEMORY"] = (
                "0"  # Forcing in-memory engine to not use UVM for the benchmark
            )

        polars_engine = pl.GPUEngine(executor=engine, raise_on_fail=True) if gpu_engine else engine
        dataset = "yellow" if dataset_type == "nyc-yellow" else "green"
        out_path = "data/out/polars.parquet"
        df_zones = pl.scan_csv("data/nyc-taxi/taxi_zone_lookup.csv", schema=zone_schema)
        df = (
            pl.scan_parquet(f"data/nyc-taxi/{dataset}.parquet")
            .join(df_zones, left_on="PULocationID", right_on="LocationID")
            .rename({"Borough": "PU_Borough", "Zone": "PU_Zone", "service_zone": "PU_service_zone"})
            .join(df_zones, left_on="DOLocationID", right_on="LocationID")
            .rename({"Borough": "DO_Borough", "Zone": "DO_Zone", "service_zone": "DO_service_zone"})
        )

        if execution_query == "simple":
            df.group_by("trip_distance").agg(
                pl.len().alias("trip_count"),
                pl.sum("fare_amount").alias("total_revenue"),
                pl.mean("fare_amount").alias("avg_fare"),
                pl.mean("trip_distance").alias("avg_distance"),
                pl.mean("tip_amount").alias("avg_tip"),
            ).sort("trip_distance").sink_parquet(out_path, engine=polars_engine, compression="snappy", mkdir=True)
        else:
            df.group_by(["trip_distance", "DO_Zone", "DO_Borough", "PU_Borough"]).agg(
                pl.len().alias("trip_count"),
                pl.sum("fare_amount").alias("total_revenue"),
                pl.mean("fare_amount").alias("avg_fare"),
                pl.mean("trip_distance").alias("avg_distance"),
                pl.mean("tip_amount").alias("avg_tip"),
            ).sort(["trip_distance", "DO_Zone", "DO_Borough", "PU_Borough"]).sink_parquet(
                out_path, engine=polars_engine, compression="snappy", mkdir=True
            )
        duration = perf_counter() - start_time
    except Exception as e:
        logger.exception("Polars %s %s %s %s failed", cpu_gpu, engine, dataset_type, execution_query)
        error = f"{type(e).__name__}: {e}"
    save_execution_time(
        "Polars",
        duration,
        cpu_gpu,
        engine,
        dataset_type,
        execution_query,
        version=pl.__version__,
        backend_version=backend_version,
        error=error,
    )
    return error is None


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--file_path", type=str)
    parser.add_argument("--file_type", type=str, default="csv")
    parser.add_argument("--mode", type=str, default="eager")

    parser.add_argument(
        "--engine",
        choices=["in-memory", "streaming"],
        default="in-memory",
        help="Execution engine for lazy queries; eager mode requires in-memory.",
    )
    parser.add_argument("--gpu_engine", type=str, default="False")
    parser.add_argument("--dataset_type", type=str, default="ecommerce")
    parser.add_argument("--execution_query", type=str, default="simple")
    add_benchmark_arguments(parser)

    args = parser.parse_args()
    if args.dataset_type == "ecommerce":
        if not args.file_path or not args.file_path.strip():
            parser.error("--file_path is required for ecommerce")
        execute = lambda: ecommerce_execution(args.file_type, args.file_path, args.mode, args.engine)
        input_paths = (args.file_path,)
    else:
        execute = lambda: nyc_taxi_execution(
            args.dataset_type, args.engine, args.execution_query, args.gpu_engine == "True"
        )
        dataset = "yellow" if args.dataset_type == "nyc-yellow" else "green"
        input_paths = (f"data/nyc-taxi/{dataset}.parquet", "data/nyc-taxi/taxi_zone_lookup.csv")
    success = run_benchmark(
        execute,
        warmups=args.warmups,
        repetitions=args.repetitions,
        process_started=PROCESS_STARTED,
        input_paths=input_paths,
        output_path="data/out/polars.parquet",
    )
    sys.exit(0 if success else 1)
