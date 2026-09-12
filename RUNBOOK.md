# Runbook — running the benchmarks

Procedure for producing a fresh benchmark table. Vocabulary (mode / engine / executor / query /
dataset) is defined in [CONTEXT.md](CONTEXT.md); what changed in the upgrade and why is in
[CHANGELOG.md](CHANGELOG.md).

Current pin: **polars 1.42.1**, Python 3.12.9.

## 0. Prerequisites

| Requirement | Checked with | Notes |
|---|---|---|
| Python 3.12 | `uv python list` | `.python-version` selects 3.12.9 |
| Java 17 or 21 | `java -version` | PySpark 4.2; verified on OpenJDK 21 |
| Rust toolchain | `cargo --version` | only to rebuild the plugin; needs ≥ 1.83 for pyo3 0.29 |
| Datasets | `ls data/nyc-taxi` | `download_datasets.sh`, then `00_preprocess.py` |
| ~40 GB free disk | `df -h .` | outputs are overwritten each run, but `efficiency.parquet` alone is 2.4 GB on green |

## 1. Build the plugin first

The wheel referenced by `[tool.uv.sources]` must exist before any `uv sync`, and the committed one is
only valid for the polars version it was built against.

```shell
cd polars_sha && make build-wheel && cd ..
```

Produces `polars_sha/target/wheels/polars_sha-0.1.0-cp39-abi3-manylinux_2_34_x86_64.whl`. The file
name is what `pyproject.toml` points at — if maturin ever emits a different tag, update that path.

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

The script executes 33 commands in order: CPU sync → e-commerce comparisons (pandas, polars eager and
lazy, PySpark, CSV and Parquet) → NYC green → NYC yellow → GPU sync → the same NYC runs on GPU. Each
run appends one row to `benchmark.txt`; at the end `utils.append_benchmark_to_readme()` truncates
`README.md` at the benchmark header and appends the new table, then `benchmark.txt` is deleted.

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

Installs `cudf-polars-cu12 >= 26.8.1` (CUDA 12 wheels). For a CUDA 13 stack, swap the group to
`cudf-polars-cu13` — the polars `gpu` extra only ever means cu12.

- `--gpu_engine True --engine streaming` runs the **streaming executor**; its sink writes a
  **directory** (`data/out/polars_gpu_stream/`), not a single file. This is a cudf-polars rule, not a
  configuration choice.
- `--gpu_engine True --engine in-memory` runs the **in-memory executor**, which is limited to device
  memory (16 GB here) and is expected to OOM on yellow.
- `raise_on_fail=True` is set, so an unsupported operation raises instead of silently falling back to
  the CPU and recording a CPU time in a GPU row.

## 5. What changed operationally since polars 1.32.3

- **polars is capped at 1.42.1, not 1.44.2.** cudf-polars 26.8.1 requires `polars>=1.35,<1.43`.
  Raising the pin without checking that constraint breaks the GPU half of the benchmark.
- **`engine="auto"` now means streaming**, so sinks and collects without an explicit engine stream by
  default. Anything that needs the old behaviour must ask for `engine="in-memory"` explicitly.
- **GPU streaming sinks write directories** (see above).
- **Multi-GPU uses `DaskEngine`** from `cudf_polars.engine.dask`, not `GPUEngine(executor_options=…)`
  plus `dask_cuda`. Requires `cudf-polars-cu12[dask]` and more than one GPU.
- **`LazyFrame.profile()` is deprecated on the CPU engines** (polars 1.43) but remains the documented
  GPU in-memory profiling path; the notebook cells were left as they are.
- **The plugin must be rebuilt** whenever the polars pin moves — it is compiled against the polars
  Rust crates, currently 0.55.2 via pyo3-polars 0.28.

## 6. Notebooks

Notebook outputs in the repo were produced on polars 1.32.3 and were deliberately **not** cleared or
re-executed during the upgrade; the code cells are current, the stored outputs are historical. Re-run
them yourself if you want matching output, starting with a kernel restart between GPU sections — the
notebooks say where.

`Polars_GPU_Colab.ipynb` is for Colab/Kaggle only and installs its own pinned environment.
