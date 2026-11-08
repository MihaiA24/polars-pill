from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl
from polars.plugins import register_plugin_function

from polars_sha._internal import __version__ as __version__

if TYPE_CHECKING:
    IntoExprColumn = pl.Expr | str | pl.Series

LIB = Path(__file__).parent


def pig_latinnify(expr: IntoExprColumn) -> pl.Expr:
    return register_plugin_function(args=[expr], plugin_path=LIB, function_name="pig_latinnify", is_elementwise=True)


def sha2_256(expr: IntoExprColumn) -> pl.Expr:
    """Takes Utf8 as input and returns utf8 hash with sha256 from SHA-2 family."""
    return register_plugin_function(plugin_path=LIB, function_name="sha2_256", args=[expr], is_elementwise=True)


def sha2_512(expr: IntoExprColumn) -> pl.Expr:
    """Takes Utf8 as input and returns utf8 hash with sha512 from SHA-2 family."""
    return register_plugin_function(plugin_path=LIB, function_name="sha2_512", args=[expr], is_elementwise=True)
