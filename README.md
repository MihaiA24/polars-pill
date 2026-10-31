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
For Spark 4.2, Java 17 or 21 needs to be installed:
```shell
    brew install temurin@17 # Open JDK 17 Temurin for MacOs via Homebrew
    sudo apt install openjdk-17-jdk # Open JDK 17 for Debian-based Linux
```

## Benchmarks

These benchmarks are results from running them on a 12-core AMD Ryzen 9900X, 32GB RAM (32 GB SWAP) and a 16GB NVIDIA 5070Ti.

If you have less than 32GB RAM, yellow trip data may not work due to RAM requirements or take a long amount of time.

The table below is **historical**, measured on polars 1.32.3; its timings and old engine labels
have not been regenerated. The current runner uses CPU polars 2.1.0 and GPU polars 1.44.2 /
RAPIDS 26.10.2, which still does not support polars 2.x
([ADR 0003](docs/adr/0003-polars-2-on-cpu-gpu-held-at-1.42.1.md)).
Regenerate e-commerce Parquet from CSV before new comparisons: the schema now preserves Float64
prices, and old Float32 files cannot recover the lost precision.


| Library          |           Duration (s) | CPU/GPU  | Engine       | Dataset                   | Query        |
|------------------|------------------------|----------|--------------|---------------------------|--------------| 
| Pandas           |                  9.714 | CPU      | eager        | data/2019-Oct-20M.csv     | Simple       |
| Polars eager     |                  0.798 | CPU      | streaming    | data/2019-Oct-20M.csv     | Simple       |
| Polars eager     |                  1.963 | CPU      | streaming    | data/2019-Oct.csv         | Simple       |
| Polars eager     |                  0.823 | CPU      | streaming    | data/2019-Oct.parquet     | Simple       |
| Polars lazy      |                  0.694 | CPU      | streaming    | data/2019-Oct.csv         | Simple       |
| Polars lazy      |                  0.195 | CPU      | streaming    | data/2019-Oct.parquet     | Simple       |
| PySpark          |    6.214 (Init: 8.209) | CPU      | lazy         | data/2019-Oct.csv         | Simple       |
| PySpark          |    4.432 (Init: 6.145) | CPU      | lazy         | data/2019-Oct.parquet     | Simple       |
| Polars           |                  1.369 | CPU      | in-memory    | nyc-green                 | simple       |
| Polars           |                  4.516 | CPU      | in-memory    | nyc-green                 | complex      |
| Polars           |                  0.373 | CPU      | streaming    | nyc-green                 | simple       |
| Polars           |                  2.076 | CPU      | streaming    | nyc-green                 | complex      |
| PySpark          |    3.243 (Init: 5.198) | CPU      | lazy         | nyc-green                 | simple       |
| PySpark          |    7.915 (Init: 9.546) | CPU      | lazy         | nyc-green                 | complex      |
| Polars           |                 79.529 | CPU      | in-memory    | nyc-yellow                | simple       |
| Polars           |   ***(Crashed process) | CPU      | in-memory    | nyc-yellow                | simple       |
| Polars           |                  3.820 | CPU      | streaming    | nyc-yellow                | simple       |
| Polars           |                 64.270 | CPU      | streaming    | nyc-yellow                | complex      |
| PySpark          |   9.533 (Init: 11.589) | CPU      | lazy         | nyc-yellow                | simple       |
| PySpark          |  33.131 (Init: 35.056) | CPU      | lazy         | nyc-yellow                | complex      |
| Polars           |                  0.869 | GPU      | in-memory    | nyc-green                 | simple       |
| Polars           |                  0.672 | GPU      | in-memory    | nyc-green                 | complex      |
| Polars           |                  0.592 | GPU      | streaming    | nyc-green                 | simple       |
| Polars           |                  0.787 | GPU      | streaming    | nyc-green                 | complex      |
| Polars           |         Error (memory) | GPU      | in-memory    | nyc-yellow                | simple       |
| Polars           |         Error (memory) | GPU      | in-memory    | nyc-yellow                | complex      |
| Polars           |                  4.983 | GPU      | streaming    | nyc-yellow                | simple       |
| Polars           |                  6.212 | GPU      | streaming    | nyc-yellow                | complex      |

