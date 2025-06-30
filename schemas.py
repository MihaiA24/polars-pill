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
