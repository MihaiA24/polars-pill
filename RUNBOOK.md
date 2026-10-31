# Runbook — running the benchmarks

Procedure for producing a fresh benchmark table. Vocabulary (mode / engine / executor / query /
dataset) is defined in [CONTEXT.md](CONTEXT.md); what changed in the upgrade and why is in
[CHANGELOG.md](CHANGELOG.md).

Current pins: **polars 2.1.0** with native Iceberg planning in `cpu_polars`, **polars 1.44.2** /
**cudf-polars-cu12 26.10.2** in `gpu_polars`, Python 3.12.9. RAPIDS requires `polars<1.45`, so the
groups remain separate ([ADR 0003](docs/adr/0003-polars-2-on-cpu-gpu-held-at-1.42.1.md)).

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
environment setup aborts before running queries under the wrong stack or replacing the README table.
The initial CPU sync also succeeds before an existing `benchmark.txt` is removed.

## 3. Run the full matrix

```shell
./run_benchmark.sh
```

The script runs CPU sync (polars 2.1.0) → e-commerce comparisons (pandas,
polars eager and lazy, PySpark, CSV and Parquet) → NYC green → NYC yellow → GPU sync (polars 1.44.2)
→ the same NYC runs on GPU. Each run appends one row to `benchmark.txt`; at the end
`utils.append_benchmark_to_readme()` truncates `README.md` at the benchmark header and appends the new
table, then `benchmark.txt` is deleted.

Consequences worth knowing before you start it:

- **`README.md` is rewritten.** Everything after the benchmark header line is replaced. Commit or
  stash anything you care about below that point.
- **Caught NYC failures produce an error row**, carrying the exception type rather than a duration.
  Check stderr too: an uncaught error or killed process can exit before recording its row.
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
