import polars as pl
# DATASET: https://www.kaggle.com/datasets/mkechinov/ecommerce-behavior-data-from-multi-category-store
# PREPROCESS FOR TALK

pl.scan_csv("data/2019-Nov.csv").with_columns(
    pl.col("event_time").str.to_datetime(format="%Y-%m-%d %H:%M:%S %Z", time_zone="UTC")
).sink_parquet("data/2019-Nov.parquet")

pl.scan_csv("data/2019-Oct.csv").with_columns(
    pl.col("event_time").str.to_datetime(format="%Y-%m-%d %H:%M:%S %Z", time_zone="UTC")
).sink_parquet("data/2019-Oct.parquet")

# pl.scan_parquet("data/*.parquet").sink_parquet("data/2019.parquet")

pl.scan_csv("data/2019-Oct.csv").with_columns(
    pl.col("event_time").str.to_datetime(format="%Y-%m-%d %H:%M:%S %Z", time_zone="UTC")
).limit(10_000_000).sink_parquet("data/2019-Oct-10M.parquet")

pl.scan_csv("data/2019-Oct.csv").limit(20_000_000).sink_csv("data/2019-Oct-20M.csv")  # For Pandas run
