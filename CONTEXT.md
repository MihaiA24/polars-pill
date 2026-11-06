# Benchmark terminology

## Mode

How a query is expressed: eager executes each operation immediately; lazy builds an optimized
plan. Mode is separate from the engine that executes the work.

## Engine

The query execution implementation. Polars selects CPU in-memory, CPU streaming, or GPU through
cudf-polars; DuckDB uses its native engine. Eager Polars uses in-memory; lazy queries select an engine.

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

One measured attempt associated with a library version, workload, execution configuration and
phase. It yields timings or a failure.

## Batch

Repeated measurements of one workload and execution configuration in one process.
Results from different batches are not pooled into a single performance estimate.

## Suite

Configuration batches collected during one benchmark invocation. A suite can be partial
if execution stops before the matrix finishes.

## Phase

Cold is the first query in a fresh process; warm follows warm-ups in that reused process.
Neither implies a flushed filesystem cache.

## Baseline

A successful result chosen as the reference for a comparison.

## Speedup

The baseline latency divided by the candidate latency for matching workloads and
measurement conditions. Values above one mean the candidate is faster.

## Runtime version

The library or engine version that produced a result. New runs capture it automatically;
historical runs use the pinned versions confirmed by the maintainer.

## Plugin

Rust expressions exposed to Polars through the plugin FFI. The `polars_sha` wheel must be built
for a compatible Polars ABI.
