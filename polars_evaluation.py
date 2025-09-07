import argparse
import os
from datetime import datetime
from typing import Literal

import polars as pl

from schemas import pl_schema, zone_schema
from utils import save_execution_time


def ecommerce_execution(file_type: str, file_path: str, mode: Literal["eager", "lazy"]) -> None:
    start_time = datetime.now()

    if file_type == "parquet":
        df = pl.read_parquet(file_path) if mode == "eager" else pl.scan_parquet(file_path)
    else:
        df = pl.read_csv(file_path, schema=pl_schema) if mode == "eager" else pl.scan_csv(file_path, schema=pl_schema)

    df = (
        df.with_columns(pl.col("event_time").str.to_datetime(format="%Y-%m-%d %H:%M:%S %Z"))
        .group_by("product_id")
        .agg(pl.col("price").median().alias("sum_price"))
        .filter((pl.col("sum_price") > 500))
    )
    if mode == "eager":
        df.write_parquet("data/out/polars.parquet", compression="snappy")  # Just overwrite the file to save space
    else:
        df.sink_parquet(
            "data/out/polars.parquet", engine="streaming", compression="snappy"
        )  # Just overwrite the file to save space. Snappy compression to match spark default
    duration = (datetime.now() - start_time).total_seconds()
    save_execution_time(f"Polars {mode}", duration, "CPU", "streaming", file_path, "Simple")


def nyc_taxi_execution(
    dataset_type: Literal["nyc-green", "nyc-yellow"],
    engine: Literal["in-memory", "streaming"] = "streaming",
    execution_query: Literal["simple", "complex"] = "simple",
    gpu_engine: bool = False,
) -> None:
    try:
        start_time = datetime.now()
        if engine == "in-memory" and gpu_engine:
            os.environ["POLARS_GPU_ENABLE_CUDA_MANAGED_MEMORY"] = (
                "0"  # Forcing in-memory engine to not use UVM for the benchmark
            )

        polars_engine = pl.GPUEngine(executor=engine, raise_on_fail=True) if gpu_engine else engine
        dataset = "yellow" if dataset_type == "nyc-yellow" else "green"
        cpu_gpu = "GPU" if gpu_engine else "CPU"
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
            ).sort("trip_distance").sink_parquet(
                "data/out/polars.parquet", engine=polars_engine
            )  # Snappy compression to match spark default
        else:
            df.group_by(["trip_distance", "DO_Zone", "DO_Borough", "PU_Borough"]).agg(
                pl.len().alias("trip_count"),
                pl.sum("fare_amount").alias("total_revenue"),
                pl.mean("fare_amount").alias("avg_fare"),
                pl.mean("trip_distance").alias("avg_distance"),
                pl.mean("tip_amount").alias("avg_tip"),
            ).sort(["trip_distance", "DO_Zone", "DO_Borough", "PU_Borough"]).sink_parquet(
                "data/out/polars.parquet", engine=polars_engine
            )  # Snappy compression to match spark default
        end_time = datetime.now()
        duration = (datetime.now() - start_time).total_seconds()
    except Exception as e:
        duration = "Error (memory)"
    save_execution_time("Polars", duration, cpu_gpu, engine, dataset_type, execution_query)
    # update_benchmark_section_in_file("Polars", cpu_gpus, engine, dataset_type, start_time, end_time)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    # For ecommerce dataset
    parser.add_argument("--file_path", type=str)
    parser.add_argument("--file_type", type=str, default="csv")
    parser.add_argument("--mode", type=str, default="eager")  # Eager or Lazy execution

    parser.add_argument("--engine", type=str, default="in-memory")
    parser.add_argument("--gpu_engine", type=str, default="False")
    parser.add_argument("--dataset_type", type=str, default="ecommerce")  # ecommerce, nyc-green, nyc-yellow
    parser.add_argument("--execution_query", type=str, default="simple")

    args = parser.parse_args()
    if args.dataset_type == "ecommerce":
        ecommerce_execution(args.file_type, args.file_path, args.mode)
    else:
        nyc_taxi_execution(args.dataset_type, args.engine, args.execution_query, args.gpu_engine == "True")
