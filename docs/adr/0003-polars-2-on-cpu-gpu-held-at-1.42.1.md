# polars 2 on the CPU group; the GPU group stays on 1.42.1

Supersedes [0002](0002-polars-pinned-to-the-gpu-engine-ceiling.md).

polars 2.0.0 (2026-10-06) is a major release: lazy queries default to the streaming engine,
`LazyFrame.profile` is gone and the 1.x deprecations are removed. No GPU engine can run it.
`cudf-polars-cu12` 26.8.1, the newest release, requires `polars>=1.35,<1.43`; the 26.10 and 26.12
nightlies require `<1.45`. Forcing 26.8.1 onto polars 2.0.0 fails before any query runs: importing
cudf-polars raises `AttributeError: module '_ir_nodes' has no attribute 'ExtContext'`, and its IR
check would reject the plan anyway (it refuses IR versions ≥ 14.4; polars 2.0.0 exposes 15.2,
1.42.1 exposes 14.3). Keeping 0002's single version would hold every CPU demo on 1.x until RAPIDS
ships polars 2 support, which not even the 26.12 nightlies have.

`cpu_polars` is pinned to `polars==2.0.0`; `gpu_polars` stays on `polars[gpu]==1.42.1` plus
`cudf-polars-cu12>=26.8.1`.

## Considered options

- **Split versions (chosen).** CPU scripts, `Polars_API.ipynb`, `Polars_Plugins.ipynb` and the CPU
  benchmark rows run on 2.0.0; the GPU notebooks and GPU rows run on 1.42.1. Code shared by both
  groups — `polars_evaluation.py` and the plugin wheel — has to work on both versions, and was
  verified on both.
- **Everything on 1.42.1 (0002).** Keeps the table on one version, but pins the CPU half to a release
  line polars has moved past, for as long as cudf-polars lags.
- **Everything on 2.0.0, GPU dropped.** Deletes three notebooks and half the benchmark matrix.
- **Override cudf-polars' upper bound.** Installs, but every `GPUEngine` collect raises the import
  error above, with or without `raise_on_fail`, so every GPU row would record an error.

## Consequences

- A regenerated benchmark table mixes versions: every CPU row is polars 2.0.0, every GPU row polars
  1.42.1. The CPU/GPU column identifies which; a CPU-versus-GPU comparison now also compares two
  polars versions. The work is still identical across libraries ([0001](0001-benchmark-comparability.md)).
- `run_benchmark.sh` changes the polars version at the group swap, not only the engine.
- One plugin wheel serves both groups. It is compiled against the polars Rust crates 0.55.2
  (pyo3-polars 0.28); no Rust crates for polars 2 have been published, so there is nothing newer to
  build against. Any rebuild has to be checked on both 1.42.1 and 2.0.x.
- `LazyFrame.profile` cells stay in the GPU notebooks, which run on 1.42.1, where cudf-polars
  supports profiling on the in-memory executor.
- Re-merge when a cudf-polars release declares support for polars 2.x: move `gpu_polars` to the
  `cpu_polars` pin, drop the profile cells, check the `GPUEngine` options against that release, and
  supersede this record.
