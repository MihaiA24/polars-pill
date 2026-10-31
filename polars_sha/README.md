# Plugin SHA hash

Minimal polars plugin for hash

This hash function for this demo are taken from polars-hash custom plugin that is more advanced polars plugin:
https://github.com/ion-elgreco/polars-hash/

## Development

Run from this directory with Rust and Python 3.11+ installed:

```sh
make venv          # or: make venv-uv (requires uv)
make install       # build and install the plugin into this directory's .venv
make test
make build-wheel   # writes target/wheels/
```

Both environment targets install development tools from `requirements.txt`; `make venv-uv`
does not use `uv sync`. The wheel's only runtime dependency is Polars. Python 3.10 remains
supported with Polars 1.x; Polars 2.1 requires Python 3.11+.