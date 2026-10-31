# polars-pill
Polars pill NTER


## Environment setup

Environment of the root project is set with uv [Docs](https://docs.astral.sh/uv/)

Install uv running:
```shell
  # On Mac and Linux
  curl -LsSf https://astral.sh/uv/install.sh | sh 

  # Windows
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Build the plugin **before** syncing: the root project depends on its local wheel.

```shell
make -C polars_sha venv
make -C polars_sha build-wheel
uv lock --upgrade-package polars-sha
uv sync --locked --group cpu_polars
```

The configured wheel path targets Linux x86_64. If your build emits a different filename, update
`[tool.uv.sources]` in `pyproject.toml` and `pyproject_with_sha_example.toml` before locking.
Re-record the wheel hash with `uv lock --upgrade-package polars-sha` after every rebuild.

Choose one environment; syncing a group replaces the other:

```shell
uv sync --locked --group cpu_polars             # Polars 2.1.0, native Iceberg planner, dev tools
uv sync --locked --group gpu_polars             # Polars 1.44.2, RAPIDS 26.10.2, dev tools
uv sync --locked --group cpu_polars --no-dev    # CPU benchmark dependencies only
uv sync --locked --group gpu_polars --no-dev    # GPU benchmark dependencies only
```

Full procedures, regression checks, and the separate cloud-monitoring environment are in
[RUNBOOK.md](RUNBOOK.md).

## Spark setup
For Spark 4.3, Java 17 or 21 needs to be installed:
```shell
    brew install temurin@17 # Open JDK 17 Temurin for MacOs via Homebrew
    sudo apt install openjdk-17-jdk # Open JDK 17 for Debian-based Linux
```

## Benchmarks

- Append-only results: [benchmarks.jsonl](benchmarks.jsonl).
- Results tables and bar charts: [BENCHMARKS.html](BENCHMARKS.html) — open locally in a browser.
- Run the full matrix with `./run_benchmark.sh`; it records running versions and regenerates the report.

Regenerate the report without running benchmarks (Matplotlib is included in the development group):

```shell
.venv/bin/python plot_benchmarks.py
```

Both environments use pandas 3.1.0 and PySpark 4.3.0. CPU/GPU Polars remain on separate supported
versions. Historical results retain their timings and labels and use the pinned versions confirmed
for those runs. Each workload has a results table and a bar chart with a library/device legend.

See [RUNBOOK.md](RUNBOOK.md) for hardware/provenance details and rebuilding old Float32
e-commerce Parquet before a fresh comparison.

