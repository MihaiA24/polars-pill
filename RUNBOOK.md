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
`BENCHMARKS.html`. Setup failures abort; a failed case records its error and exits nonzero,
while the matrix continues with later cases.

Each configuration uses one process: one measured **cold** attempt, one unrecorded warm-up,
then five measured **warm** attempts. A failure stops further attempts for that configuration;
failed warm-ups are recorded too. Override the defaults for the matrix:

```shell
BENCHMARK_WARMUPS=0 BENCHMARK_REPETITIONS=3 ./run_benchmark.sh
```

Individual CLIs accept `--warmups N` (≥0) and `--repetitions N` (≥1).
Missing or blank e-commerce `--file_path` arguments exit with usage status 2 without recording.

- Eager Polars is in-memory. Lazy CSV/Parquet runs select in-memory and streaming separately.
- NYC CPU engines and GPU executors are explicit. The CLI defaults to `--engine in-memory`;
  eager + streaming is rejected. Polars 2's streaming default does not change these selections.
- GPU queries use `raise_on_fail=True`: unsupported work is an error, not an unnoticed CPU fallback.
  In-memory runs can exhaust RAM/VRAM on yellow; failures remain part of the results.
- Every library must perform the same work. Both NYC queries retain both zone joins, even when
  joined columns are unused: inner joins can remove rows. E-commerce price inputs use Float32.
- All timed sinks request Snappy; pandas omits its index. Spark coalesces only the small
  e-commerce aggregate to one writer, not NYC results.
- Native aggregate precision is retained: Float32 inputs do not imply identical accumulator
  or output types. The recorded output schema exposes those differences.
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

`benchmarks.jsonl` is append-only: each measured attempt records library/backend versions,
phase, batch, repetition counts, query/total seconds and any error. Failed attempts have
null durations, never zero-time bars; a killed process may exit before recording.

- Query time covers read/compute/write, including engine first-use work when it occurs there.
  Cold totals add library/session startup, excluding interpreter launch; warm totals cover
  only that attempt. Metadata probes and JSON serialization are outside these timers.
- “Cold” means a fresh process, not a flushed filesystem cache. The cache policy is recorded.
- Provenance includes source revision/dirty status, input paths/sizes/mtimes (not content hashes),
  CPU/thread/OS limits, and Spark's configured memory plus actual JVM heap.
- Output Parquet footers supply actual file counts, rows, schema and codecs. A GPU fixture
  produced mixed Snappy/uncompressed chunks despite requesting Snappy; metadata preserves
  actual encoding rather than assuming every chunk is compressed. Probe errors are explicit.

Regenerate the report with development dependencies in your selected environment:

```shell
.venv/bin/python plot_benchmarks.py
# Optional paths:
.venv/bin/python plot_benchmarks.py --input benchmarks.jsonl --output BENCHMARKS.html
```

The standalone HTML separates cold, warm and legacy protocol results. Tables show successful/
expected samples, median and min–max within the same batch/configuration. Charts compare
versions side by side with range whiskers; failed/incomplete groups have no bar.
Details retain metadata and individual attempts; raw measurements stay in JSONL.

The first 28 records originate from
[`00aa8e9`](https://github.com/MihaiA24/polars-pill/commit/00aa8e90e4324f9f8469dcd0e4061617bfdc0b0f);
their pinned versions are confirmed and timestamps unknown. Three proven eager-engine
label mistakes are corrected with `original_engine` provenance; ambiguous query labels remain.
Records without phase/batch metadata remain separate legacy attempts, not new warm samples.
The original hardware description was Ryzen 9900X, 32 GB RAM + 32 GB swap and RTX 5070 Ti 16 GB;
that full inventory is not captured per record.

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

Root checks use temporary fixtures, not production datasets or GPUs. Java 21 is installed
in CI so Spark coverage cannot silently skip; local Spark cases skip if Java is absent:

```shell
.venv/bin/python -m unittest discover -s tests -v
```

The [benchmark CI workflow](.github/workflows/benchmark_checks.yml) uses Python 3.12, the
CPU group and lightweight `checks` dependencies (Matplotlib/Ruff, without notebooks).
It consumes `uv.lock` with `--frozen --no-install-package polars-sha` because these tests
do not use the locally built plugin. This deliberately skips local-wheel metadata/freshness
checks; normal development syncs still build the wheel and use `--locked`.
Root and plugin checks use the same pinned Ruff version.

The [plugin workflow](.github/workflows/publish_to_pypi.yml) separately builds native wheels,
runs read-only formatting/lint/type checks once, and tests Python 3.10–3.15 compatibility.
Use [plugin development commands](polars_sha/README.md#development) to reproduce those checks.
Actions are SHA-pinned to verified releases; stale PR runs are cancelled without interrupting
tag publication. Hosted CI does not run full-data or GPU performance benchmarks.

Check the rebuilt plugin on both supported Polars versions (replace `2.1.0` with `1.44.2`):

```shell
uv run --no-project --python .venv/bin/python --with pytest --with polars==2.1.0 \
  --with ./polars_sha/target/wheels/polars_sha-0.1.0-cp39-abi3-manylinux_2_34_x86_64.whl \
  python -I -m pytest polars_sha/tests -q
```

