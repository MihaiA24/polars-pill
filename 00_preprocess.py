import polars as pl
from schemas import pl_schema
# DATASET: https://www.kaggle.com/datasets/mkechinov/ecommerce-behavior-data-from-multi-category-store
# PREPROCESS FOR TALK

pl.scan_csv("data/2019-Nov.csv", schema=pl_schema).sink_parquet("data/2019-Nov.parquet")

pl.scan_csv("data/2019-Oct.csv", schema=pl_schema).sink_parquet("data/2019-Oct.parquet")

# pl.scan_parquet("data/*.parquet").sink_parquet("data/2019.parquet")

pl.scan_csv("data/2019-Oct.csv", schema=pl_schema).limit(10_000_000).sink_parquet("data/2019-Oct-10M.parquet")

pl.scan_csv("data/2019-Oct.csv", schema=pl_schema).limit(20_000_000).sink_csv("data/2019-Oct-20M.csv")  # For Pandas run
