import argparse
import csv
import hashlib
import json
import logging
import os
import platform
import subprocess
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from benchmark_profiling import MemoryProfiler
from benchmark_validation import ResultValidator

# Imported before dataframe libraries so every CLI uses the same startup boundary.
PROCESS_STARTED = perf_counter()


logger = logging.getLogger(__name__)


_attempt = ContextVar("benchmark_attempt", default=None)
_THREAD_ENVIRONMENT = (
    "POLARS_MAX_THREADS",
    "RAYON_NUM_THREADS",
    "OMP_NUM_THREADS",
    "OMP_THREAD_LIMIT",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "SPARK_LOCAL_IP",
    "CUDA_VISIBLE_DEVICES",
    "POLARS_ENGINE_AFFINITY",
)


def _count_argument(minimum):
    def parse(value):
        try:
            count = int(value)
        except (TypeError, ValueError):
            raise argparse.ArgumentTypeError(f"must be an integer >= {minimum}") from None
        if count < minimum:
            raise argparse.ArgumentTypeError(f"must be an integer >= {minimum}")
        return count

    return parse


def add_benchmark_arguments(parser):
    """Add same-process measurement counts; the shell forwards environment overrides."""
    parser.add_argument("--warmups", type=_count_argument(0), default=1)
    parser.add_argument("--repetitions", type=_count_argument(1), default=5)
    parser.add_argument(
        "--profile-memory", action="store_true", default=os.environ.get("BENCHMARK_PROFILE_MEMORY") == "1"
    )


def _error(exception):
    return f"{type(exception).__name__}: {exception}"


def _source_metadata():
    metadata = {"benchmark_revision": None, "benchmark_dirty": None}
    root = Path(__file__).resolve().parent
    try:
        metadata["benchmark_revision"] = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
        ).stdout.strip()
        # Generated history, reports and dataset outputs do not change benchmark source.
        status = subprocess.run(
            [
                "git",
                "status",
                "--porcelain",
                "--untracked-files=all",
                "--",
                ".",
                ":(exclude)benchmarks.jsonl",
                ":(exclude)BENCHMARKS.html",
                ":(exclude)data",
                ":(exclude).idea",
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        metadata["benchmark_dirty"] = bool(status.stdout.strip())
    except (OSError, subprocess.SubprocessError) as exception:
        metadata["benchmark_metadata_error"] = _error(exception)
    return metadata


def _input_snapshot(paths):
    snapshots = []
    for path in paths:
        snapshot = {"path": os.fspath(path), "size_bytes": None, "mtime_ns": None}
        try:
            stat = Path(path).stat()
            snapshot.update(size_bytes=stat.st_size, mtime_ns=stat.st_mtime_ns)
        except OSError as exception:
            snapshot["metadata_error"] = _error(exception)
        snapshots.append(snapshot)
    return snapshots


def _hardware_metadata(errors):
    hardware = {"host_id": None, "cpu_model": None, "memory_bytes": None, "gpus": None}
    if platform.system() == "Linux":
        try:
            machine_id = Path("/etc/machine-id").read_text().strip()
            if not machine_id:
                raise ValueError("Empty machine identity")
            hardware["host_id"] = hashlib.sha256(machine_id.encode()).hexdigest()
        except (OSError, UnicodeError, ValueError) as exception:
            errors["hardware_host_id"] = _error(exception)
        try:
            fields = dict(line.split(":", 1) for line in Path("/proc/cpuinfo").read_text().splitlines() if ":" in line)
            fields = {key.strip(): value.strip() for key, value in fields.items()}
            hardware["cpu_model"] = fields.get("model name") or fields.get("Hardware") or None
            if hardware["cpu_model"] is None:
                raise ValueError("CPU model unavailable")
        except (OSError, UnicodeError, ValueError) as exception:
            errors["hardware_cpu_model"] = _error(exception)
    try:
        memory = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
        if memory <= 0:
            raise ValueError("Physical memory size unavailable")
        hardware["memory_bytes"] = memory
    except (AttributeError, OSError, ValueError) as exception:
        errors["hardware_memory_bytes"] = _error(exception)
    try:
        inventory = subprocess.run(
            ["nvidia-smi", "--query-gpu=uuid,name,memory.total,driver_version", "--format=csv,noheader,nounits"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
        gpus = []
        for row in csv.reader(inventory.stdout.splitlines(), skipinitialspace=True):
            gpu_uuid, name, memory, driver = (value.strip() for value in row)
            if (
                any(value in ("", "N/A", "[N/A]", "[Not Supported]") for value in (gpu_uuid, name, driver))
                or float(memory) <= 0
            ):
                raise ValueError("Incomplete GPU inventory")
            gpus.append(
                {
                    "uuid": gpu_uuid,
                    "name": name,
                    "memory_bytes": int(float(memory) * 1024 * 1024),
                    "driver_version": driver,
                }
            )
        hardware["gpus"] = sorted(gpus, key=lambda gpu: gpu["uuid"])
    except (OSError, subprocess.SubprocessError, UnicodeError, ValueError, OverflowError, csv.Error) as exception:
        errors["hardware_gpus"] = _error(exception)
    return hardware


def _resource_metadata():
    metadata = {
        "cpu_count": os.cpu_count(),
        "cpu_affinity_count": None,
        "thread_environment": {name: os.environ[name] for name in _THREAD_ENVIRONMENT if name in os.environ},
        "os": platform.system(),
        "os_release": platform.release(),
        "architecture": platform.machine(),
        "python_version": platform.python_version(),
        "os_limits": {},
    }
    errors = {}
    metadata["hardware"] = _hardware_metadata(errors)
    if hasattr(os, "sched_getaffinity"):
        try:
            metadata["cpu_affinity_count"] = len(os.sched_getaffinity(0))
        except OSError as exception:
            errors["cpu_affinity_count"] = _error(exception)
    try:
        import resource

        for name in ("RLIMIT_AS", "RLIMIT_DATA", "RLIMIT_RSS", "RLIMIT_NOFILE", "RLIMIT_NPROC", "RLIMIT_CPU"):
            if hasattr(resource, name):
                try:
                    soft, hard = resource.getrlimit(getattr(resource, name))
                    metadata["os_limits"][name] = {
                        "soft": "unlimited" if soft == resource.RLIM_INFINITY else soft,
                        "hard": "unlimited" if hard == resource.RLIM_INFINITY else hard,
                    }
                except (OSError, ValueError) as exception:
                    errors[name] = _error(exception)
    except ImportError as exception:
        errors["os_limits"] = _error(exception)
    if errors:
        metadata["metadata_errors"] = errors
    return metadata


def _output_metadata(path, succeeded):
    """Inspect only output Parquet footers, never read input or output rows."""
    output = {
        "path": os.fspath(path),
        "attempt_succeeded": succeeded,
        "file_count": None,
        "rows": None,
        "schema": None,
        "compression": None,
        "files": [],
    }
    try:
        from pyarrow import parquet

        root = Path(path)
        if not root.exists():
            raise FileNotFoundError(f"Output does not exist: {root}")
        paths = sorted(root.rglob("*.parquet")) if root.is_dir() else [root]
        if not paths:
            raise FileNotFoundError(f"No Parquet output files in {root}")
        output["file_count"] = len(paths)
        schemas = []
        codecs = set()
        rows = 0
        for file in paths:
            item = {"path": os.fspath(file), "size_bytes": None, "rows": None, "schema": None, "compression": None}
            output["files"].append(item)
            try:
                item["size_bytes"] = file.stat().st_size
                footer = parquet.read_metadata(file)
                item["rows"] = footer.num_rows
                item["schema"] = [
                    {"name": field.name, "type": str(field.type), "nullable": field.nullable}
                    for field in footer.schema.to_arrow_schema()
                ]
                item["compression"] = sorted(
                    {
                        footer.row_group(group).column(column).compression
                        for group in range(footer.num_row_groups)
                        for column in range(footer.num_columns)
                    }
                )
                rows += item["rows"]
                if item["schema"] not in schemas:
                    schemas.append(item["schema"])
                codecs.update(item["compression"])
            except Exception as exception:
                logger.debug("Output footer metadata unavailable: %s", file, exc_info=True)
                item["metadata_error"] = _error(exception)
        if any("metadata_error" in item for item in output["files"]):
            output["metadata_error"] = "Some output footers could not be read; aggregate metadata is unknown"
        else:
            output.update(rows=rows, schema=schemas[0] if len(schemas) == 1 else schemas, compression=sorted(codecs))
    except Exception as exception:
        logger.debug("Output metadata unavailable: %s", path, exc_info=True)
        output["metadata_error"] = _error(exception)
    return output


def _append_record(record):
    line = json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n"
    with Path("benchmarks.jsonl").open("a", encoding="utf-8") as output:
        output.write(line)


def run_benchmark(
    execute,
    *,
    warmups=1,
    repetitions=5,
    process_started=None,
    input_paths=(),
    output_path=None,
    resources=None,
    profile_memory=None,
):
    """Measure one cold attempt and repeated warm attempts without timing provenance probes."""
    entered = perf_counter()
    startup = 0.0 if process_started is None else entered - process_started
    for name, value, minimum in (("warmups", warmups, 0), ("repetitions", repetitions, 1)):
        if type(value) is not int or value < minimum:
            raise ValueError(f"{name} must be an integer >= {minimum}")
    if profile_memory is None:
        profile_memory = os.environ.get("BENCHMARK_PROFILE_MEMORY") == "1"
    input_paths = tuple(input_paths)
    resource_metadata = _resource_metadata()
    try:
        resource_metadata.update((resources() if callable(resources) else resources) or {})
    except Exception as exception:
        logger.debug("Session resource metadata unavailable", exc_info=True)
        resource_metadata.setdefault("metadata_errors", {})["session_resources"] = _error(exception)
    metadata = {
        "suite_id": os.environ.get("BENCHMARK_SUITE_ID") or uuid4().hex,
        "suite_started_at": (
            os.environ.get("BENCHMARK_SUITE_STARTED_AT") if os.environ.get("BENCHMARK_SUITE_ID") else None
        )
        or datetime.now(UTC).isoformat(),
        "batch_id": os.environ.get("BENCHMARK_BATCH_ID") or uuid4().hex,
        "warmups": warmups,
        "repetitions": repetitions,
        "cache_policy": (
            "uncontrolled; no cache flushing; same-process repetitions; independent validation after measured attempts "
            "may populate OS input/output caches between attempts; disk reference cache reused within batch"
        ),
        "input_snapshot": _input_snapshot(input_paths),
        "resources": resource_metadata,
        **_source_metadata(),
    }
    phases = [("cold", 1)] + [("warmup", index + 1) for index in range(warmups)]
    phases += [("warm", index + 1) for index in range(repetitions)]
    validator = None
    try:
        for phase, repetition in phases:
            profiler = MemoryProfiler(enabled=profile_memory)
            try:
                profiler.start()
                attempt = {"records": [], "started": perf_counter(), "startup": startup if phase == "cold" else 0.0}
                token = _attempt.set(attempt)
                try:
                    succeeded = bool(execute())
                finally:
                    _attempt.reset(token)
            finally:
                memory_profile = profiler.stop()
            succeeded = succeeded and all(record["error"] is None for record in attempt["records"])
            validation_succeeded = True
            if phase != "warmup" or not succeeded:
                output = None if output_path is None else _output_metadata(output_path, succeeded)
                for record in attempt["records"]:
                    if not succeeded:
                        record.update(
                            duration_seconds=None,
                            total_seconds=None,
                            error=record["error"] or "Benchmark execution returned false",
                        )
                        validation = {
                            "validation": {
                                "status": "unchecked",
                                "reference": "duckdb-sql-v1",
                                "reason": "Benchmark execution failed",
                            }
                        }
                    else:
                        try:
                            if validator is None:
                                validator = ResultValidator(input_paths)
                            validation = validator.validate(record, output_path)
                        except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exception:
                            validation = {
                                "validation": {
                                    "status": "error",
                                    "reference": "duckdb-sql-v1",
                                    "reason": _error(exception),
                                }
                            }
                        validation_succeeded &= validation["validation"]["status"] not in ("mismatch", "error")
                    record.update(
                        metadata,
                        **validation,
                        phase=phase,
                        repetition=repetition,
                        startup_seconds=attempt["startup"],
                        output=output,
                        memory_profile=memory_profile,
                        timer_scope={
                            "duration_seconds": "read-compute-write",
                            "total_seconds": (
                                "startup-and-attempt" if phase == "cold" and process_started is not None else "attempt"
                            ),
                        },
                    )
                    _append_record(record)
            if not succeeded or not validation_succeeded:
                return False
        return True
    finally:
        if validator is not None:
            validator.close()


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
    input_format=None,
):
    """Append one measured execution; failed runs have no numeric duration."""
    attempt = _attempt.get()
    if error is not None:
        duration = total_duration = None
    elif attempt is not None:
        total_duration = attempt["startup"] + perf_counter() - attempt["started"]
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
        "input_format": input_format,
    }
    if attempt is None:
        _append_record(record)
    else:
        attempt["records"].append(record)
