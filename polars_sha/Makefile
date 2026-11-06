SHELL=/bin/bash

.PHONY: pre-commit format

venv:
	python3 -m venv .venv
	.venv/bin/python -m pip install -r requirements.txt

venv-uv:
	uv venv --seed .venv
	uv pip install --python .venv/bin/python -r requirements.txt

install:
	unset CONDA_PREFIX && \
	source .venv/bin/activate && maturin develop

install-release:
	unset CONDA_PREFIX && \
	source .venv/bin/activate && maturin develop --release

pre-commit:
	cargo fmt --all -- --check
	cargo clippy --all-features
	.venv/bin/python -m ruff check .
	.venv/bin/python -m ruff format . --check
	.venv/bin/mypy polars_sha tests

format:
	cargo fmt --all
	.venv/bin/python -m ruff check . --fix
	.venv/bin/python -m ruff format .

test:
	.venv/bin/python -m pytest tests

run: install
	source .venv/bin/activate && python run.py

run-release: install-release
	source .venv/bin/activate && python run.py

build-wheel:
	source .venv/bin/activate && maturin build --release
