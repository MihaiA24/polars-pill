# Benchmark runbook

## Environment

Follow [README.md](README.md#setup) to install dependencies and, optionally, the local plugin.

- Python 3.12; Java 17 or 21 for Spark; Rust is needed only to build the optional plugin.
- CPU: Polars 2.1.0 with native Iceberg planning. GPU: Polars 1.44.2 / cudf-polars 26.10.2.
  [RAPIDS requires Polars <1.45](https://pypi.org/pypi/cudf-polars-cu12/26.10.2/json); do not force it onto Polars 2.
- Both groups use DuckDB 2.0.0, pandas 3.1.1, PyArrow 26.0.1 and PySpark 4.3.0. Syncing one group replaces the other.
- The plugin notebook needs an explicit wheel install after syncing; benchmarks do not use it.
  One wheel serves both groups; verify its FFI compatibility on both versions.
- Download missing datasets with `download_datasets.sh`, then run `00_preprocess.py` for initial preparation.
  Existing prepared Float32 e-commerce Parquet can be reused unchanged.

## Run benchmarks

```shell
python3 run_benchmark.py
```

The runner uses locked dependencies, runs CPU comparisons on Polars 2.1.0, switches to
the GPU environment, then repeats e-commerce and NYC CPU baselines on Polars 1.44.2 and
runs GPU cases before generating `BENCHMARKS.html`. Setup failures abort immediately. Failed benchmark cases
do not stop later cases or report generation, but the runner exits 1 if any case failed.
A report-generation failure retains its own nonzero exit status.

The standard-library runner keeps one live dashboard on a capable terminal: current phase,
workload and exact command, operation progress and passed/failed/interrupted counts,
active/total elapsed time, and recent outcomes. Failed-operation logs retain their phase and command.
Child output is captured while updating the display.
Status colors honor `NO_COLOR`; redirected stdout and `TERM=dumb` use plain streaming output.
Force that mode to see all library output, including successful-operation warnings:

```shell
python3 run_benchmark.py --plain
```

Ctrl+C stops the active process group, including surviving descendants, and exits 130.
SIGTERM cleans up with status 143. Neither starts later cases or generates a report; already
recorded measurements remain intact. Terminal state is restored on completion, failure or interruption.
The shell runner has been replaced; `python3 run_benchmark.py --help` describes the CLI.

One invocation has a `suite_id` and start timestamp shared by the whole matrix. Each
configuration has its own `batch_id`. `BENCHMARK_SUITE_ID` can set the full-run identity;
the runner ignores inherited `BENCHMARK_BATCH_ID` values. Standalone configuration CLIs
create a single-configuration suite and still accept `BENCHMARK_BATCH_ID`.

Each configuration uses one process: one measured **cold** attempt, one unrecorded warm-up,
then five measured **warm** attempts. A failure stops further attempts for that configuration;
failed warm-ups are recorded too. Override the defaults for the matrix:

```shell
BENCHMARK_WARMUPS=0 BENCHMARK_REPETITIONS=3 python3 run_benchmark.py
```

Individual CLIs accept `--warmups N` (≥0) and `--repetitions N` (≥1).
Missing or blank e-commerce `--file_path` arguments exit with usage status 2 without recording.

- pandas reads CSV only through `--file_path`; there is no `--file_type` selector.
- Eager Polars is in-memory. Lazy CSV/Parquet runs select in-memory and streaming separately.
- NYC CPU engines and GPU executors are explicit. The CLI defaults to `--engine in-memory`;
  eager + streaming is rejected. Polars 2's streaming default does not change these selections.
- DuckDB executes native SQL with one connection reused across cold/warm attempts; its optimizer
  selects execution strategies. It is recorded as `CPU / native`, not as a Polars streaming mode.
- GPU queries use `raise_on_fail=True`: unsupported work is an error, not an unnoticed CPU fallback.
  In-memory runs can exhaust RAM/VRAM on yellow; failures remain part of the results.
- Every library must perform the same work. NYC `simple` and `complex` retain both zone joins,
  even when joined columns are unused: inner joins can remove rows. `filtered` has no joins
  and needs only the trip Parquet file. E-commerce price inputs use Float32.
- All timed sinks request Snappy; pandas omits its index. Spark coalesces only the small
  e-commerce aggregate to one writer, not NYC results.
- Native aggregate precision is retained: Float32 inputs do not imply identical accumulator
  or output types. The recorded output schema exposes those differences.
- Compare CPU 1.44.2 against GPU 1.44.2 to isolate GPU acceleration, and CPU 1.44.2 against
  CPU 2.1.0 to measure the version change. CPU 2.1.0 versus GPU 1.44.2 changes both variables.
  Apply workload changes consistently across libraries.

Individual runs:

```shell
.venv/bin/python polars_evaluation.py --file_path data/2019-Oct.parquet --file_type parquet --mode lazy --engine in-memory
.venv/bin/python polars_evaluation.py --file_path data/2019-Oct.parquet --file_type parquet --mode lazy --engine streaming
.venv/bin/python polars_evaluation.py --dataset_type nyc-green --engine streaming --execution_query complex
.venv/bin/python polars_evaluation.py --dataset_type nyc-yellow --engine streaming --execution_query simple --gpu_engine True
```

### Filtered pickup aggregates

The matrix now includes `--execution_query filtered` for both NYC datasets in Polars CPU
2.1.0, same-version CPU 1.44.2/GPU comparisons, DuckDB and Spark. Existing `simple` and
`complex` workloads are unchanged.

This query keeps trips with `trip_distance > 0 AND fare_amount > 0`, groups by `PULocationID`,
and computes trip count, total revenue, average fare, distance and tip. It sorts pickup IDs
ascending with nulls first and writes the usual Snappy Parquet output. Null distance/fare
rows fail the predicate; null tips are excluded from the tip mean, not the trip count.
Unknown and null pickup IDs remain groups because there is no zone join.

This adds a scan/filter workload with a small grouping key space, rather than another
distance-based grouping with two joins. It exercises projection, native filtering and
aggregation; it does not guarantee row-group pruning or a particular filter selectivity.
Timings still include the read, compute and write. The distinct `filtered` query identity
keeps these results separate from historical workloads, and input snapshots omit the unused
zone lookup. Native aggregate precision remains unchanged.

```shell
.venv/bin/python polars_evaluation.py --dataset_type nyc-green --engine streaming --execution_query filtered
.venv/bin/python duckdb_evaluation.py --dataset_type nyc-green --execution_query filtered
.venv/bin/python pyspark_evaluation.py --dataset_type nyc-green --execution_query filtered
```

Select the GPU group before a standalone GPU run. Use `--no-dev` for benchmark-only installs;
the full runner adds development dependencies after timing to generate the report.

### DuckDB SQL comparisons

[duckdb_evaluation.py](duckdb_evaluation.py) contains the SQL queries; no DataFrame conversion
or preloaded in-memory tables are included in its timed path:

- E-commerce reads CSV with explicit column types (`price FLOAT`, `product_id INTEGER`) or reads
  the prepared Parquet directly, groups by product, and filters `median(price) AS sum_price > 500`.
- NYC `simple` and `complex` retain pickup and dropoff inner joins to the zone lookup. Simple
  groups by trip distance; complex adds dropoff zone/borough and pickup borough. `filtered`
  instead filters positive distances/fares and groups by pickup ID without a lookup. All compute
  trip count, total revenue and fare/distance/tip means, sorted by grouping keys with nulls first.
- Native aggregate precision is retained. Each attempt writes `data/out/duckdb.parquet` with
  Snappy; a later attempt overwrites that file. The runner includes all three e-commerce inputs
  and simple/complex/filtered queries for both taxi colors, once in the CPU phase.

```shell
.venv/bin/python duckdb_evaluation.py --file_path data/2019-Oct.csv
.venv/bin/python duckdb_evaluation.py --file_path data/2019-Oct.parquet --file_type parquet
.venv/bin/python duckdb_evaluation.py --dataset_type nyc-green --execution_query complex
.venv/bin/python duckdb_evaluation.py --dataset_type nyc-yellow --execution_query simple
```

## Results and charts

`benchmarks.jsonl` is append-only: each measured attempt records library/backend versions,
suite, phase, configuration batch, repetition counts, query/total seconds, timer scopes and
any error. Failed attempts have null durations, never zero-time bars; a killed process may
exit before recording.

- Query time covers read/compute/write, including engine first-use work when it occurs there.
  Cold totals add library/session startup, excluding interpreter launch; warm totals cover
  only that attempt. Metadata probes and JSON serialization are outside these timers.
- “Cold” means a fresh process, not a flushed filesystem cache. The cache policy is recorded.
- Provenance includes source revision/dirty status, input paths/sizes/mtimes (not content hashes),
  CPU/thread/OS limits, Spark's configured memory plus actual JVM heap, and DuckDB's actual
  thread count, memory limit and spill directory. DuckDB uses its native default resource settings.
- New Linux records include a hashed host identity, CPU model and physical RAM. NVIDIA
  inventory adds GPU UUIDs, models, memory and driver versions when `nvidia-smi` is available.
  These probes run outside the timers. Failures remain metadata errors, not failed attempts.
- Output Parquet footers supply actual file counts, rows, schema and codecs. A GPU fixture
  produced mixed Snappy/uncompressed chunks despite requesting Snappy; metadata preserves
  actual encoding rather than assuming every chunk is compressed. Probe errors are explicit.

Regenerate the report with development dependencies in your selected environment:

```shell
.venv/bin/python plot_benchmarks.py
# Optional paths:
.venv/bin/python plot_benchmarks.py --input benchmarks.jsonl --output BENCHMARKS.html
```

The standalone HTML opens the latest suite by start time, not JSONL append order. Dataset,
query and phase filters hide each table and its chart together. History lists older suites
and an explicit unassigned scope for records without suite identity. Legacy attempts have
their own view. Existing records are not relabelled or rewritten.

Tables retain successful/expected samples, medians and min–max within each configuration
batch. Visible batch IDs and UTC dates distinguish repeated configurations. Full IDs,
metadata and individual attempts remain in Measurement details; raw measurements stay
in JSONL. Failed or incomplete groups have no chart bar.

Each section has a baseline selector. Speedup divides the baseline median by the candidate
median, using total seconds for cold measurements and query seconds for warm measurements.
Values above 1× mean the candidate is faster. Both results must be complete and positive,
with matching workload, phase, timer scope, cache policy, input snapshots and known hardware.
GPU comparisons also require matching GPU inventories. Unknown or different metadata,
failures and zero times leave the measurements visible with an explanation instead of a ratio.
Input snapshots compare paths, sizes and modification times, not file contents; resource
budgets remain the libraries' recorded settings rather than an enforced common limit.

The generator embeds `benchmark_report.js` in the HTML. The report needs no server,
external assets or network connection. Without JavaScript, all sections remain readable.

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
  Each GPU notebook defines its shared taxi query builder in setup and calls it inside the
  timed cells, so plan construction remains part of the timing.
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
node --check benchmark_report.js
```

The [benchmark CI workflow](.github/workflows/benchmark_checks.yml) uses Python 3.12, the
CPU group and lightweight `checks` dependencies (Matplotlib/Ruff, without notebooks).
Both Polars 2.1.0 and GPU-compatible 1.44.2 run the complete CPU fixture suite without CUDA.
Each job installs `uv.lock` with `--locked`, then selects its exact Polars runtime while
leaving the other locked dependencies unchanged. The optional plugin is installed separately.
DuckDB CLI fixtures cover Float32-sensitive medians, join filtering/multiplicity, null-first
ordering, Snappy output and failure recording in both jobs. Shared CLI fixtures also verify
`filtered` results across both Polars CPU engines, DuckDB and Spark: zero/negative/null
distance and fare exclusion, null-tip means, and null/unknown pickup groups without a zone lookup.
Root and plugin checks use the same pinned Ruff version.
CI also checks the report interaction script's syntax with Node.

The [plugin workflow](.github/workflows/publish_to_pypi.yml) builds five native wheel targets
through one platform matrix and tests seven Python/Polars pairs in a separate runtime matrix.
Read-only formatting/lint/type checks run once. Use the
[plugin development commands](polars_sha/README.md#development) to reproduce those checks.
Actions are SHA-pinned to verified releases; stale PR runs are cancelled without interrupting
tag publication. Hosted CI does not run full-data or GPU performance benchmarks.

Check the rebuilt plugin on both supported Polars versions (replace `2.1.0` with `1.44.2`):

```shell
uv run --no-project --python .venv/bin/python --with pytest --with polars==2.1.0 \
  --with ./polars_sha/target/wheels/polars_sha-0.1.0-cp39-abi3-manylinux_2_34_x86_64.whl \
  python -I -m pytest polars_sha/tests -q
```

