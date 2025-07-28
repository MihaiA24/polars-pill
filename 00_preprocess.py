import polars as pl
import polars.selectors as cs
from schemas import pl_schema, generate_polars_cast
import glob
# pl.Config.set_engine_affinity("streaming")
# PREPROCESS FOR TALK


# Some parquets dont follow the same path, cast all with same schema
parquet_list = glob.glob("data/nyc-taxi/green/*/*.parquet")
for file in parquet_list:
    schema = pl.read_parquet_schema(file)
    schema["tpep_pickup_datetime"] = schema.pop("lpep_pickup_datetime")
    schema["tpep_dropoff_datetime"] = schema.pop("lpep_dropoff_datetime")
    schema["airport_fee"] = schema.pop("ehail_fee")
    schema.pop("trip_type")
    cast_schema = generate_polars_cast(schema)
    if cast_schema:
        print("Formating... ", file)
        pl.read_parquet(file).drop("trip_type").rename(
            {
                "lpep_pickup_datetime": "tpep_pickup_datetime",
                "lpep_dropoff_datetime": "tpep_dropoff_datetime",
                "ehail_fee": "airport_fee",
            }
        ).with_columns(*cast_schema).write_parquet(file)
    else:
        print("Skipping... ", file)

print("Merging green parquets...")
pl.scan_parquet("data/nyc-taxi/green/*/*.parquet").sink_parquet("data/nyc-taxi/green.parquet")

parquet_list = glob.glob("data/nyc-taxi/yellow/*/*.parquet")
for file in parquet_list:
    schema = pl.read_parquet_schema(file)
    cast_schema = generate_polars_cast(schema)
    if cast_schema:
        print("Formating... ", file)
        df = pl.read_parquet(file)
        # Different name in multiple cols
        df = df.rename({"Airport_fee": "airport_fee"}) if "Airport_fee" in df.columns else df
        df.with_columns(*cast_schema).write_parquet(file)
    else:
        print("Skipping... ", file)
print("Merging yellow parquets...")
pl.scan_parquet("data/nyc-taxi/yellow/*/*.parquet").sink_parquet("data/nyc-taxi/yellow.parquet")


pl.scan_csv("data/2019-Nov.csv", schema=pl_schema).sink_parquet("data/2019-Nov.parquet")

pl.scan_csv("data/2019-Oct.csv", schema=pl_schema).sink_parquet("data/2019-Oct.parquet")

# pl.scan_parquet("data/*.parquet").sink_parquet("data/2019.parquet")

pl.scan_csv("data/2019-Oct.csv", schema=pl_schema).limit(10_000_000).sink_parquet("data/2019-Oct-10M.parquet")

pl.scan_csv("data/2019-Oct.csv", schema=pl_schema).limit(20_000_000).sink_csv("data/2019-Oct-20M.csv")  # For Pandas run
