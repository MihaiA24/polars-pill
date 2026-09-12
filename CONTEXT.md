# Context

Glossary for this repository. Terms only — no implementation detail, no procedures.

The benchmark table has one column per axis below. They were conflated once already: a run's `mode`
was recorded under the `Engine` column, which is why eager runs appeared as "streaming".

## Mode

*How the query is expressed*, chosen by the demo code, not by polars.

- **Eager** — operations execute as each call is made (`pl.read_parquet`, `DataFrame.write_parquet`).
  There is no query plan and therefore no engine choice.
- **Lazy** — operations build a plan (`pl.scan_parquet`, `LazyFrame.sink_parquet`) that is optimized
  and then executed by an **Engine**.

Mode is meaningful for the e-commerce comparison. It is *not* an engine: an eager run has no engine.

## Engine

*What executes a lazy plan*, selected per call via `engine=` on `collect`/`sink_*`, or globally via
engine affinity.

- **auto** — the default. Resolves to the configured affinity, falling back to **streaming**.
- **in-memory** — materializes intermediates in RAM; the historical polars default.
- **streaming** — processes the plan in batches; stable since polars 1.41 and the default target of
  the project going forward.
- **gpu** — hands the plan to cudf-polars, falling back to the CPU unless `raise_on_fail=True`.

## Executor

A **cudf-polars** concept, not a polars one: *which GPU execution model runs the plan* once the
**gpu** engine has been selected.

- **streaming executor** — partitions inputs and streams them; the default behind `engine="gpu"`, and
  the only model that scales past device memory.
- **in-memory executor** — `GPUEngine(executor="in-memory")`; single GPU, whole query materialized in
  device memory. The only GPU path that supports `LazyFrame.profile`.

"GPU streaming" therefore means engine = gpu **and** executor = streaming. Saying "engine" for this
axis is what makes GPU rows ambiguous.

## Cluster backend

*How GPU workers are provisioned* for the streaming executor: a single implicit GPU
(`engine="gpu"`), or an explicit engine object — `DaskEngine`, `RayEngine`, `SPMDEngine` — that
manages one worker per GPU. It is a deployment choice, not a performance model: all of them run the
same streaming executor.

## Dataset

A named input to a benchmark run, not a file path.

- **ecommerce** — the multi-category store behaviour log; the CSV-versus-Parquet and
  eager-versus-lazy comparisons use it.
- **nyc-green**, **nyc-yellow** — NYC TLC taxi trip records, joined against the **zone lookup**
  (`LocationID` → borough/zone). Green is the small dataset; yellow is the one that exhausts memory
  and forces streaming.

## Query

The workload shape a run executes, held identical across libraries so the timings are comparable.

- **simple** — one grouping key, five aggregates.
- **complex** — four grouping keys including joined zone columns, same aggregates.

Both include the zone joins, even when the aggregation does not read the joined columns, because
every library being compared performs them.

## Run

A single measured execution, identified by the tuple (library, dataset, query, mode-or-engine,
CPU/GPU). One run produces one row in the benchmark table; a failed run records the failure in place
of a duration rather than disappearing.

## Plugin

A separately compiled Rust expression registered into polars through the plugin FFI (here:
`polars_sha`, providing SHA-2 hashing). It is a binary artifact built against a specific polars crate
version, so it is bound to a narrower polars range than pure-Python code and must be rebuilt when
that range moves.
