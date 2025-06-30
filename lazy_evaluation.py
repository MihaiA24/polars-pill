import polars as pl


from schemas import pl_schema

df = pl.scan_csv("data/2019-Nov.csv", schema=pl_schema)
# df = pl.scan_parquet("data/2019-Oct.parquet")


df.with_columns(
    pl.col("event_time").str.to_datetime(format="%Y-%m-%d %H:%M:%S %Z"),
    pl.col("price").sum().over("brand").alias("median_price_over_brand"),
).sink_parquet("data/2019-Oct_polars.parquet", engine="streaming", compression="snappy")
