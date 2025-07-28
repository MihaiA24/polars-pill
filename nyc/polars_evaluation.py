import argparse

import polars as pl
import rmm

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
        ((pl.col("tpep_dropoff_datetime") - pl.col("tpep_pickup_datetime")).dt.total_minutes()).alias(
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

df.sink_parquet("data/nyc-taxi/out/efficiency.parquet", engine=engine)  # Large data transformation


# Efficiency by hour of the day
df.with_columns(pl.col("tpep_pickup_datetime").dt.hour().alias("hour")).group_by("hour").agg(
    pl.mean("revenue_per_minute").alias("avg_revenue_per_minute"),
    pl.mean("speed_mph").alias("avg_speed_mph"),
    pl.mean("efficiency_score").alias("avg_efficiency_score"),
    pl.len().alias("trip_count"),
).sort("avg_revenue_per_minute", descending=True).sink_csv("data/nyc-taxi/out/efficiency_by_hour.csv", engine=engine)


# Join DF with zones
df = (
    df.join(df_zones, left_on="PULocationID", right_on="LocationID")
    .rename({"Borough": "PU_Borough", "Zone": "PU_Zone", "service_zone": "PU_service_zone"})
    .join(df_zones, left_on="DOLocationID", right_on="LocationID")
    .rename({"Borough": "DO_Borough", "Zone": "DO_Zone", "service_zone": "DO_service_zone"})
)


## Find most effective routes
df.group_by(["PU_Zone", "DO_Zone"]).agg(
    pl.mean("revenue_per_minute").alias("avg_revenue_per_minute"),
    pl.mean("speed_mph").alias("avg_speed_mph"),
    pl.len().alias("trip_count"),
).sort("avg_revenue_per_minute", descending=True).sink_csv("data/nyc-taxi/out/efficiency_by_route.csv", engine=engine)


## Borough pick up
df.group_by("PU_Borough").agg(
    pl.len().alias("trip_count"),
    pl.sum("fare_amount").alias("total_revenue"),
    pl.mean("fare_amount").alias("avg_fare"),
    pl.mean("trip_distance").alias("avg_distance"),
    pl.mean("tip_amount").alias("avg_tip"),
).with_columns((pl.col("trip_count") / 8 * 100).alias("percentage_of_trips")).sort(
    "trip_count", descending=True
).sink_csv("data/nyc-taxi/out/efficiency_by_borough.csv", engine=engine)

## Borough dropoff
df.group_by("DO_Borough").agg(
    pl.len().alias("trip_count"),
    pl.sum("fare_amount").alias("total_revenue"),
    pl.mean("fare_amount").alias("avg_fare"),
    pl.mean("trip_distance").alias("avg_distance"),
    pl.mean("tip_amount").alias("avg_tip"),
).sort("trip_count", descending=True).sink_csv("data/nyc-taxi/out/efficiency_by_borough_dropoff.csv", engine=engine)

df.group_by("PU_Borough").agg(
    pl.mean("trip_duration_minutes").alias("avg_duration_minutes"),
    pl.mean("revenue_per_minute").alias("avg_revenue_per_minute"),
    pl.mean("speed_mph").alias("avg_speed_mph"),
    pl.len().alias("trip_count"),
).sort("avg_revenue_per_minute", descending=True).sink_csv(
    "data/nyc-taxi/out/efficiency_by_borough_duration.csv", engine=engine
)
