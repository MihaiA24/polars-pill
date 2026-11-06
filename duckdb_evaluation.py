import argparse
import logging
import sys
from pathlib import Path
from time import perf_counter
from typing import Literal

from utils import PROCESS_STARTED, add_benchmark_arguments, run_benchmark, save_execution_time

# isort: split

import duckdb

logger = logging.getLogger(__name__)
OUTPUT_PATH = "data/out/duckdb.parquet"

# Match the fixed ecommerce CSV schema without importing the Polars/Spark schemas.
ECOMMERCE_CSV_SOURCE = """
    read_csv($1, header = true, columns = {
        'event_time': 'VARCHAR',
        'event_type': 'VARCHAR',
        'product_id': 'INTEGER',
        'category_id': 'BIGINT',
        'category_code': 'VARCHAR',
        'brand': 'VARCHAR',
        'price': 'FLOAT',
        'user_id': 'INTEGER',
        'user_session': 'VARCHAR'
    })
"""


def ecommerce_execution(
    connection: duckdb.DuckDBPyConnection, file_type: Literal["csv", "parquet"], file_path: str
) -> bool:
    duration = error = None
    try:
        start_time = perf_counter()
        source = "read_parquet($1)" if file_type == "parquet" else ECOMMERCE_CSV_SOURCE
        # The unused timestamp expression may be pruned, just as in the other lazy engines.
        query = f"""
            COPY (
                WITH events AS (
                    SELECT product_id, price,
                        strptime(event_time, '%Y-%m-%d %H:%M:%S %Z') AS event_time
                    FROM {source}
                )
                SELECT product_id, median(price) AS sum_price
                FROM events
                GROUP BY product_id
                HAVING sum_price > 500
            ) TO $2 (FORMAT PARQUET, COMPRESSION SNAPPY)
        """
        Path(OUTPUT_PATH).parent.mkdir(parents=True, exist_ok=True)
        # Single-file COPY overwrites its destination on each benchmark attempt.
        connection.execute(query, [file_path, OUTPUT_PATH])
        duration = perf_counter() - start_time
    except Exception as e:
        logger.exception("DuckDB ecommerce benchmark failed")
        error = f"{type(e).__name__}: {e}"
    save_execution_time(
        "DuckDB",
        duration,
        "CPU",
        "native",
        file_path,
        "simple",
        version=duckdb.__version__,
        error=error,
        input_format="parquet" if file_type == "parquet" else "csv",
    )
    return error is None


def nyc_taxi_execution(
    connection: duckdb.DuckDBPyConnection,
    dataset_type: Literal["nyc-green", "nyc-yellow"],
    execution_query: Literal["simple", "complex", "filtered", "date-window"] = "simple",
) -> bool:
    duration = error = None
    try:
        start_time = perf_counter()
        dataset = "yellow" if dataset_type == "nyc-yellow" else "green"
        parameters = [f"data/nyc-taxi/{dataset}.parquet"]
        if execution_query in ("filtered", "date-window"):
            grouping_keys = ["PULocationID"]
            source = """
                SELECT PULocationID, trip_distance, fare_amount, tip_amount
                FROM read_parquet($1)
                WHERE trip_distance > 0 AND fare_amount > 0
            """
            if execution_query == "date-window":
                source += """
                    AND tpep_pickup_datetime >= TIMESTAMP '2019-10-01 00:00:00'
                    AND tpep_pickup_datetime < TIMESTAMP '2019-10-02 00:00:00'
                """
        else:
            grouping_keys = ["trip_distance"]
            if execution_query == "complex":
                grouping_keys += ["DO_Zone", "DO_Borough", "PU_Borough"]
            parameters.append("data/nyc-taxi/taxi_zone_lookup.csv")
            source = """
                WITH zones AS (
                    SELECT * FROM read_csv($2, header = true, columns = {
                        'LocationID': 'INTEGER',
                        'Borough': 'VARCHAR',
                        'Zone': 'VARCHAR',
                        'service_zone': 'VARCHAR'
                    })
                )
                SELECT trips.trip_distance, trips.fare_amount, trips.tip_amount,
                    dropoff.Zone AS DO_Zone, dropoff.Borough AS DO_Borough,
                    pickup.Borough AS PU_Borough
                FROM read_parquet($1) AS trips
                INNER JOIN zones AS pickup ON trips.PULocationID = pickup.LocationID
                INNER JOIN zones AS dropoff ON trips.DOLocationID = dropoff.LocationID
            """
        grouping = ", ".join(grouping_keys)
        ordering = ", ".join(f"{key} ASC NULLS FIRST" for key in grouping_keys)
        query = f"""
            COPY (
                WITH joined AS ({source})
                SELECT {grouping},
                    count(*) AS trip_count,
                    sum(fare_amount) AS total_revenue,
                    avg(fare_amount) AS avg_fare,
                    avg(trip_distance) AS avg_distance,
                    avg(tip_amount) AS avg_tip
                FROM joined
                GROUP BY {grouping}
                ORDER BY {ordering}
            ) TO ${len(parameters) + 1} (FORMAT PARQUET, COMPRESSION SNAPPY)
        """
        Path(OUTPUT_PATH).parent.mkdir(parents=True, exist_ok=True)
        connection.execute(query, [*parameters, OUTPUT_PATH])
        duration = perf_counter() - start_time
    except Exception as e:
        logger.exception("DuckDB %s %s benchmark failed", dataset_type, execution_query)
        error = f"{type(e).__name__}: {e}"
    save_execution_time(
        "DuckDB",
        duration,
        "CPU",
        "native",
        dataset_type,
        execution_query,
        version=duckdb.__version__,
        error=error,
        input_format="parquet",
    )
    return error is None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file_path", type=str)
    parser.add_argument("--file_type", choices=["csv", "parquet"], default="csv")
    parser.add_argument("--dataset_type", choices=["ecommerce", "nyc-green", "nyc-yellow"], default="ecommerce")
    parser.add_argument(
        "--execution_query",
        choices=["simple", "complex", "filtered", "date-window"],
        default="simple",
        help="NYC query variant; ecommerce always runs the simple median workload.",
    )
    add_benchmark_arguments(parser)
    args = parser.parse_args()
    if args.dataset_type == "ecommerce" and (not args.file_path or not args.file_path.strip()):
        parser.error("--file_path is required for ecommerce")

    with duckdb.connect() as connection:
        if args.dataset_type == "ecommerce":
            execute = lambda: ecommerce_execution(connection, args.file_type, args.file_path)
            input_paths = (args.file_path,)
        else:
            execute = lambda: nyc_taxi_execution(connection, args.dataset_type, args.execution_query)
            dataset = "yellow" if args.dataset_type == "nyc-yellow" else "green"
            input_paths = (f"data/nyc-taxi/{dataset}.parquet",)
            if args.execution_query not in ("filtered", "date-window"):
                input_paths += ("data/nyc-taxi/taxi_zone_lookup.csv",)

        def duckdb_resources():
            threads, memory_limit, temp_directory = connection.execute(
                "SELECT current_setting('threads'), current_setting('memory_limit'), current_setting('temp_directory')"
            ).fetchone()
            return {
                "duckdb_threads": threads,
                "duckdb_memory_limit": memory_limit,
                "duckdb_temp_directory": temp_directory,
            }

        success = run_benchmark(
            execute,
            warmups=args.warmups,
            repetitions=args.repetitions,
            process_started=PROCESS_STARTED,
            input_paths=input_paths,
            output_path=OUTPUT_PATH,
            resources=duckdb_resources,
            profile_memory=args.profile_memory,
        )
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
