from typing import Literal

import polars as pl
from pyspark.sql.types import StructType, StringType, StructField, IntegerType, LongType, DoubleType

# NOTE: Intentionally read event_time as String to convert to Timestamp
pd_schema = {
    "event_time": "str",
    "event_type": "str",
    "product_id": "int32",
    "category_id": "int64",
    "category_code": "str",
    "brand": "str",
    "price": "float64",
    "user_id": "int32",
    "user_session": "str",
}

pl_schema = {
    "event_time": pl.String(),
    "event_type": pl.String(),
    "product_id": pl.Int32(),
    "category_id": pl.Int64(),
    "category_code": pl.String(),
    "brand": pl.String(),
    "price": pl.Float32(),
    "user_id": pl.Int32(),
    "user_session": pl.String(),
}

spark_schema = StructType(
    [
        StructField("event_time", StringType(), nullable=False),
        StructField("event_type", StringType(), nullable=False),
        StructField("product_id", IntegerType(), nullable=False),
        StructField("category_id", LongType(), nullable=False),
        StructField("category_code", StringType(), nullable=False),
        StructField("brand", StringType(), nullable=True),
        StructField("price", DoubleType(), nullable=False),
        StructField("user_id", IntegerType(), nullable=False),
        StructField("user_session", StringType(), nullable=False),
    ]
)

green_default_schema = {
    "VendorID": pl.Int32,
    "lpep_pickup_datetime": pl.Datetime(time_unit="ms", time_zone=None),
    "lpep_dropoff_datetime": pl.Datetime(time_unit="ms", time_zone=None),
    "store_and_fwd_flag": pl.String,
    "RatecodeID": pl.Int64,
    "PULocationID": pl.Int32,
    "DOLocationID": pl.Int32,
    "passenger_count": pl.Int64,
    "trip_distance": pl.Float64,
    "fare_amount": pl.Float64,
    "extra": pl.Float64,
    "mta_tax": pl.Float64,
    "tip_amount": pl.Float64,
    "tolls_amount": pl.Float64,
    "ehail_fee": pl.Float64,
    "improvement_surcharge": pl.Float64,
    "total_amount": pl.Float64,
    "payment_type": pl.Int64,
    "trip_type": pl.Float64,
    "congestion_surcharge": pl.Float64,
}
yellow_default_schema = {
    "VendorID": pl.Int32,
    "tpep_pickup_datetime": pl.Datetime(time_unit="ms", time_zone=None),
    "tpep_dropoff_datetime": pl.Datetime(time_unit="ms", time_zone=None),
    "passenger_count": pl.Int64,
    "trip_distance": pl.Float64,
    "RatecodeID": pl.Int32,
    "store_and_fwd_flag": pl.String,
    "PULocationID": pl.Int32,
    "DOLocationID": pl.Int32,
    "payment_type": pl.Int32,
    "fare_amount": pl.Float64,
    "extra": pl.Float64,
    "mta_tax": pl.Float64,
    "tip_amount": pl.Float64,
    "tolls_amount": pl.Float64,
    "improvement_surcharge": pl.Float64,
    "total_amount": pl.Float64,
    "congestion_surcharge": pl.Float64,
    "airport_fee": pl.Float64,
}


def generate_polars_cast(parquet_schema: dict, type: Literal["green", "yellow"]) -> list[pl.Expr]:
    if type == "green":
        default_schema = green_default_schema
    else:
        default_schema = yellow_default_schema

    distinct_fields = {}
    for key, value in parquet_schema.items():
        if key == "Airport_fee":
            key = "airport_fee"
        if value != default_schema[key]:
            distinct_fields[key] = default_schema[key]


    parse_list = []
    for key, value in distinct_fields.items():
        parse_list.append(pl.col(key).cast(value))
    return parse_list
