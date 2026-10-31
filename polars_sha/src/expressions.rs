#![allow(clippy::unused_unit)]
use polars::prelude::*;
use pyo3_polars::derive::polars_expr;
use std::fmt::Write;
use crate::sha_hashers::{sha2_256_hash, sha2_512_hash};

#[polars_expr(output_type=String)]
fn pig_latinnify(inputs: &[Series]) -> PolarsResult<Series> {
    let ca: &StringChunked = inputs[0].str()?;
    let out: StringChunked = ca.apply_into_string_amortized(|value: &str, output: &mut String| {
        if let Some(first_char) = value.chars().next() {
            write!(output, "{}{}ay", &value[first_char.len_utf8()..], first_char).unwrap()
        }
    });
    Ok(out.into_series())
}


#[polars_expr(output_type=String)]
fn sha2_256(inputs: &[Series]) -> PolarsResult<Series> {
    let ca = inputs[0].str()?;
    let out: StringChunked = ca.apply_into_string_amortized(sha2_256_hash);
    Ok(out.into_series())
}

#[polars_expr(output_type=String)]
fn sha2_512(inputs: &[Series]) -> PolarsResult<Series> {
    let ca = inputs[0].str()?;
    let out: StringChunked = ca.apply_into_string_amortized(sha2_512_hash);
    Ok(out.into_series())
}