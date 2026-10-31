import json
from datetime import UTC, datetime
from pathlib import Path


def save_execution_time(
    library,
    duration,
    cpu_gpu,
    engine,
    dataset,
    execution_query,
    *,
    version,
    total_duration=None,
    error=None,
    backend_version=None,
):
    """Append one measured execution; failed runs have no numeric duration."""
    record = {
        "recorded_at": datetime.now(UTC).isoformat(),
        "library": library,
        "version": version,
        "backend_version": backend_version,
        "duration_seconds": duration,
        "total_seconds": total_duration,
        "device": cpu_gpu,
        "engine": engine,
        "dataset": dataset,
        "query": execution_query.lower(),
        "error": error,
    }
    line = json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n"
    with Path("benchmarks.jsonl").open("a", encoding="utf-8") as output:
        output.write(line)
