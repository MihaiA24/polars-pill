import argparse

from pyspark.sql import SparkSession
from pyspark.sql.functions import broadcast, col, count, desc, hour, lit, mean, unix_timestamp
from pyspark.sql.functions import sum as spark_sum
from pyspark.sql.types import IntegerType, StringType, StructField, StructType

parser = argparse.ArgumentParser()
parser.add_argument("--file_path", type=str)

args = parser.parse_args()

# Initialize Spark session
spark = (
    SparkSession.builder.appName("NYC Taxi Analysis")
    .config("spark.executor.memory", "50g")
    .config("spark.driver.memory", "50g")
    .master("local[*]")
    .config("spark.sql.adaptive.enabled", "true")
    .getOrCreate()
)

# Define schema for zones
zone_schema = StructType(
    [
        StructField("LocationID", IntegerType(), True),
        StructField("Borough", StringType(), True),
        StructField("Zone", StringType(), True),
        StructField("service_zone", StringType(), True),
    ]
)

# Load and broadcast df_zones
df_zones = spark.read.csv("data/nyc-taxi/taxi_zone_lookup.csv", header=True, schema=zone_schema)
df_zones_broadcast = broadcast(df_zones)

# Load main taxi data
df = spark.read.parquet(args.file_path)

# Taxi operation efficiency
df = (
    df.withColumn(
        "trip_duration_minutes", (unix_timestamp("tpep_dropoff_datetime") - unix_timestamp("tpep_pickup_datetime")) / 60
    )
    .filter((col("trip_duration_minutes") > 0) & (col("trip_distance") > 0) & (col("fare_amount") > 0))
    .withColumn("revenue_per_minute", col("fare_amount") / col("trip_duration_minutes"))
    .withColumn("revenue_per_mile", col("fare_amount") / col("trip_distance"))
    .withColumn("total_revenue_per_minute", col("total_amount") / col("trip_duration_minutes"))
    .withColumn("speed_mph", col("trip_distance") / (col("trip_duration_minutes") / 60))
    .withColumn("efficiency_score", col("fare_amount") * col("trip_distance") / col("trip_duration_minutes"))
).cache()

# Write efficiency data
df.write.mode("overwrite").parquet("data/nyc-taxi/out/efficiency.parquet")


# Efficiency by hour of the day
efficiency_by_hour = (
    df.withColumn("hour", hour("tpep_pickup_datetime"))
    .groupBy("hour")
    .agg(
        mean("revenue_per_minute").alias("avg_revenue_per_minute"),
        mean("speed_mph").alias("avg_speed_mph"),
        mean("efficiency_score").alias("avg_efficiency_score"),
        count("*").alias("trip_count"),
    )
    .orderBy(desc("avg_revenue_per_minute"))
)

efficiency_by_hour.write.mode("overwrite").option("header", "true").csv("data/nyc-taxi/out/efficiency_by_hour.csv")

# Join with zones using broadcast join
df_with_zones = (
    df.join(df_zones_broadcast, col("PULocationID") == col("LocationID"), "left")
    .withColumnRenamed("Borough", "PU_Borough")
    .withColumnRenamed("Zone", "PU_Zone")
    .withColumnRenamed("service_zone", "PU_service_zone")
    .drop("LocationID")
    .join(df_zones_broadcast, col("DOLocationID") == col("LocationID"), "left")
    .withColumnRenamed("Borough", "DO_Borough")
    .withColumnRenamed("Zone", "DO_Zone")
    .withColumnRenamed("service_zone", "DO_service_zone")
    .drop("LocationID")
)

# Find most effective routes
df_with_zones.groupBy("PU_Zone", "DO_Zone").agg(
    mean("revenue_per_minute").alias("avg_revenue_per_minute"),
    mean("speed_mph").alias("avg_speed_mph"),
    count("*").alias("trip_count"),
).orderBy(desc("avg_revenue_per_minute")).write.mode("overwrite").option("header", "true").csv(
    "data/nyc-taxi/out/efficiency_by_route.csv"
)

# Borough pickup analysis
df_with_zones.groupBy("PU_Borough").agg(
    count("*").alias("trip_count"),
    spark_sum("fare_amount").alias("total_revenue"),
    mean("fare_amount").alias("avg_fare"),
    mean("trip_distance").alias("avg_distance"),
    mean("tip_amount").alias("avg_tip"),
).withColumn("percentage_of_trips", col("trip_count") / lit(8) * 100).orderBy(desc("trip_count")).write.mode(
    "overwrite"
).option("header", "true").csv("data/nyc-taxi/out/efficiency_by_borough.csv")

# Borough dropoff analysis

df_with_zones.groupBy("DO_Borough").agg(
    count("*").alias("trip_count"),
    spark_sum("fare_amount").alias("total_revenue"),
    mean("fare_amount").alias("avg_fare"),
    mean("trip_distance").alias("avg_distance"),
    mean("tip_amount").alias("avg_tip"),
).orderBy(desc("trip_count")).write.mode("overwrite").option("header", "true").csv(
    "data/nyc-taxi/out/efficiency_by_borough_dropoff.csv"
)

# Borough efficiency with duration
df_with_zones.groupBy("PU_Borough").agg(
    mean("trip_duration_minutes").alias("avg_duration_minutes"),
    mean("revenue_per_minute").alias("avg_revenue_per_minute"),
    mean("speed_mph").alias("avg_speed_mph"),
    count("*").alias("trip_count"),
).orderBy(desc("avg_revenue_per_minute")).write.mode("overwrite").option("header", "true").csv(
    "data/nyc-taxi/out/efficiency_by_borough_duration.csv"
)

spark.stop()
