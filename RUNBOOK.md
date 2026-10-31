# Runbook — running the benchmarks

Procedure for recording versioned benchmark history and generating performance diagrams. Vocabulary
(mode / engine / executor / query / dataset / runtime version) is defined in [CONTEXT.md](CONTEXT.md);
upgrade details are in [CHANGELOG.md](CHANGELOG.md).

Current pins: **polars 2.1.0** with native Iceberg planning in `cpu_polars`, **polars 1.44.2** /
**cudf-polars-cu12 26.10.2** in `gpu_polars`, Python 3.12.9. RAPIDS requires `polars<1.45`, so the
groups remain separate ([ADR 0003](docs/adr/0003-polars-2-on-cpu-gpu-held-at-1.42.1.md)).
Both groups use **pandas 3.1.0** and **PySpark 4.3.0**. The project's Python 3.12 and PyArrow 25
already satisfy their requirements; pandas 3.1 requires NumPy ≥2.0.2, which the lock also satisfies.

## 0. Prerequisites

| Requirement | Checked with | Notes |
|---|---|---|
| Python 3.12 | `uv python list` | `.python-version` selects 3.12.9 |
| Java 17 or 21 | `java -version` | PySpark 4.3; verified on OpenJDK 21 |
| Rust toolchain | `cargo --version` | only to rebuild the plugin; needs ≥ 1.83 for pyo3 0.29 |
| Datasets | `ls data/nyc-taxi` | `download_datasets.sh`, then `00_preprocess.py` |
| ~40 GB free disk | `df -h .` | outputs are overwritten each run, but `efficiency.parquet` alone is 2.4 GB on green |

## 1. Build the plugin first

The wheel referenced by `[tool.uv.sources]` must exist before any `uv sync`. `target/` is not
committed, so every checkout builds its own, and that one wheel is installed by both dependency
groups — it has to load on polars 1.44.2 and 2.1.0.

```shell
make -C polars_sha venv
make -C polars_sha build-wheel
```

Produces `polars_sha/target/wheels/polars_sha-0.1.0-cp39-abi3-manylinux_2_34_x86_64.whl`. The file
name is what `pyproject.toml` points at — if maturin ever emits a different tag, update that path.

`uv.lock` records the wheel's hash, and Rust builds are not byte-reproducible, so a fresh build no
longer matches the lock (`Hash mismatch for polars-sha`). Re-record it before syncing:

```shell
uv lock --upgrade-package polars-sha
```

Smoke check after syncing (step 2):

```shell
.venv/bin/python -c "
import polars as pl, polars_sha as sha, hashlib
df = pl.DataFrame({'s': ['abc']}).with_columns(sha.sha2_256('s').alias('h'))
assert df['h'][0] == hashlib.sha256(b'abc').hexdigest()
print('plugin ok')"
```

## 2. Sync the environment

```shell
uv sync --locked --group cpu_polars --no-dev   # benchmark dependencies only
uv sync --locked --group cpu_polars            # include notebook/ruff/cookiecutter
```

`cpu_polars` and `gpu_polars` are declared conflicting: syncing one **uninstalls** the other. That is
also what `run_benchmark.sh` does halfway through its command list.

The runner uses `--locked`, not `-U`: dependencies cannot drift between measurements. A failed
environment setup aborts before querying under the wrong stack. Existing JSON records and the
README are never deleted or rewritten by benchmark execution.

## 3. Run the full matrix

```shell
./run_benchmark.sh
```

The script runs CPU sync (polars 2.1.0) → e-commerce comparisons (pandas 3.1.0,
polars eager and lazy, PySpark 4.3.0, CSV and Parquet) → NYC green → NYC yellow → GPU sync
(polars 1.44.2) → the same NYC runs on GPU.

Each measured run appends one JSON object to `benchmarks.jsonl`. At the end, the runner loads the
development dependencies with `uv run --locked --group gpu_polars` and generates `BENCHMARKS.html`.
Repeated invocations append new runs rather than replacing historical results. There is no
intermediate Markdown table or README publication step.

Consequences worth knowing before you start it:

- **History is append-only.** Single commands also append records. If a matrix stops halfway
  through, completed records remain available; regenerate the report manually using §9.
- **Failures are not zero-duration successes.** Caught errors have `duration_seconds: null` and
  an error message. An uncaught exception or killed process can still exit before recording a row.
- **Yellow in-memory is expected to fail or thrash** on a 32 GB machine. That is the point of the
  row.
- **Rebuild e-commerce Parquet before new comparisons.** `pl_schema["price"]` is now Float64,
  matching pandas and Spark. Files previously written as Float32 cannot recover discarded precision;
  regenerate them from CSV with `00_preprocess.py`.

Single runs, same arguments the script uses:

```shell
.venv/bin/python polars_evaluation.py --file_path data/2019-Oct.parquet --file_type parquet --mode lazy
.venv/bin/python polars_evaluation.py --dataset_type nyc-green --engine streaming --execution_query complex
.venv/bin/python polars_evaluation.py --dataset_type nyc-yellow --engine streaming --execution_query simple --gpu_engine True
```

## 4. GPU runs

```shell
uv sync --locked --group gpu_polars --no-dev
```

Installs the locked `cudf-polars-cu12` 26.10.2 CUDA 12 wheels and swaps polars 2.1.0 for 1.44.2.
The `polars[gpu]` extra selects CUDA 12 packages; a CUDA 13 package selection must also avoid
pulling that CUDA 12 extra. Use a materialized environment via `uv sync` for native GPU libraries.

- `--gpu_engine True --engine streaming` runs the **streaming executor**. RAPIDS 26.10.2's
  single-GPU default supports a file sink, so all benchmark paths overwrite `data/out/polars.parquet`.
  Explicit Dask/Ray/SPMD engines still require directory sinks.
- `--gpu_engine True --engine in-memory` runs the **in-memory executor**, which is limited to device
  memory (16 GB here) and is expected to OOM on yellow.
- `raise_on_fail=True` is set, so an unsupported operation raises instead of silently falling back to
  the CPU and recording a CPU time in a GPU row.

## 5. What changed operationally since polars 1.32.3

- **The CPU group is on polars 2.1.0, the GPU group on 1.44.2.** RAPIDS 26.10.2 requires
  `polars>=1.35,<1.45`; do not override its upper bound to force polars 2 into the GPU group.
- **CPU and GPU rows come from different polars versions.** The group swap in `run_benchmark.sh`
  changes the polars version as well as the engine.
- **`engine="auto"` means streaming for lazy queries on polars 2.0** (`collect`, `collect_all`). On
  1.44.2 it still means in-memory for `collect`; `sink_*` streams on both. Eager calls
  (`read_csv`, `read_parquet`, `DataFrame` methods) run in-memory on both. The streaming engine does
  not keep row order for `group_by` or joins, so every NYC query sorts before it sinks.
- **Single-GPU streaming sinks can write a file.** The old directory-only workaround is removed.
- **Multi-GPU uses `DaskEngine`** from `cudf_polars.engine.dask`. Install its `[dask]` extra in the
  same kernel environment. Shut down `DefaultSingletonEngine` before constructing an explicit
  engine, and use a context manager to release the cluster. The notebooks do both; multiple GPUs
  are needed to demonstrate scaling.
- **`LazyFrame.profile()` was removed in polars 2.0.** It remains deprecated on the 1.44.2 GPU
  stack, where cudf-polars supports it only on the in-memory executor.
- **One plugin wheel serves both groups.** It is compiled against the polars Rust crates 0.55.2
  (pyo3-polars 0.28); no Rust crates for polars 2 are published yet. After any rebuild, run the smoke
  check above in both groups.
- **Spark 4.3 still warns about pandas ≥3 for Spark↔pandas conversion.** The benchmark uses Spark
  DataFrames directly, not those conversion APIs; pandas is measured separately. The warning is
  not suppressed. See the [Spark source](https://github.com/apache/spark/blob/v4.3.0/python/pyspark/sql/pandas/utils.py).
- **Spark NYC joins use named pickup/drop-off keys.** Reusing the lookup's `LocationID` expression
  with ambiguity checks disabled dropped cross-zone trips and duplicated same-zone trips. Both
  query variants now match the Polars workload; old timings were not re-measured.

## 6. Notebooks

Notebook outputs in the repo were produced on polars 1.32.3 and were deliberately **not** cleared or
re-executed during the upgrades; the code cells are current, the stored outputs are
historical. `Polars_API.ipynb` and `Polars_Plugins.ipynb` run in `cpu_polars` (polars 2.1.0); the
`Polars_GPU_*` notebooks need `gpu_polars` (polars 1.44.2). If restarting after an intentional GPU
OOM, rerun the setup and engine-definition cells identified by the notebook.
`Polars_API.ipynb`'s `show_graph` cells also need the graphviz `dot` binary on `PATH`.

`Polars_GPU_Colab.ipynb` is for Colab/Kaggle only and installs its own pinned environment.

## 7. Regression checks

After CPU synchronization:

```shell
.venv/bin/python -m unittest discover -s tests -v
uv run --no-project --python .venv/bin/python --with pytest --with polars==2.1.0 \
  --with ./polars_sha/target/wheels/polars_sha-0.1.0-cp39-abi3-manylinux_2_34_x86_64.whl \
  python -m pytest polars_sha/tests -q
```

The root checks create temporary data, not production outputs; the Spark check skips without Java.
Repeat the plugin command with `polars==1.44.2` for the GPU environment's Python/FFI contract.
Actual GPU execution and notebook lifecycle checks are separate from that CPU-only plugin test.

## 8. Cloud monitoring

`cloud_monitoring_demo.py` runs a local query and uploads monitoring metrics; it is not a remote
compute example. Its old filename, `polars_cloud.py`, shadowed the SDK.

Polars 2.1 expects cloud SDK ≥0.13.0, but the currently published `polars-cloud` 0.12.0 requires
polars 2.0.0; `polars-nanook` 0.0.1 is only a reserved-name placeholder. Do not install either into
the 2.1 CPU group as a workaround. Until a compatible SDK is published, use a separate environment:

```shell
uv venv /tmp/polars-cloud-demo
uv pip install --python /tmp/polars-cloud-demo/bin/python "polars-cloud==0.12.0"
/tmp/polars-cloud-demo/bin/python cloud_monitoring_demo.py
```

This requires a cloud account and authentication; `enable_monitoring()` uses its default workspace.
See the [SDK metadata](https://pypi.org/pypi/polars-cloud/json) and
[Polars 2.1 package-rename preparation](https://github.com/pola-rs/polars/pull/30099).

## 9. Results, charts, and historical provenance

`benchmarks.jsonl` is the source of truth. Every new record stores the library's actual running
`version`, a UTC recording timestamp, the original library/device/execution/dataset/query labels,
and numeric `duration_seconds`. GPU records also include the installed cudf-polars `backend_version`.
Spark's `total_seconds` includes session initialization plus the query; it is not initialization
time alone. Successful records have `error: null`; caught failures have an error string and no
numeric duration. Timing uses `perf_counter`; JSON serialization happens after measurement.

Generate the report without rerunning queries. Matplotlib is a development dependency; a minimal
`--no-dev` environment must include that group first:

```shell
uv sync --locked --group cpu_polars # Or --group gpu_polars for the GPU environment.
.venv/bin/python plot_benchmarks.py
.venv/bin/python plot_benchmarks.py --input benchmarks.jsonl --output BENCHMARKS.html
```

Open `BENCHMARKS.html` locally in a browser; viewing it needs no network or Python packages.
Each dataset/query starts with a compact table of every attempt, version, device, execution label,
query/total seconds and outcome. GPU versions include the cudf-polars version. Expand run details
for timestamps and provenance. A Matplotlib horizontal bar chart follows each table, with consistent
library/device colours, a legend and row numbers linking bars to the table. Workloads have separate
zero-based linear scales and are not averaged. Failed runs stay in the table without a fabricated
zero-time bar. Tables and charts scroll locally on narrow screens, keeping chart labels readable.

Malformed JSON and invalid durations are rejected with a source line number. Verification fixtures
write only to temporary directories, never to the published history.

The 28 historical rows were published together in
[`00aa8e9`](https://github.com/MihaiA24/polars-pill/commit/00aa8e90e4324f9f8469dcd0e4061617bfdc0b0f).
The maintainer confirmed that these runs used the versions pinned in that revision. Those versions
are stored directly in `version` and `backend_version`, without unverified/snapshot labels:

- pandas 2.3.2; PySpark 4.0.1.
- CPU Polars 1.33.1; GPU Polars 1.31.0 and cudf-polars 25.8.0.

Measurement timestamps were not saved, so historical `recorded_at` remains null. The publication
revision and maintainer confirmation are retained in `provenance`. Original timings, failures,
and even the old eager/streaming and duplicate query-label mistakes are preserved. Historical
Spark `Init` strings were split into query and total seconds.

The original README described a 12-core Ryzen 9900X, 32 GB RAM plus 32 GB swap, and a 16 GB NVIDIA
5070 Ti. That is documented historical hardware, not per-record runtime telemetry. Full-size
measurements must be rerun before claiming a speedup from the new dependency versions or fixes.
