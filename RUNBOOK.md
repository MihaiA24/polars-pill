# Benchmark runbook

## Environment

Follow [README.md](README.md#setup) to build the local plugin and install dependencies.

- Python 3.12; Java 17 or 21 for Spark; Rust ≥1.83 to build the plugin.
- CPU: Polars 2.1.0 with native Iceberg planning. GPU: Polars 1.44.2 / cudf-polars 26.10.2.
  [RAPIDS requires Polars <1.45](https://pypi.org/pypi/cudf-polars-cu12/26.10.2/json); do not force it onto Polars 2.
- Both groups use pandas 3.1.0 and PySpark 4.3.0. Syncing one group replaces the other.
- Build the plugin before syncing and refresh its lock hash after every rebuild.
  One wheel serves both groups; verify its FFI compatibility on both versions.
- Download missing datasets with `download_datasets.sh`, then run `00_preprocess.py` for initial preparation.
  Existing prepared Float32 e-commerce Parquet can be reused unchanged.

## Run benchmarks

```shell
bash run_benchmark.sh
```

The runner uses locked dependencies, runs CPU comparisons, switches to GPU, then generates
`BENCHMARKS.html`. Environment setup failure stops the run without deleting earlier results.

- Eager Polars is in-memory. Lazy CSV/Parquet runs select in-memory and streaming separately.
- NYC CPU engines and GPU executors are explicit. The CLI defaults to `--engine in-memory`;
  eager + streaming is rejected. Polars 2's streaming default does not change these selections.
- GPU queries use `raise_on_fail=True`: unsupported work is an error, not an unnoticed CPU fallback.
  In-memory runs can exhaust RAM/VRAM on yellow; failures remain part of the results.
- Every library must perform the same work. Both NYC queries retain both zone joins, even when
  joined columns are unused: inner joins can remove rows. E-commerce price inputs use Float32.
- CPU/GPU comparisons also compare different Polars versions. Apply workload changes consistently
  across libraries rather than attributing all timing differences to the engine.

Individual runs:

```shell
.venv/bin/python polars_evaluation.py --file_path data/2019-Oct.parquet --file_type parquet --mode lazy --engine in-memory
.venv/bin/python polars_evaluation.py --file_path data/2019-Oct.parquet --file_type parquet --mode lazy --engine streaming
.venv/bin/python polars_evaluation.py --dataset_type nyc-green --engine streaming --execution_query complex
.venv/bin/python polars_evaluation.py --dataset_type nyc-yellow --engine streaming --execution_query simple --gpu_engine True
```

Select the GPU group before a standalone GPU run. Use `--no-dev` for benchmark-only installs;
the full runner adds development dependencies after timing to generate the report.

## Results and charts

`benchmarks.jsonl` is append-only. Each record includes the runtime version, UTC timestamp,
input/query/execution labels, query seconds and any error. GPU records include the backend version.
Spark's total includes session initialization plus the query. Failed attempts have a null duration,
not a zero-time success; a killed process may exit before it can record a result.

To regenerate the report, include the development group in your selected environment:

```shell
.venv/bin/python plot_benchmarks.py
# Optional paths:
.venv/bin/python plot_benchmarks.py --input benchmarks.jsonl --output BENCHMARKS.html
```

Open the HTML locally; it needs no network or Python packages to view. Each workload has a table
and a Matplotlib bar chart with a library/device legend. Row numbers link bars to attempts;
charts use separate zero-based scales, omit failures and do not average repeated runs.

The first 28 records preserve the confirmed pins and original labels from
[`00aa8e9`](https://github.com/MihaiA24/polars-pill/commit/00aa8e90e4324f9f8469dcd0e4061617bfdc0b0f).
Their timestamps are unknown, and historical execution/query label mistakes remain unchanged.
The original hardware description was Ryzen 9900X, 32 GB RAM + 32 GB swap and RTX 5070 Ti 16 GB;
hardware is not captured per record.

## Notebooks and cloud

- `Polars_API.ipynb` and `Polars_Plugins.ipynb` use the CPU group; `Polars_GPU_*` use the GPU group.
  Stored notebook outputs are historical. Graph rendering needs Graphviz `dot`.
- GPU profiling is available only on the 1.x in-memory executor. Stop `DefaultSingletonEngine`
  before an explicit `DaskEngine`; distributed sinks require directories. After an OOM, rerun
  the setup cells identified by the notebook. Colab installs its own pinned environment.
- Spark 4.3 warns about pandas ≥3 interop. The benchmarks use native Spark DataFrames and measure
  pandas separately; they do not use Spark↔pandas conversion APIs.
- Cloud monitoring uploads local-query metrics and requires authentication/default-workspace access.
  SDK 0.12 needs Polars 2.0, so keep it outside the benchmark environment:

```shell
uv venv /tmp/polars-cloud-demo
uv pip install --python /tmp/polars-cloud-demo/bin/python "polars-cloud==0.12.0"
/tmp/polars-cloud-demo/bin/python cloud_monitoring_demo.py
```

## Checks

Root checks use temporary fixtures; Spark cases skip without Java:

```shell
.venv/bin/python -m unittest discover -s tests -v
```

Check the rebuilt plugin on both supported Polars versions (replace `2.1.0` with `1.44.2`):

```shell
uv run --no-project --python .venv/bin/python --with pytest --with polars==2.1.0 \
  --with ./polars_sha/target/wheels/polars_sha-0.1.0-cp39-abi3-manylinux_2_34_x86_64.whl \
  python -m pytest polars_sha/tests -q
```
