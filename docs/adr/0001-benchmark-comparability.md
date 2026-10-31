# Every library in the benchmark runs identical work

The benchmark table exists to compare execution engines, so each Run must perform the same work in
every library: the NYC queries join the zone lookup twice even when the aggregation reads none of the
joined columns, because `pyspark_evaluation.py` does the same joins. Dropping those joins from the
polars path alone would produce a faster polars number for a reason that has nothing to do with
polars.

## Consequences

- The "simple" NYC query keeps two joins it does not need. This is deliberate, not an oversight — see
  the `explain()` cell in `Polars_API.ipynb`, which shows projection pushdown removing the unused
  zone columns while the joins remain (an inner join can still remove rows).
- Any optimization applied to one library must be applied to the others, or the table has to be
  re-measured end to end.
- Published numbers stay tied to the version that produced them. The current table was measured on
  polars 1.32.3 and was not re-measured during the 1.42.1, 2.0 or 2.1 upgrades, so it is a historical
  record, not a description of the current code. Since [0003](0003-polars-2-on-cpu-gpu-held-at-1.42.1.md),
  CPU and GPU rows come from different polars versions.
