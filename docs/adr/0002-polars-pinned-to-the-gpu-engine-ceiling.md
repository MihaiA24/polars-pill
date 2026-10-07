# polars is pinned to the newest version the GPU engine supports, not the newest release

**Superseded by [0003](0003-polars-2-on-cpu-gpu-held-at-1.42.1.md)** when polars 2.0 shipped without
GPU support: the CPU group moved to 2.0.0 and only the GPU group stays on 1.42.1.

polars 1.44.2 is current, but no cudf-polars build supports polars ≥ 1.43 — `cudf-polars-cu12`
26.8.1 requires `polars>=1.35,<1.43`. Since three of the five notebooks and half of the benchmark
matrix are GPU demos, both dependency groups are pinned to `polars==1.42.1`: the GPU engine sets the
ceiling for the whole repository.

## Considered options

- **One version everywhere (chosen).** `run_benchmark.sh` syncs `cpu_polars`, runs, then syncs
  `gpu_polars` and runs again, writing CPU and GPU rows into a single table. Different polars
  versions across that swap would contaminate the only comparison the table exists to make.
- **CPU on 1.44.2, GPU on 1.42.1.** Expressible — the two groups are already declared conflicting —
  and each group would be maximal, but it buys nothing the repo uses and costs the table's internal
  consistency.

## Consequences

- `cudf-polars-cu12>=26.8.1` is declared explicitly in `gpu_polars`. polars' own `gpu` extra is
  unversioned, so with polars pinned the resolver walks back to the `24.8.0a281` placeholder package
  and `uv sync` fails building a stub `cudf-cu12` sdist.
- Raising the polars pin requires checking the cudf-polars constraint first, and rebuilding the Rust
  plugin, which is compiled against the polars Rust crates (currently 0.55.2 via pyo3-polars 0.28).
- Features and deprecations from 1.43/1.44 do not apply yet. Where the repo already had code those
  releases will affect — `LazyFrame.profile`, `show_graph(plan_stage=…)` — it was migrated anyway, so
  the next bump is not blocked on them.
