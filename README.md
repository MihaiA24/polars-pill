# polars-pill

Polars, pandas and Spark benchmark demos.

## Setup

Install [uv](https://docs.astral.sh/uv/).

Build the plugin **before** syncing: the root project depends on its local wheel.

```shell
make -C polars_sha venv
make -C polars_sha build-wheel
uv lock --upgrade-package polars-sha
uv sync --locked --group cpu_polars
```

The wheel path targets Linux x86_64. If the build emits a different filename, update
`[tool.uv.sources]` in `pyproject.toml`. Refresh its lock hash after every rebuild.

Choose one environment; syncing a group replaces the other:

```shell
uv sync --locked --group cpu_polars             # Polars 2.1.0, native Iceberg planner, dev tools
uv sync --locked --group gpu_polars             # Polars 1.44.2, RAPIDS 26.10.2, dev tools
uv sync --locked --group cpu_polars --no-dev    # CPU benchmark dependencies only
uv sync --locked --group gpu_polars --no-dev    # GPU benchmark dependencies only
```

See [RUNBOOK.md](RUNBOOK.md) for benchmark options, checks and cloud setup.

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
- Defaults: one cold attempt, one unrecorded warm-up and five measured warm attempts in the same process.
- Timed sinks request Snappy; pandas omits its index, and only Spark's small e-commerce result uses one writer.

Regenerate the report without running benchmarks (Matplotlib is included in the development group):

```shell
.venv/bin/python plot_benchmarks.py
```

Both environments use pandas 3.1.0 and PySpark 4.3.0. Each recorded run includes its library version.

E-commerce `price` inputs use Float32 across all three libraries, matching existing Parquet files;
no data regeneration is needed.

