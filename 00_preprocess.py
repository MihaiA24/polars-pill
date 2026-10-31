import glob
from pathlib import Path
from tempfile import NamedTemporaryFile

import polars as pl

from schemas import generate_polars_cast, pl_schema

# Some parquets use different names and dtypes; normalize both before merging.
for color, column_mapping in {
    "green": {
        "lpep_pickup_datetime": "tpep_pickup_datetime",
        "lpep_dropoff_datetime": "tpep_dropoff_datetime",
        "ehail_fee": "airport_fee",
    },
    "yellow": {"Airport_fee": "airport_fee"},
}.items():
    for file in glob.glob(f"data/nyc-taxi/{color}/*/*.parquet"):
        path = Path(file)
        schema = pl.read_parquet_schema(path)
        renames = {source: target for source, target in column_mapping.items() if source in schema}
        drop_columns = ["trip_type"] if color == "green" and "trip_type" in schema else []
        for source, target in renames.items():
            schema[target] = schema.pop(source)
        for column in drop_columns:
            schema.pop(column)
        year_dtype = schema.pop("year", None)
        month_dtype = schema.pop("month", None)
        cast_schema = generate_polars_cast(schema)
        if not (renames or drop_columns or cast_schema or year_dtype != pl.Int16 or month_dtype != pl.Int8):
            print("Skipping... ", file)
            continue

        print("Formatting... ", file)
        # Pickup dates can be wrong (for example, 2081); use the filename instead.
        _, year, month = path.stem.split("-")
        # Read eagerly before replacing the source; scanning and sinking the same path is unsafe.
        df = (
            pl.read_parquet(path)
            .drop(drop_columns)
            .rename(renames)
            .with_columns(
                *cast_schema,
                pl.lit(int(year), dtype=pl.Int16).alias("year"),
                pl.lit(int(month), dtype=pl.Int8).alias("month"),
            )
        )
        with NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as temporary:
            temporary_path = Path(temporary.name)
        try:
            df.write_parquet(temporary_path)
            temporary_path.replace(path)
        finally:
            temporary_path.unlink(missing_ok=True)

    print(f"Merging {color} parquets...")
    pl.scan_parquet(f"data/nyc-taxi/{color}/*/*.parquet").sink_parquet(f"data/nyc-taxi/{color}.parquet")


pl.scan_csv("data/2019-Nov.csv", schema=pl_schema).sink_parquet("data/2019-Nov.parquet")

pl.scan_csv("data/2019-Oct.csv", schema=pl_schema).sink_parquet("data/2019-Oct.parquet")

pl.scan_csv("data/2019-Oct.csv", schema=pl_schema).limit(10_000_000).sink_parquet("data/2019-Oct-10M.parquet")

pl.scan_csv("data/2019-Oct.csv", schema=pl_schema).limit(20_000_000).sink_csv("data/2019-Oct-20M.csv")  # For Pandas run
