import polars as pl
from pyspark.sql.types import FloatType, IntegerType, LongType, StringType, StructField, StructType

# NOTE: Intentionally read event_time as String to convert to Timestamp
pd_schema = {
    "event_time": "str",
    "event_type": "str",
    "product_id": "int32",
    "category_id": "int64",
    "category_code": "str",
    "brand": "str",
    "price": "float32",
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

zone_schema = {"LocationID": pl.Int32, "Borough": pl.String, "Zone": pl.String, "service_zone": pl.String}

spark_schema = StructType(
    [
        StructField("event_time", StringType(), nullable=False),
        StructField("event_type", StringType(), nullable=False),
        StructField("product_id", IntegerType(), nullable=False),
        StructField("category_id", LongType(), nullable=False),
        StructField("category_code", StringType(), nullable=False),
        StructField("brand", StringType(), nullable=True),
        StructField("price", FloatType(), nullable=False),
        StructField("user_id", IntegerType(), nullable=False),
        StructField("user_session", StringType(), nullable=False),
    ]
)

default_schema = {
    "VendorID": pl.Int16,
    "tpep_pickup_datetime": pl.Datetime(time_unit="ms", time_zone=None),
    "tpep_dropoff_datetime": pl.Datetime(time_unit="ms", time_zone=None),
    "passenger_count": pl.UInt16,
    "trip_distance": pl.Float32,
    "RatecodeID": pl.UInt8,
    "store_and_fwd_flag": pl.String,
    "PULocationID": pl.UInt16,
    "DOLocationID": pl.UInt16,
    "payment_type": pl.UInt8,
    "fare_amount": pl.Float32,
    "extra": pl.Float32,
    "mta_tax": pl.Float32,
    "tip_amount": pl.Float32,
    "tolls_amount": pl.Float32,
    "improvement_surcharge": pl.Float32,
    "total_amount": pl.Float32,
    "congestion_surcharge": pl.Float32,
    "airport_fee": pl.Float32,
}


def generate_polars_cast(parquet_schema: dict) -> list[pl.Expr]:
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
