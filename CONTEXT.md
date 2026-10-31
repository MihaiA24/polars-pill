# Benchmark terminology

## Mode

How a query is expressed: eager executes each operation immediately; lazy builds an optimized
plan. Mode is separate from the engine that executes the work.

## Engine

The query execution implementation: CPU in-memory, CPU streaming, or GPU through cudf-polars.
Eager Polars uses in-memory; lazy queries select an engine.

## Executor

The GPU execution model: in-memory materializes the query in device memory; streaming processes
partitions. A cluster backend provisions workers and is separate from the executor.

## Dataset

A benchmark input, including its representation and subset. E-commerce inputs distinguish
CSV/Parquet and row limits; NYC inputs are green or yellow taxi records with a zone lookup.

## Query

The workload held equivalent across libraries. NYC simple and complex queries differ in grouping
keys, not in whether they perform the zone joins.

## Run

One measured attempt identified by library/version, input, query, execution label and device.
It produces a query duration or a failure; Spark can also record a total including initialization.

## Runtime version

The library or engine version that produced a result. New runs capture it automatically;
historical runs use the pinned versions confirmed by the maintainer.

## Plugin

Rust expressions exposed to Polars through the plugin FFI. The `polars_sha` wheel must be built
for a compatible Polars ABI.
