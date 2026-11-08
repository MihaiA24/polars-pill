import polars as pl

# Requires a compatible cloud SDK in a separate environment; see RUNBOOK.md.
pl.Config.enable_monitoring()

print(
    pl.LazyFrame(
        {
            "quantity": [1, 2, 3, 4, 3],
            "price": [34.2, 43.2, 123.1, 23.3, 42],
            "order_id": [1, 1, 2, 2, 2]
        }
    )
    .group_by("order_id")
    .agg((pl.col("quantity") * pl.col("price")).sum())
    .collect()
)