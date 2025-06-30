import polars as pl
from schemas import pl_schema


# Data load on memory
df = pl.read_csv("data/2019-Oct-20M.csv", schema=pl_schema)
# df = pl.read_csv("data/2019-Oct.csv", schema=pl_schema)
# df = pl.read_parquet("data/2019-Oct.parquet")

# Operations done
df = df.with_columns(
    pl.col("event_time").str.to_datetime(format="%Y-%m-%d %H:%M:%S %Z"),
    pl.col("price").median().over("brand").alias("median_price_over_brand"),
)


# print(df.count())
# print(df.estimated_size("mb"))

df.write_parquet("data/2019-Oct_polars.parquet", compression="snappy")
