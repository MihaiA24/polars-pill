# Runbook — running the benchmarks

Procedure for producing a fresh benchmark table. Vocabulary (mode / engine / executor / query /
dataset) is defined in [CONTEXT.md](CONTEXT.md); what changed in the upgrade and why is in
[CHANGELOG.md](CHANGELOG.md).

Current pins: **polars 2.0.0** in `cpu_polars`, **polars 1.42.1** in `gpu_polars` (held back: no
cudf-polars release supports polars 2, see [ADR 0003](docs/adr/0003-polars-2-on-cpu-gpu-held-at-1.42.1.md)),
Python 3.12.9.

## 0. Prerequisites

| Requirement | Checked with | Notes |
|---|---|---|
| Python 3.12 | `uv python list` | `.python-version` selects 3.12.9 |
| Java 17 or 21 | `java -version` | PySpark 4.2; verified on OpenJDK 21 |
| Rust toolchain | `cargo --version` | only to rebuild the plugin; needs ≥ 1.83 for pyo3 0.29 |
| Datasets | `ls data/nyc-taxi` | `download_datasets.sh`, then `00_preprocess.py` |
| ~40 GB free disk | `df -h .` | outputs are overwritten each run, but `efficiency.parquet` alone is 2.4 GB on green |

## 1. Build the plugin first

The wheel referenced by `[tool.uv.sources]` must exist before any `uv sync`. `target/` is not
committed, so every checkout builds its own, and that one wheel is installed by both dependency
groups — it has to load on polars 1.42.1 and 2.0.0.

```shell
cd polars_sha && make build-wheel && cd ..
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
uv sync --group cpu_polars --no-dev   # benchmark runs: skip notebook/ruff/cookiecutter
uv sync --group cpu_polars            # add dev tools when working on the notebooks
```

`cpu_polars` and `gpu_polars` are declared conflicting: syncing one **uninstalls** the other. That is
also what `run_benchmark.sh` does halfway through its command list.

Note the `-U` in `run_benchmark.sh`: it ignores `uv.lock` and re-resolves. polars itself cannot drift
(it is pinned exactly), but everything else can.

## 3. Run the full matrix

```shell
./run_benchmark.sh
```

The script executes 33 commands in order: CPU sync (polars 2.0.0) → e-commerce comparisons (pandas,
polars eager and lazy, PySpark, CSV and Parquet) → NYC green → NYC yellow → GPU sync (polars 1.42.1)
→ the same NYC runs on GPU. Each run appends one row to `benchmark.txt`; at the end
`utils.append_benchmark_to_readme()` truncates `README.md` at the benchmark header and appends the new
table, then `benchmark.txt` is deleted.

Consequences worth knowing before you start it:

- **`README.md` is rewritten.** Everything after the benchmark header line is replaced. Commit or
  stash anything you care about below that point.
- **A failed run still produces a row**, carrying the exception type instead of a duration, and the
  full error goes to stderr. Check stderr before trusting a table with `Error (...)` rows in it.
- **Yellow in-memory is expected to fail or thrash** on a 32 GB machine. That is the point of the
  row.

Single runs, same arguments the script uses:

```shell
.venv/bin/python polars_evaluation.py --file_path data/2019-Oct.parquet --file_type parquet --mode lazy
.venv/bin/python polars_evaluation.py --dataset_type nyc-green --engine streaming --execution_query complex
.venv/bin/python polars_evaluation.py --dataset_type nyc-yellow --engine streaming --execution_query simple --gpu_engine True
```

## 4. GPU runs

```shell
uv sync --group gpu_polars --no-dev
```

Installs `cudf-polars-cu12 >= 26.8.1` (CUDA 12 wheels) and swaps polars 2.0.0 for 1.42.1. For a CUDA
13 stack, swap the group to `cudf-polars-cu13` — the polars `gpu` extra only ever means cu12.

- `--gpu_engine True --engine streaming` runs the **streaming executor**; its sink writes a
  **directory** (`data/out/polars_gpu_stream/`), not a single file. This is a cudf-polars rule, not a
  configuration choice.
- `--gpu_engine True --engine in-memory` runs the **in-memory executor**, which is limited to device
  memory (16 GB here) and is expected to OOM on yellow.
- `raise_on_fail=True` is set, so an unsupported operation raises instead of silently falling back to
  the CPU and recording a CPU time in a GPU row.

## 5. What changed operationally since polars 1.32.3

- **The CPU group is on polars 2.0.0, the GPU group on 1.42.1.** cudf-polars 26.8.1 requires
  `polars>=1.35,<1.43` and fails at import under polars 2.0. Raising the GPU pin without checking
  that constraint breaks the GPU half of the benchmark.
- **CPU and GPU rows come from different polars versions.** The group swap in `run_benchmark.sh`
  changes the polars version as well as the engine.
- **`engine="auto"` means streaming for lazy queries on polars 2.0** (`collect`, `collect_all`). On
  1.42.1 it still means in-memory for `collect`; `sink_*` streams on both. Eager calls
  (`read_csv`, `read_parquet`, `DataFrame` methods) run in-memory on both. The streaming engine does
  not keep row order for `group_by` or joins, so every NYC query sorts before it sinks.
- **GPU streaming sinks write directories** (see above).
- **Multi-GPU uses `DaskEngine`** from `cudf_polars.engine.dask`, not `GPUEngine(executor_options=…)`
  plus `dask_cuda`. Requires `cudf-polars-cu12[dask]` and more than one GPU.
- **`LazyFrame.profile()` was removed in polars 2.0.** It survives only on the 1.42.1 GPU stack, where
  cudf-polars supports it on the in-memory executor; the GPU notebook cells keep it until that group
  moves to 2.x.
- **One plugin wheel serves both groups.** It is compiled against the polars Rust crates 0.55.2
  (pyo3-polars 0.28); no Rust crates for polars 2 are published yet. After any rebuild, run the smoke
  check above in both groups.

## 6. Notebooks

Notebook outputs in the repo were produced on polars 1.32.3 and were deliberately **not** cleared or
re-executed during the 1.42.1 or 2.0 upgrades; the code cells are current, the stored outputs are
historical. `Polars_API.ipynb` and `Polars_Plugins.ipynb` run in `cpu_polars` (polars 2.0.0); the
`Polars_GPU_*` notebooks need `gpu_polars` (polars 1.42.1). Re-run them yourself if you want
matching output, starting with a kernel restart between GPU sections — the notebooks say where.
`Polars_API.ipynb`'s `show_graph` cells also need the graphviz `dot` binary on `PATH`.

`Polars_GPU_Colab.ipynb` is for Colab/Kaggle only and installs its own pinned environment.
