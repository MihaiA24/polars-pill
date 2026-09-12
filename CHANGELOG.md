# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

Every entry names the upstream release or PR that forced it, so the next upgrade does not have to
re-derive the reason.

## [Unreleased] - 2026-09-12

Upgrade from polars 1.32.3 (2025-08-14) to 1.42.1, across scripts, notebooks and the Rust plugin.
Benchmarks were **not** re-run: the table in `README.md` is unchanged and still reports the numbers
measured on polars 1.32.3.

### Changed

- **polars pinned to `==1.42.1`** in both `cpu_polars` and `gpu_polars` (`pyproject.toml:23-33`), up
  from `>1.31.0`. Not 1.44.2, which is the current release: no cudf-polars build supports polars
  ≥ 1.43. The newest RAPIDS release,
  [`cudf-polars-cu12` 26.8.1](https://pypi.org/project/cudf-polars-cu12/26.8.1/), requires
  `polars>=1.35,<1.43`, so **1.42.1 is the ceiling while the GPU engine has to work**. A single
  version is used for both groups because `run_benchmark.sh` swaps groups mid-run and writes CPU and
  GPU rows into one table.
- **`cudf-polars-cu12>=26.8.1` is now declared explicitly** in the `gpu_polars` group. polars' own
  `gpu` extra is unversioned (`cudf-polars-cu12; extra == "gpu"`), so with polars pinned the resolver
  walked backwards to the `24.8.0a281` placeholder package and `uv sync` failed trying to build
  `cudf-cu12` from a stub sdist.
- **`requires-python`: `==3.12.9` → `>=3.12,<3.13`.** The exact-patch pin rejected every other 3.12
  build. polars 1.42.1 needs ≥ 3.10; the binding constraint in this stack is pandas 3.0 / cudf-polars
  at ≥ 3.11. `.python-version` still selects 3.12.9.
- **Dependency floors moved to current releases**: `deltalake` 1.0.2 → 1.6.3, `duckdb` 1.3.0 → 1.5.5,
  `pyarrow` 21 → 25.0.1, `pyspark` 4.0 → 4.2.0, `pandas` 2.2.3 → 3.0.5, `pyiceberg` 0.10 → 0.12.0.
- **`pydantic < 2.12.0` pin removed.** It existed because pydantic 2.12.0 broke PyIceberg table
  creation ([iceberg-python#2590](https://github.com/apache/iceberg-python/issues/2590)). PyIceberg
  now rejects 2.12.0/2.12.1 in its own metadata
  ([#2635](https://github.com/apache/iceberg-python/pull/2635)), so the hand-pin is redundant.
- **Rust plugin rebuilt against the current ABI** (`polars_sha/Cargo.toml`): `pyo3` 0.25 → 0.29,
  `pyo3-polars` 0.22 → 0.28, `polars`/`polars-arrow` 0.49.1 → 0.55.2. pyo3-polars 0.28 requires the
  polars 0.55 crate family and pyo3 0.29; plugins are separately compiled binaries with no stability
  guarantee across polars versions, and polars 1.37 changed the plugin FFI call path
  ([#26000](https://github.com/pola-rs/polars/pull/26000)). The wheel keeps its `cp39-abi3` tag, so
  the `[tool.uv.sources]` path is unchanged.
- **`ethnum` 1.5.2 → 1.5.3** in `polars_sha/Cargo.lock`. Not a polars change: 1.5.2 fails to compile
  on rustc 1.97 with `E0512: cannot transmute between types of different sizes`, which killed the
  plugin build.
- **Plugin metadata aligned with the ABI it is built for**: `polars>=1.42` in
  `polars_sha/pyproject.toml` and `requirements.txt`, `requires-python = ">=3.10"` (polars dropped
  Python 3.9 in 1.37, [#25984](https://github.com/pola-rs/polars/pull/25984)), and the CI
  "min versions" job moved from Python 3.9 + polars 1.3.0 to Python 3.10 + polars 1.42.1 — a plugin
  built against the polars 0.55 crates cannot be loaded by py-polars 1.3.0.

### Fixed — required by polars changes

- **`no_optimization=True` → `optimizations=pl.QueryOptFlags.none()`** (`Polars_API.ipynb`, lazy
  collect cell). The boolean optimization flags on `LazyFrame.collect` are deprecated since polars
  1.30 in favour of `QueryOptFlags`.
- **`show_graph()` now passes `plan_stage="ir"`** (`Polars_API.ipynb`, both graph cells). polars
  1.43.2 deprecated omitting `plan_stage`
  ([#28391](https://github.com/pola-rs/polars/pull/28391)); the default flips from `"ir"` to
  `"physical"` in 2.0, so the previous calls would silently start showing a different graph.
- **`pl.Config.set_engine_affinity("streaming")` removed** (`00_preprocess.py`). polars 1.41
  stabilised the streaming engine ([#27497](https://github.com/pola-rs/polars/pull/27497)) and
  `engine="auto"` — the default for every `collect`/`sink_*` — already falls back to `"streaming"`
  when no affinity is set. The call was a no-op restating the default.
- **Multi-GPU cells ported to `DaskEngine`** (`Polars_GPU_02_Streaming.ipynb`,
  `Polars_GPU_Colab.ipynb`). `GPUEngine(executor="streaming", executor_options={"scheduler":
  "distributed"})` plus a hand-built `dask_cuda.LocalCUDACluster` is superseded: since cudf-polars
  26.06 the cluster backends are engine classes (`DaskEngine`, `RayEngine`, `SPMDEngine`) that
  provision their own workers. Install line changed from `dask_cuda` to `cudf-polars-cu12[dask]`.
- **GPU streaming runs now sink to a directory path** (`polars_evaluation.py`). With a streaming GPU
  engine, cudf-polars sinks "always produce a directory containing one or more files" and
  `sink_to_directory=False` raises `ValueError`; the previous single-file path
  `data/out/polars.parquet` was written under both CPU and GPU streaming.
- **`pl.Utf8` → `pl.String`** in the `map_elements` UDF comparison (`Polars_Plugins.ipynb`), matching
  the spelling used everywhere else in the repo.
- **Colab install pinned** to `polars[gpu]==1.42.1` + `cudf-polars-cu12>=26.8.1`, replacing
  `polars[gpu]>=1.27.0`, which now resolves to a version combination that cannot work.

### Fixed — repo bugs found during the upgrade

- **The `Engine` column was wrong for every e-commerce row.** `polars_evaluation.py` recorded a
  hardcoded `"streaming"` regardless of mode, so eager runs — `read_parquet`/`read_csv` +
  `write_parquet`, which involve no lazy engine at all — were logged as streaming. The engine is now
  derived from the path actually taken (`in-memory` for eager, `streaming` for lazy). Existing README
  rows were left untouched; they predate the fix.
- **Every NYC failure was labelled `Error (memory)`.** The blanket `except Exception` overwrote the
  cause, so a typo and an OOM produced the same benchmark row. The row now carries the exception type
  and the full error is printed to stderr.
- **`cpu_gpu` could be unbound in the error path**: it was assigned inside the `try`, but read after
  it, so a failure before that line raised `NameError` instead of recording the real error.
- **`import rmm` removed from `nyc/polars_evaluation.py`.** `rmm` was never used and is GPU-only, so
  the script raised `ModuleNotFoundError` on any CPU-only machine.
- **Sinks create their output directory** (`mkdir=True`). `download_datasets.sh` creates `data` and
  `data/out` but never `data/nyc-taxi/out`, so `nyc/polars_evaluation.py` failed on its first sink on
  a fresh checkout. `mkdir` on writers/sinks was added in polars 1.33
  ([#24239](https://github.com/pola-rs/polars/pull/24239)).
- Removed an unused `polars.selectors` import (`00_preprocess.py`), a dead `end_time` assignment and
  a commented-out call to a function that does not exist (`polars_evaluation.py`).

### Performance

- **`nyc/polars_evaluation.py` runs as one pass instead of six.** All six outputs are now deferred
  with `sink_*(lazy=True)` and executed by a single `pl.collect_all(...)`; previously each sink
  re-ran the scan, filter and the five derived columns. Measured on `green.parquet`, 3 runs, median:
  **7.68 s → 5.45 s (-29 %)**.
  - Caveat, measured: batching helps only when the sinks share expensive work. For a batch of five
    cheap aggregations with no shared large sink, `collect_all` was *slower* than separate sinks
    (green 3.30 s → 3.87 s; yellow 34.7 s → 40.4 s), presumably because the separate queries each get
    the full thread pool. Do not batch aggregations reflexively.

### Added

- `Polars_API.ipynb`: an `explain()` cell showing what the optimizer does with the benchmark's NYC
  query shape — projection pushdown drops every unused zone column, while the inner joins remain,
  because a join can still remove rows. Verified: the printed plan contains the joins and no
  `Borough`/`Zone` projections.
- `CONTEXT.md` — glossary. `mode`, `engine` and cudf-polars' `executor` were used interchangeably in
  this repo, which is what produced the mislabelled benchmark column.
- `RUNBOOK.md` — the manual benchmark procedure and what changed operationally since 1.32.3.
- `docs/adr/0001-benchmark-comparability.md` — why every library runs identical work, including joins
  a given query does not need.
- `docs/adr/0002-polars-pinned-to-the-gpu-engine-ceiling.md` — why the pin is 1.42.1 and not the
  newest polars release.

### Deliberately not changed

- **The benchmark table in `README.md`** — no numbers were re-measured, so nothing in it was edited,
  including the three mislabelled `Polars eager / streaming` rows.
- **Stored notebook outputs**, including the CUDA `MemoryError` traceback in
  `Polars_GPU_02_Streaming.ipynb` — they are demo artifacts from the 1.32.3 run.
- **The zone joins in the NYC "simple" query.** They are unused by that query's aggregation, but
  removing them from polars only would produce a faster polars number for a reason unrelated to
  polars, and `pyspark_evaluation.py` performs the same joins. Parity beats the micro-optimization;
  the point is made in the notebook instead.
- **`LazyFrame.profile()` in the GPU notebooks.** polars deprecated it in 1.43
  ([#28275](https://github.com/pola-rs/polars/pull/28275)) because it assumes a single in-memory
  pass, but cudf-polars documents the GPU in-memory executor as the place where `profile` *is*
  supported ("Streaming engines do not support `LazyFrame.profile`… the in-memory engine supports
  it"). The calls stay; a comment records the CPU-side deprecation.
- **`GPUEngine(executor="in-memory")` and the manual RMM/UVM cells** — both still documented by
  cudf-polars; they are the "how it works underneath" material.
- **`schemas.py:generate_polars_cast`.** polars 1.42 deprecated string → temporal casts
  ([#28056](https://github.com/pola-rs/polars/pull/28056)); checked against the actual data, the
  datetime columns are already `Datetime(time_unit="ms")` on disk, so no such cast is generated.

### Known issues

- **PySpark 4.2 warns on pandas 3**: `PySpark does not yet fully support pandas >= 3.0.0`. It affects
  Spark↔pandas conversion only; `pyspark_evaluation.py` and `nyc/pypsark_evaluation.py` use no pandas
  interop (verified), and a `SparkSession` + CSV read works on Java 21.
- **Whether `POLARS_GPU_ENABLE_CUDA_MANAGED_MEMORY` still exists in cudf-polars 26.8 is unverified.**
  The 26.x docs describe `StreamingOptions` instead. The env var is set in the GPU notebooks and in
  `polars_evaluation.py` when forcing the in-memory executor; if it is gone, those lines are dead
  code rather than wrong code.
- **No GPU code path was executed.** The `gpu_polars` group conflicts with `cpu_polars`, so verifying
  it requires a full environment swap; `DaskEngine` needs more than one GPU in any case.
