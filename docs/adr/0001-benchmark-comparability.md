# Every library in the benchmark runs identical work

The benchmark history exists to compare execution engines, so each Run must perform the same work in
every library: the NYC queries join the zone lookup twice even when the aggregation reads none of the
joined columns, because `pyspark_evaluation.py` does the same joins. Dropping those joins from the
polars path alone would produce a faster polars number for a reason that has nothing to do with
polars.

## Consequences

- The "simple" NYC query keeps two joins it does not need. This is deliberate, not an oversight — see
  the `explain()` cell in `Polars_API.ipynb`, which shows projection pushdown removing the unused
  zone columns while the joins remain (an inner join can still remove rows).
- Any optimization applied to one library must be applied to the others, or the timings have to
  be re-measured end to end.
- Historical timings are preserved in `benchmarks.jsonl`, not rewritten by upgrades. The rows were
  introduced in `00aa8e9`; their versions are the publication-lock pins confirmed by the maintainer:
  pandas 2.3.2, Spark 4.0.1, CPU Polars 1.33.1 and GPU Polars 1.31.0 / cudf-polars 25.8.0.
  Historical measurement timestamps remain unknown.
- New runs record actual library versions and, on GPU, the backend version. CPU and GPU still use
  different Polars versions ([0003](0003-polars-2-on-cpu-gpu-held-at-1.42.1.md)).
