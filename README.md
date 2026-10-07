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

Sync all packages by running: 
```shell
  uv sync --group cpu_polars -U # Install common, dev and cpu_polars packages
  # If you want to install the gpu_polars packages run:
  uv sync --group gpu_polars -U # Install common, dev and gpu_polars packages 
  # For benchmark running use:
  uv sync --group cpu_polars --no-dev -U # Avoid installing dev packages
  # Or for GPU:
  uv sync --group gpu_polars --no-dev -U # Avoid installing dev packages
```
## Polars plugin installation

To install the polars plugins:
    1. In the folder polars_sha (plugin folder) run: 
```shell
    make venv # First create the venv or make venv-uv
    make build-wheel # Make the package as wheel
```
. That will build the python wheel in path target/wheels
    2. Add the dependency in the root folder with uv as: 
```shell
    uv add polars_sha/target/wheels/name_of_wheel.whl # Change name_of_wheel.whl with the name of the wheel you just built
```

## Spark setutp
For Spark 4.0 Java 17 or 21 need to be installed:
```shell
    brew install temurin@17 # Open JDK 17 Temurin for MacOs via Homebrew
    sudo apt install openjdk-17-jdk # Open JDK 17 for Debian-based Linux
```

## Benchmarks

These benchmarks are results from running them on a 12-core AMD Ryzen 9900X, 32GB RAM (32 GB SWAP) and a 16GB NVIDIA 5070Ti.

If you have less than 32GB RAM, yellow trip data may not work due to RAM requirements or take a long amount of time.

`run_benchmark.sh` measures CPU rows on polars 2.0.0 and GPU rows on polars 1.42.1, the newest version cudf-polars supports ([ADR 0003](docs/adr/0003-polars-2-on-cpu-gpu-held-at-1.42.1.md)).


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

