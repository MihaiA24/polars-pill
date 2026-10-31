from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import polars as pl

    IntoExprColumn = pl.Expr | str | pl.Series
