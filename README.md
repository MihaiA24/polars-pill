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
  uv sync -U
```
Uv automatically will create the venv and install all dependencies.

#### Polars GPU package
By default, the pyproject has the polars-gpu package installed. If you want to use the CPU version:
```shell
# remove the polars-gpu package from the pyproject.toml file.
uv remove polars
# install the polars cpu package
uv add polars
# if want to install the polars gpu package. Remove the polars package and run:
uv add "polars[gpu]"
```


## Polars plugin installation

To install the polars plugins:
    1. In the folder polars_sha (plugin folder) run: make build-wheel. That will build the python wheel in path target/wheels
    2. Add the dependency in the root folder with uv as: uv add polars_sha/target/wheels/name_of_wheel.whl


## Benchmarks

These benchmarks are results from running them on a 12-core AMD Ryzen 9900X, 32GB RAM (32 GB SWAP) and a 16GB NVIDIA 5070Ti.

If you have less than 32GB RAM, yellow trip data may not work due to RAM requirements or take a long amount of time.

| Library          |       Duration (s) | CPU/GPU  | Engine       | Dataset                   | Query        |
|------------------|--------------------|----------|--------------|---------------------------|--------------| 
| Polars eager     |              0.625 | CPU      | streaming    | data/2019-Oct-20M.csv     | Simple       |
| Polars eager     |              1.362 | CPU      | streaming    | data/2019-Oct.csv         | Simple       |

