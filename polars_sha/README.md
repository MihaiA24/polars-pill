# Plugin SHA hash

Minimal polars plugin for hash

This hash function for this demo are taken from polars-hash custom plugin that is more advanced polars plugin:
https://github.com/ion-elgreco/polars-hash/

The plugin is intended for local demos. CI runs checks only: no PyPI publishing or uploaded
release artifacts. Build and install it locally with the development commands below.

## Development

Run from this directory with Rust and Python 3.11+ installed:

```sh
make venv          # or: make venv-uv (requires uv)
RUSTFLAGS="-Dwarnings" make pre-commit  # read-only CI formatting, lint and typing
make install       # build and install the plugin into this directory's .venv
make test
make build-wheel   # writes target/wheels/
```

Both environment targets install development tools from `requirements.txt`; `make venv-uv`
does not use `uv sync`. The wheel's only runtime dependency is Polars. Python 3.10 remains
supported with Polars 1.x; Polars 2.1 requires Python 3.11+.

The stable Rust toolchain installs rustfmt and Clippy automatically. `make pre-commit` does
not rewrite files; use `make format` to apply formatting and Ruff fixes deliberately.
Ruff, MyPy, pytest and maturin versions are pinned in `requirements.txt`.

CI runs lint once and tests Polars 2.1 on GIL-enabled CPython 3.11–3.15, plus the Python 3.10
minimum and GPU-compatible Polars 1.x cases. Root benchmark fixtures have their own CPU-only job.