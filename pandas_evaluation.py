import pandas as pd
from schemas import pd_schema

# Read the CSV with the schema
df = pd.read_csv("data/2019-Oct-20M.csv", engine="pyarrow", dtype=pd_schema)
df["event_time"] = pd.to_datetime(df["event_time"])
df["median_price_over_brand"] = df.groupby("brand")["price"].transform("median")
df.to_parquet("data/2019-Oct_pandas.parquet")
