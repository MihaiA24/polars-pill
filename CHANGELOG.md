# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

Every entry names the upstream release or PR that forced it, so the next upgrade does not have to
re-derive the reason.

## [Unreleased] - 2026-10-31

CPU [polars 2.1.0](https://github.com/pola-rs/polars/releases/tag/py-2.1.0), GPU polars 1.44.2 /
[RAPIDS 26.10.2](https://pypi.org/pypi/cudf-polars-cu12/26.10.2/json). RAPIDS now accepts
`polars>=1.35,<1.45`, so the GPU ceiling moves without removing the split-version decision.
Historical benchmark numbers and stored notebook outputs are unchanged.

### Changed

- Both root manifests and the lock use `polars[iceberg]==2.1.0` for CPU and
  `polars[gpu]==1.44.2` / `cudf-polars-cu12>=26.10.2` for GPU. The CPU extra enables the native
  Iceberg planner instead of the slower PyIceberg-planning fallback.
- The Iceberg notebook uses `sink_iceberg` create-if-absent options with overwrite semantics;
  repeated execution no longer fails at namespace/table creation or duplicates appended data.
- The benchmark runner uses `uv sync --locked`, stops on environment setup failure, and does not
  remove prior benchmark output until its initial sync succeeds. Setup docs build the required
  plugin wheel first and refresh its hash with `uv lock --upgrade-package polars-sha`.
- Single-GPU streaming sinks on RAPIDS 26.10.2 support a file; the old directory-only workaround
  is removed and all benchmark paths reuse `data/out/polars.parquet`. Explicit distributed
  engines still require directory sinks
  ([source](https://github.com/NVIDIA/cudf/blob/v26.10.02/python/cudf_polars/cudf_polars/utils/config.py#L1364-L1371)).
- Plugin runtime dependencies contain only Polars; build/test/type/lint tools remain development
  requirements. The lock no longer brings them into `--no-dev` root installations.
- Plugin CI lives in repository-root `.github/workflows`, uses correct working directories,
  tests exact CPU/GPU/minimum Polars versions, and gates publication on those tests. The 2.1
  matrix uses Python ≥3.11; retired macOS images are replaced with supported runner labels.
- `polars_cloud.py` is renamed `cloud_monitoring_demo.py` so it cannot shadow the SDK. Monitoring
  uses the account's default workspace. RUNBOOK documents its separate 2.0 / SDK 0.12 environment:
  the SDK required by 2.1 has not been published, and `polars-nanook` is only a placeholder
  ([upstream rename preparation](https://github.com/pola-rs/polars/pull/30099)).

### Fixed

- Preprocessing normalizes names, drops obsolete columns, and adds filename-derived dates even
  when no dtype cast is needed. Canonical monthly files are skipped; rewrites use a same-directory
  temporary file and atomic replacement rather than truncating the original on write failure.
- E-commerce prices use Float64, matching pandas and Spark. Existing Float32 Parquet must be
  regenerated from CSV to recover source precision; it is not silently rewritten by the upgrade.
- NYC Polars analysis preserves fractional minutes; both Polars and Spark borough percentages
  divide by total trips rather than a hard-coded `8`.
- GPU timing/profiling/streaming comparisons use the same four grouping keys. Notebook transitions
  shut down the singleton before entering a context-managed Dask engine with strict GPU failure
  handling. Dead executable UVM setup is removed; host spilling and UVM are described separately.
- Colab installs into its kernel with pinned `%pip` commands, keeps installer errors visible, and
  replaces automatic kernel shutdowns with explicit restart/setup instructions.
- Pig Latin slices at the first character's UTF-8 boundary, not byte `1`; Unicode no longer causes
  a plugin panic. Obsolete Python <3.10 typing compatibility code and an unused alias are removed.
- The API notebook's lazy output no longer overwrites its eager output file.

### Verified

- Four root regressions pass, including actual Spark execution on Java 21, rename-only/mixed
  preprocessing and reruns, fractional durations, normalized shares, price-threshold precision,
  and preservation of results after failed benchmark setup.
- Two plugin tests pass against the rebuilt wheel on Polars 2.1.0, 1.44.2 and the declared 1.42.0
  minimum, including SHA-256/512 versus `hashlib` and Unicode Pig Latin.
- Bounded real data: 12 CPU benchmark configurations on 2.1.0; eight GPU configurations on
  1.44.2 / RAPIDS 26.10.2, with CPU/GPU output equivalence within floating-point tolerance.
- CPU API/plugin notebooks: 45 non-empty code cells execute on small real-data inputs; graph
  generation is checked as raw DOT, not a rendered notebook frontend.
- Both local GPU notebooks execute 20 code cells on small inputs. Singleton → Dask → singleton
  transitions and cleanup on success/error work with one GPU; this is not multi-GPU scaling proof.
- Colab's 18 computational cells execute locally on the GPU; all 21 code cells compile through
  IPython's transformer. Hosted package installation/download cells were not executed.
- The root environment remains on CPU 2.1.0; GPU verification uses a separate materialized
  environment. Full-size timings, hosted Colab installation, and authenticated cloud monitoring
  were not run. Existing wall-clock/broad-exception Ruff diagnostics in the benchmark module
  remain unchanged; pipeline/plugin/new-test Ruff checks pass.

## polars 2.0 step - 2026-10-07

Upgrade of the CPU stack from polars 1.42.1 to **2.0.0**
([release](https://github.com/pola-rs/polars/releases/tag/py-2.0.0),
[upgrade guide](https://docs.pola.rs/releases/upgrade/2/)); the GPU stack stays on 1.42.1. This
builds on the 1.42.1 step below, and both ship together from `chore/polars-v2-upgrade` (formerly
`chore/polars-1.42.1-upgrade`). Benchmarks were **not** re-run: the table in `README.md` still
reports polars 1.32.3.

### Changed

- **`cpu_polars` pinned to `polars==2.0.0`; `gpu_polars` stays at `polars[gpu]==1.42.1`**
  (`pyproject.toml`, `pyproject_with_sha_example.toml`). This replaces the single version of ADR 0002
  with [ADR 0003](docs/adr/0003-polars-2-on-cpu-gpu-held-at-1.42.1.md). No cudf-polars release
  supports polars 2: `cudf-polars-cu12` 26.8.1 requires `polars>=1.35,<1.43` and the 26.10/26.12
  nightlies `<1.45`. Forced onto polars 2.0.0, cudf-polars 26.8.1 fails at import
  (`AttributeError: module '_ir_nodes' has no attribute 'ExtContext'`) on every `GPUEngine` collect,
  with or without `raise_on_fail`.
- **CPU and GPU benchmark rows now come from different polars versions.** `run_benchmark.sh` swaps
  groups mid-run, so the swap moves polars from 2.0.0 to 1.42.1 as well as changing the engine. Noted
  above the table in `README.md`, in RUNBOOK §3/§5 and in ADR 0001.
- **`uv.lock` re-resolved**: polars and `polars-runtime-32` 2.0.0 added for `cpu_polars`, 1.42.1 kept
  for `gpu_polars`, nothing else moved. The `polars-sha` entry was re-recorded from a fresh build: the
  committed one carried another build's wheel hash and stale `polars>=1.20` metadata, so `uv sync`
  without `-U` failed with `Hash mismatch for polars-sha` after any rebuild. RUNBOOK §1 now says to
  run `uv lock --upgrade-package polars-sha` after building.
- **Plugin CI: Python 3.9 → 3.10** in the `linux-just-test` matrix
  (`polars_sha/.github/workflows/publish_to_pypi.yml`). `requires-python` was already `>=3.10` and
  polars has shipped no 3.9 wheels since 1.37, so that job could not install `polars>=1.42`. It now
  resolves polars 2.0.0; `linux-min-versions-just-test` keeps 1.42.1, the GPU pin.

### Fixed — required by polars 2.0

- **`LazyFrame.profile()` was removed.** The GPU notebook comments called it deprecated; they now say
  it only runs because the GPU stack is on 1.42.1 and that the cells go when it moves
  (`Polars_GPU_01_Memory.ipynb`, `Polars_GPU_Colab.ipynb`). CONTEXT.md and RUNBOOK §5 likewise.
- **Colab install line** states why it stays on `polars[gpu]==1.42.1`.

### Fixed — wrong claims from the 1.42.1 step

- **`engine="auto"` did not mean streaming for `collect()` on 1.x.** The 1.42.1 step said it did
  from 1.41 on (`00_preprocess.py`, CONTEXT.md, RUNBOOK §5, `Polars_GPU_02_Streaming.ipynb`,
  `Polars_GPU_Colab.ipynb`). Measured with `POLARS_VERBOSE=1`: a bare `collect()` runs the in-memory
  engine on 1.42.1 and the streaming engine on 2.0.0 — the 2.0 change "The Lazy API defaults to the
  streaming engine". On 1.x only `sink_*` streamed by default, and sinks are all `00_preprocess.py`
  uses, so removing `set_engine_affinity("streaming")` there was still right. All five now date the
  switch to 2.0.
- **Eager runs do use an engine.** `polars_evaluation.py` said eager mode involves "no lazy engine at
  all"; in 2.0 `pl.read_csv`/`pl.read_parquet` are `scan_*()` collected through `_collect_eager()`,
  which always selects the in-memory engine — what the eager rows' `in-memory` label records. Comment
  and CONTEXT.md "Mode" corrected.

### Verified — no code change needed

Each 2.0 breaking change was checked against the code:

- **CSV `schema` is matched by header name, not position** (`read_csv`/`scan_csv`). The e-commerce
  CSV and zone lookup headers carry the same names, in the same order, as `pl_schema`/`zone_schema`.
- **Streaming does not preserve row order for `group_by`/joins.** Every NYC query sorts before it
  sinks; the e-commerce output and the notebooks' `head()` previews do not depend on order.
- **String → temporal casts removed.** `generate_polars_cast` emits none (see the 1.42.1 step).
- **`show_graph()` defaults to `plan_stage="physical"`.** `Polars_API.ipynb` already passes
  `plan_stage="ir"`.
- **Removed APIs** (individual optimization flags, `streaming=`, `with_row_count`,
  `join(how="outer")`, …): none used.
- **Plugin.** No Rust crates for polars 2 are published (crates.io's newest `polars` is 0.55.2), so
  `polars_sha/Cargo.toml` is unchanged. The 0.55.2 / pyo3-polars 0.28 build loads on py-polars 2.0.0
  and 1.42.1 and matches `hashlib` for `sha2_256`/`sha2_512`, including nulls and a 300k-row streaming
  collect; `polars_sha/tests` passes on 2.0.0.

Evidence, on subsets of the real data (300k e-commerce rows; green 2014/2019/2023-01, yellow
2021/2023-01), polars 2.0.0 against 1.42.1:

- `00_preprocess.py`: all 11 outputs identical.
- `polars_evaluation.py`: all 13 CPU polars configurations from `run_benchmark.sh` succeed with the
  same results and sorted NYC output. `Float32` sums differ in the last bits (max 0.016 on values
  around 1.3e5), as they also do between two runs of 1.42.1.
- `nyc/polars_evaluation.py`: all six outputs equal within that tolerance.
- `Polars_API.ipynb`, `Polars_Plugins.ipynb`: execute with no errors or warnings, except the two
  `show_graph` cells, which need the graphviz `dot` binary (absent on the test machine); their DOT
  output was checked with `raw_output=True`. The `explain()` cell still shows both joins, with only
  `LocationID` read from the zone lookup.
- GPU stack (`gpu_polars` synced from the new lock with `--frozen`; polars 1.42.1, cudf-polars
  26.8.1, RTX 5090 Laptop): the plugin loads, and the simple NYC query succeeds on both executors.
  The complex query could not be judged — another process held 23 of the GPU's 24 GB.

### Added

- `docs/adr/0003-polars-2-on-cpu-gpu-held-at-1.42.1.md` — why the groups run different polars
  versions, and what to change when cudf-polars supports polars 2. ADR 0002 is marked superseded.

### Deliberately not changed

- **Benchmark table and stored notebook outputs**: not re-measured or re-executed.
- **No polars 2 feature demos** (`Map` dtype, SQL, out-of-core spill): this is an upgrade only.
- **GPU code**: still on 1.42.1; only comments changed.

## polars 1.42.1 step - 2026-09-12

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
  GPU rows into one table. *Superseded for `cpu_polars` by the polars 2.0 entry above.*
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
  when no affinity is set. The call was a no-op restating the default. *Corrected in the polars 2.0
  entry: on 1.x this held for `sink_*` only; `collect` defaulted to in-memory until 2.0.*
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
  it requires a full environment swap; `DaskEngine` needs more than one GPU in any case. *Single-GPU
  paths were run during the polars 2.0 step; see that entry.*
