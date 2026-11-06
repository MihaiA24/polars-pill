"""Independent, untimed SQL validation; DuckDB is imported only in worker processes."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REFERENCE = "duckdb-sql-v1"
WINDOW_START = "2019-10-01T00:00:00"
WINDOW_END = "2019-10-02T00:00:00"
FLOAT_TOLERANCES = {"float32": {"rtol": 1e-4, "atol": 1e-5}, "float64": {"rtol": 1e-9, "atol": 1e-9}}


def _outcome(status, reason=None, **details):
    return {"validation": {"status": status, "reference": REFERENCE, "reason": reason, **details}}


class ResultValidator:
    """Keep reference data on disk for one batch, never in the measured interpreter."""

    def __init__(self, input_paths):
        self.input_paths = [os.fspath(path) for path in input_paths]
        self._temporary = None

    def validate(self, record, output_path):
        dataset, query = record.get("dataset"), record.get("query")
        if not self.input_paths:
            return _outcome("unchecked", "No input paths supplied")
        if dataset in ("nyc-green", "nyc-yellow") and query in ("simple", "complex", "filtered", "date-window"):
            workload = query
        elif dataset == self.input_paths[0] and query == "simple":
            workload = "ecommerce"
            if record.get("input_format") not in ("csv", "parquet"):
                return _outcome("unchecked", "Primary input format not supplied")
        else:
            return _outcome("unchecked", "Unsupported synthetic workload")
        if output_path is None:
            return _outcome("error", "No output path supplied")
        try:
            if self._temporary is None:
                self._temporary = tempfile.TemporaryDirectory(prefix="benchmark-reference-")
            request = {
                "workload": workload,
                "inputs": self.input_paths,
                "output": os.fspath(output_path),
                "cache": self._temporary.name,
                "input_format": record.get("input_format"),
            }
            completed = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--worker"],
                input=json.dumps(request),
                capture_output=True,
                text=True,
                check=True,
            )
            return json.loads(completed.stdout)
        except (OSError, ValueError, subprocess.SubprocessError) as exception:
            reason = f"{type(exception).__name__}: {exception}"
            if isinstance(exception, subprocess.CalledProcessError) and exception.stderr:
                reason += f"; {exception.stderr.strip()}"
            return _outcome("error", reason)

    def close(self):
        if self._temporary is not None:
            self._temporary.cleanup()
            self._temporary = None


def _literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def _identifier(value):
    return '"' + value.replace('"', '""') + '"'


def _parquet_source(path):
    root = Path(path)
    files = sorted(root.rglob("*.parquet")) if root.is_dir() else [root]
    if not files:
        raise FileNotFoundError(f"No Parquet output files in {path}")
    return "read_parquet([" + ",".join(_literal(file) for file in files) + "])"


def _reference_sql(request, connection):
    workload, inputs = request["workload"], request["inputs"]
    if workload == "ecommerce":
        if request["input_format"] == "parquet":
            source = _parquet_source(inputs[0])
        else:
            source = f"""read_csv({_literal(inputs[0])}, header=true, columns={{
                'event_time':'VARCHAR', 'event_type':'VARCHAR', 'product_id':'INTEGER',
                'category_id':'BIGINT', 'category_code':'VARCHAR', 'brand':'VARCHAR',
                'price':'FLOAT', 'user_id':'INTEGER', 'user_session':'VARCHAR'
            }})"""
        return (
            (
                f"SELECT product_id, median(CAST(price AS DOUBLE)) AS sum_price FROM {source} "
                "GROUP BY product_id HAVING median(CAST(price AS DOUBLE)) > 500"
            ),
            ["product_id"],
            ["sum_price"],
            None,
        )
    trips = _parquet_source(inputs[0])
    selectivity = None
    if workload in ("filtered", "date-window"):
        predicate = "trip_distance > 0 AND fare_amount > 0"
        if workload == "date-window":
            predicate += (
                f" AND tpep_pickup_datetime >= TIMESTAMP {_literal(WINDOW_START)}"
                f" AND tpep_pickup_datetime < TIMESTAMP {_literal(WINDOW_END)}"
            )
        # parquet_file_metadata reads footers, not input rows; qualifying counts are actual SQL observations.
        input_rows = connection.execute(
            "SELECT coalesce(sum(num_rows), 0) FROM parquet_file_metadata(?)", [inputs[0]]
        ).fetchone()[0]
        selectivity = {"input_rows": input_rows}
        if workload == "date-window":
            selectivity.update(window_start=WINDOW_START, window_end=WINDOW_END)
        source = f"SELECT * FROM {trips} WHERE {predicate}"
        keys = ["PULocationID"]
    else:
        if len(inputs) < 2:
            raise ValueError("NYC joined workloads require a zone lookup input")
        zones = f"""read_csv({_literal(inputs[1])}, header=true, columns={{
            'LocationID':'INTEGER', 'Borough':'VARCHAR', 'Zone':'VARCHAR', 'service_zone':'VARCHAR'
        }})"""
        source = f"""SELECT t.trip_distance, t.fare_amount, t.tip_amount,
            d.Zone AS DO_Zone, d.Borough AS DO_Borough, p.Borough AS PU_Borough
            FROM {trips} t
            INNER JOIN {zones} p ON t.PULocationID = p.LocationID
            INNER JOIN {zones} d ON t.DOLocationID = d.LocationID"""
        keys = ["trip_distance"]
        if workload == "complex":
            keys += ["DO_Zone", "DO_Borough", "PU_Borough"]
    grouping = ", ".join(_identifier(key) for key in keys)
    sql = f"""SELECT {grouping}, count(*) AS trip_count,
        sum(CAST(fare_amount AS DOUBLE)) AS total_revenue,
        avg(CAST(fare_amount AS DOUBLE)) AS avg_fare,
        avg(CAST(trip_distance AS DOUBLE)) AS avg_distance,
        avg(CAST(tip_amount AS DOUBLE)) AS avg_tip
        FROM ({source}) GROUP BY {grouping}"""
    return sql, keys, ["total_revenue", "avg_fare", "avg_distance", "avg_tip"], selectivity


def _numeric_type(type_name):
    return type_name in {
        "TINYINT",
        "SMALLINT",
        "INTEGER",
        "BIGINT",
        "HUGEINT",
        "UTINYINT",
        "USMALLINT",
        "UINTEGER",
        "UBIGINT",
        "UHUGEINT",
        "FLOAT",
        "DOUBLE",
    } or type_name.startswith("DECIMAL(")


def _integer_type(type_name):
    return _numeric_type(type_name) and type_name not in ("FLOAT", "DOUBLE") and not type_name.startswith("DECIMAL(")


def _compare(connection, keys, floats):
    expected = {row[0]: row[1] for row in connection.execute("DESCRIBE expected").fetchall()}
    observed = {row[0]: row[1] for row in connection.execute("DESCRIBE observed").fetchall()}
    stats = {
        "expected_rows": connection.execute("SELECT count(*) FROM expected").fetchone()[0],
        "observed_rows": connection.execute("SELECT count(*) FROM observed").fetchone()[0],
        "grouping_keys": keys,
        "float_tolerance": {
            "policy": "output-native-precision; exact grouping keys/counts; nulls and nonfinite values match only like-for-like",
            **FLOAT_TOLERANCES,
            "columns": {name: "float32" if observed.get(name) == "FLOAT" else "float64" for name in floats},
        },
    }
    if set(expected) != set(observed):
        return _outcome("mismatch", "Output columns differ from reference", **stats)
    if stats["expected_rows"] != stats["observed_rows"]:
        return _outcome("mismatch", "Output row count differs from reference", **stats)
    for name, reference_type in expected.items():
        actual_type = observed[name]
        if _numeric_type(reference_type) != _numeric_type(actual_type) or (
            not _numeric_type(reference_type) and reference_type != actual_type
        ):
            return _outcome("mismatch", f"Incompatible output type for {name}: {actual_type}", **stats)
    if "trip_count" in observed and not _integer_type(observed["trip_count"]):
        return _outcome("mismatch", "trip_count must have an integer representation", **stats)
    grouping = ", ".join(_identifier(key) for key in keys)
    for table, prefix in (("expected", "expected"), ("observed", "observed")):
        distinct = connection.execute(
            f"SELECT count(*) FROM (SELECT {grouping} FROM {table} GROUP BY {grouping})"
        ).fetchone()[0]
        stats[f"{prefix}_keys"] = distinct
        stats[f"{prefix}_duplicate_rows"] = stats[f"{prefix}_rows"] - distinct
    joins = []
    for key in keys:
        a, r = f"a.{_identifier(key)}", f"r.{_identifier(key)}"
        if _integer_type(expected[key]) and _integer_type(observed[key]):
            a, r = f"CAST({a} AS HUGEINT)", f"CAST({r} AS HUGEINT)"
        elif expected[key] in ("FLOAT", "DOUBLE") and observed[key] in ("FLOAT", "DOUBLE"):
            a, r = f"CAST({a} AS DOUBLE)", f"CAST({r} AS DOUBLE)"
        elif expected[key] != observed[key]:
            return _outcome("mismatch", f"Incompatible grouping key type for {key}", **stats)
        joins.append(f"{a} IS NOT DISTINCT FROM {r}")
    join = " AND ".join(joins)
    stats["missing_keys"] = connection.execute(
        f"SELECT count(*) FROM expected r WHERE NOT EXISTS (SELECT 1 FROM observed a WHERE {join})"
    ).fetchone()[0]
    stats["unexpected_keys"] = connection.execute(
        f"SELECT count(*) FROM observed a WHERE NOT EXISTS (SELECT 1 FROM expected r WHERE {join})"
    ).fetchone()[0]
    if any(
        stats[name]
        for name in ("missing_keys", "unexpected_keys", "observed_duplicate_rows", "expected_duplicate_rows")
    ):
        return _outcome("mismatch", "Grouping keys or row multiplicity differ", **stats)
    comparisons = []
    for name in floats:
        a, r = f"a.{_identifier(name)}", f"r.{_identifier(name)}"
        tolerance = FLOAT_TOLERANCES["float32" if observed[name] == "FLOAT" else "float64"]
        # IS NOT DISTINCT FROM covers equal nulls, NaNs and infinities. The second arm only admits finite values.
        comparisons.append(
            f"({a} IS NOT DISTINCT FROM {r} OR coalesce((isfinite({a}) AND isfinite({r}) "
            f"AND abs(CAST({a} AS DOUBLE) - {r}) <= {tolerance['atol']} + {tolerance['rtol']} * abs({r})), false))"
        )
    if "trip_count" in observed:
        comparisons.append('CAST(a."trip_count" AS HUGEINT) IS NOT DISTINCT FROM CAST(r."trip_count" AS HUGEINT)')
    equal = " AND ".join(comparisons)
    stats["value_mismatches"] = connection.execute(
        f"SELECT count(*) FROM observed a INNER JOIN expected r ON {join} WHERE NOT ({equal})"
    ).fetchone()[0]
    return _outcome(
        "mismatch" if stats["value_mismatches"] else "passed",
        "Aggregate values differ" if stats["value_mismatches"] else None,
        **stats,
    )


def _validate_worker(request):
    import duckdb

    cache = Path(request["cache"])
    workload = request["workload"]
    reference = cache / f"{workload}.parquet"
    metadata_path = cache / f"{workload}.json"
    with duckdb.connect(
        config={"threads": 2, "memory_limit": "512MB", "temp_directory": str(cache / "spill")}
    ) as connection:
        if not reference.exists():
            sql, keys, floats, selectivity = _reference_sql(request, connection)
            connection.execute(f"COPY ({sql}) TO {_literal(reference)} (FORMAT PARQUET)")
            if selectivity is not None:
                matched_rows = connection.execute(
                    "SELECT coalesce(sum(trip_count), 0) FROM read_parquet(?)", [str(reference)]
                ).fetchone()[0]
                selectivity.update(
                    matched_rows=matched_rows,
                    fraction=matched_rows / selectivity["input_rows"] if selectivity["input_rows"] else None,
                )
            metadata_path.write_text(json.dumps({"keys": keys, "floats": floats, "selectivity": selectivity}))
        metadata = json.loads(metadata_path.read_text())
        try:
            connection.execute(f"CREATE VIEW expected AS SELECT * FROM {_parquet_source(reference)}")
            connection.execute(f"CREATE VIEW observed AS SELECT * FROM {_parquet_source(request['output'])}")
            result = _compare(connection, metadata["keys"], metadata["floats"])
        except (OSError, ValueError, duckdb.Error) as exception:
            result = _outcome("error", f"{type(exception).__name__}: {exception}")
        if metadata["selectivity"] is not None:
            result["selectivity"] = metadata["selectivity"]
        return result


if __name__ == "__main__":
    from duckdb import Error as DuckDBError

    try:
        result = _validate_worker(json.load(sys.stdin))
    except (OSError, ValueError, TypeError, KeyError, DuckDBError) as exception:
        result = _outcome("error", f"{type(exception).__name__}: {exception}")
    print(json.dumps(result, allow_nan=False))
