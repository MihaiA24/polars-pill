# polars-pill

Polars, pandas and Spark benchmark demos.

## Setup

Install [uv](https://docs.astral.sh/uv/).

Choose one environment; syncing a group replaces the other:

```shell
uv sync --locked --group cpu_polars             # Polars 2.1.0, native Iceberg planner, dev tools
uv sync --locked --group gpu_polars             # Polars 1.44.2, RAPIDS 26.10.2, dev tools
uv sync --locked --group cpu_polars --no-dev    # CPU benchmark dependencies only
uv sync --locked --group gpu_polars --no-dev    # GPU benchmark dependencies only
```

The Rust plugin is optional and is not installed by the root dependency groups.
For `Polars_Plugins.ipynb`, build and install its wheel **after** syncing:

```shell
make -C polars_sha venv
make -C polars_sha build-wheel
uv pip install --python .venv/bin/python ./polars_sha/target/wheels/polars_sha-0.1.0-cp39-abi3-manylinux_2_34_x86_64.whl
```

Use the filename emitted by the build on other platforms. Repeat the wheel install after
each `uv sync`, which removes packages outside the selected dependency groups.

See [RUNBOOK.md](RUNBOOK.md) for benchmark options, CPU fixture checks and cloud setup;
see [plugin development](polars_sha/README.md#development) for read-only pre-commit checks.

## Spark setup
For Spark 4.3, Java 17 or 21 needs to be installed:
```shell
    brew install temurin@17 # Open JDK 17 Temurin for MacOs via Homebrew
    sudo apt install openjdk-17-jdk # Open JDK 17 for Debian-based Linux
```

## Benchmarks

- Append-only results: [benchmarks.jsonl](benchmarks.jsonl).
- Results tables and bar charts: [BENCHMARKS.html](BENCHMARKS.html) — open locally in a browser.
- Run the full matrix with `./run_benchmark.sh`; each configuration records cold and repeated warm measurements.
- Polars engines are explicit: eager uses in-memory; lazy runs in-memory and streaming separately.
- E-commerce and NYC repeat CPU baselines on the GPU-compatible Polars version, separating version changes from GPU acceleration.
- Defaults: one cold attempt, one unrecorded warm-up and five measured warm attempts in the same process.
- Timed sinks request Snappy; pandas omits its index, and only Spark's small e-commerce result uses one writer.
- Failed cases do not stop the matrix or report generation, but make the runner exit nonzero.

Regenerate the report without running benchmarks (Matplotlib is included in the development group):

```shell
.venv/bin/python plot_benchmarks.py
```

Both environments use pandas 3.1.1, PyArrow 26.0.1 and PySpark 4.3.0.
Each recorded run includes its library version.

E-commerce `price` inputs use Float32 across all three libraries, matching existing Parquet files;
no data regeneration is needed.

