import argparse

import polars as pl

zone_schema = {"LocationID": pl.Int32, "Borough": pl.String, "Zone": pl.String, "service_zone": pl.String}


engine = "streaming"
parser = argparse.ArgumentParser()
parser.add_argument("--file_path", type=str)

args = parser.parse_args()

df_zones = pl.scan_csv("data/nyc-taxi/taxi_zone_lookup.csv", schema=zone_schema)

# Taxi operation efficiency
df = (
    pl.scan_parquet(args.file_path)
    .with_columns(
        ((pl.col("tpep_dropoff_datetime") - pl.col("tpep_pickup_datetime")).dt.total_minutes(fractional=True)).alias(
            "trip_duration_minutes"
        )
    )
    .filter((pl.col("trip_duration_minutes") > 0) & (pl.col("trip_distance") > 0) & (pl.col("fare_amount") > 0))
    .with_columns(
        [
            (pl.col("fare_amount") / pl.col("trip_duration_minutes")).alias("revenue_per_minute"),
            (pl.col("fare_amount") / pl.col("trip_distance")).alias("revenue_per_mile"),
            (pl.col("total_amount") / pl.col("trip_duration_minutes")).alias("total_revenue_per_minute"),
            (pl.col("trip_distance") / (pl.col("trip_duration_minutes") / 60)).alias("speed_mph"),
            (pl.col("fare_amount") * pl.col("trip_distance") / pl.col("trip_duration_minutes")).alias(
                "efficiency_score"
            ),
        ]
    )
)

# Every sink below is deferred (lazy=True) and executed together at the bottom, so the source
# parquet is scanned once for all six outputs instead of once per sink.
sinks = [df.sink_parquet("data/nyc-taxi/out/efficiency.parquet", mkdir=True, lazy=True)]


# Efficiency by hour of the day
sinks.append(
    df.with_columns(pl.col("tpep_pickup_datetime").dt.hour().alias("hour"))
    .group_by("hour")
    .agg(
        pl.mean("revenue_per_minute").alias("avg_revenue_per_minute"),
        pl.mean("speed_mph").alias("avg_speed_mph"),
        pl.mean("efficiency_score").alias("avg_efficiency_score"),
        pl.len().alias("trip_count"),
    )
    .sort("avg_revenue_per_minute", descending=True)
    .sink_csv("data/nyc-taxi/out/efficiency_by_hour.csv", mkdir=True, lazy=True)
)


# Join DF with zones
df = (
    df.join(df_zones, left_on="PULocationID", right_on="LocationID")
    .rename({"Borough": "PU_Borough", "Zone": "PU_Zone", "service_zone": "PU_service_zone"})
    .join(df_zones, left_on="DOLocationID", right_on="LocationID")
    .rename({"Borough": "DO_Borough", "Zone": "DO_Zone", "service_zone": "DO_service_zone"})
)


## Find most effective routes
sinks.append(
    df.group_by(["PU_Zone", "DO_Zone"])
    .agg(
        pl.mean("revenue_per_minute").alias("avg_revenue_per_minute"),
        pl.mean("speed_mph").alias("avg_speed_mph"),
        pl.len().alias("trip_count"),
    )
    .sort("avg_revenue_per_minute", descending=True)
    .sink_csv("data/nyc-taxi/out/efficiency_by_route.csv", mkdir=True, lazy=True)
)


## Borough pick up
sinks.append(
    df.group_by("PU_Borough")
    .agg(
        pl.len().alias("trip_count"),
        pl.sum("fare_amount").alias("total_revenue"),
        pl.mean("fare_amount").alias("avg_fare"),
        pl.mean("trip_distance").alias("avg_distance"),
        pl.mean("tip_amount").alias("avg_tip"),
    )
    .with_columns((pl.col("trip_count") / pl.col("trip_count").sum() * 100).alias("percentage_of_trips"))
    .sort("trip_count", descending=True)
    .sink_csv("data/nyc-taxi/out/efficiency_by_borough.csv", mkdir=True, lazy=True)
)

## Borough dropoff
sinks.append(
    df.group_by("DO_Borough")
    .agg(
        pl.len().alias("trip_count"),
        pl.sum("fare_amount").alias("total_revenue"),
        pl.mean("fare_amount").alias("avg_fare"),
        pl.mean("trip_distance").alias("avg_distance"),
        pl.mean("tip_amount").alias("avg_tip"),
    )
    .sort("trip_count", descending=True)
    .sink_csv("data/nyc-taxi/out/efficiency_by_borough_dropoff.csv", mkdir=True, lazy=True)
)

sinks.append(
    df.group_by("PU_Borough")
    .agg(
        pl.mean("trip_duration_minutes").alias("avg_duration_minutes"),
        pl.mean("revenue_per_minute").alias("avg_revenue_per_minute"),
        pl.mean("speed_mph").alias("avg_speed_mph"),
        pl.len().alias("trip_count"),
    )
    .sort("avg_revenue_per_minute", descending=True)
    .sink_csv("data/nyc-taxi/out/efficiency_by_borough_duration.csv", mkdir=True, lazy=True)
)

pl.collect_all(sinks, engine=engine)
