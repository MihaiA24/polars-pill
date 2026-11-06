"""Render benchmarks.jsonl as a table-first HTML report with Matplotlib charts."""

import argparse
import json
import math
from collections import defaultdict
from datetime import UTC, datetime
from html import escape
from io import StringIO
from pathlib import Path
from statistics import median
from xml.etree import ElementTree

from matplotlib import rc_context
from matplotlib.figure import Figure
from matplotlib.patches import Patch

REQUIRED_FIELDS = {
    "recorded_at",
    "library",
    "version",
    "backend_version",
    "duration_seconds",
    "total_seconds",
    "device",
    "engine",
    "dataset",
    "query",
    "error",
}


def load_records(path):
    """Read every JSONL record, rejecting invalid data with its source line."""
    records = []
    with Path(path).open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise TypeError("expected a JSON object")
                missing = REQUIRED_FIELDS - record.keys()
                if missing:
                    raise ValueError(f"missing fields: {', '.join(sorted(missing))}")
                for key in ("library", "device", "engine", "dataset", "query"):
                    if not isinstance(record[key], str) or not record[key].strip():
                        raise ValueError(f"{key} must be a nonempty string")
                for key in ("version", "backend_version", "recorded_at", "error"):
                    if record[key] is not None and not isinstance(record[key], str):
                        raise ValueError(f"{key} must be a string or null")
                for key in ("duration_seconds", "total_seconds"):
                    value = record[key]
                    if value is not None:
                        try:
                            valid = type(value) in (int, float) and math.isfinite(value) and value >= 0
                        except OverflowError:
                            valid = False
                        if not valid:
                            raise ValueError(f"{key} must be a finite nonnegative number or null")
                profile = record.get("memory_profile")
                if profile is not None:
                    if not isinstance(profile, dict) or type(profile.get("enabled")) is not bool:
                        raise ValueError("memory_profile requires a boolean enabled field")
                    errors = profile.get("errors", [])
                    if not isinstance(errors, list) or any(not isinstance(error, str) for error in errors):
                        raise ValueError("memory_profile.errors must be a list of strings")
                    for field in ("peak_rss_bytes", "peak_gpu_memory_bytes", "rss_samples", "gpu_samples"):
                        value = profile.get(field)
                        if value is not None and (type(value) is not int or value < 0):
                            raise ValueError(f"memory_profile.{field} must be a nonnegative integer or null")
                    for field in ("interval_seconds", "gpu_interval_seconds"):
                        value = profile.get(field)
                        if value is not None:
                            try:
                                valid = type(value) in (int, float) and math.isfinite(value) and value > 0
                            except OverflowError:
                                valid = False
                            if not valid:
                                raise ValueError(f"memory_profile.{field} must be finite and positive")
                if record["error"] is None and record["duration_seconds"] is None:
                    raise ValueError("a successful record requires duration_seconds")
                if record["error"] is not None and record["duration_seconds"] is not None:
                    raise ValueError("a failed record requires null duration_seconds")
                if record["error"] is not None and record["total_seconds"] is not None:
                    raise ValueError("a failed record requires null total_seconds")
                if "phase" in record:
                    if record.get("phase") not in ("cold", "warm", "warmup"):
                        raise ValueError("phase must be cold, warm or warmup")
                    if not isinstance(record.get("batch_id"), str) or not record["batch_id"].strip():
                        raise ValueError("batch_id must be a nonempty string")
                    for key, minimum in (("warmups", 0), ("repetitions", 1), ("repetition", 1)):
                        if type(record.get(key)) is not int or record[key] < minimum:
                            raise ValueError(f"{key} must be an integer >= {minimum}")
                    limit = {"cold": 1, "warm": record["repetitions"], "warmup": record["warmups"]}[record["phase"]]
                    if record["repetition"] > limit:
                        raise ValueError("repetition exceeds its phase limit")
                    if (
                        record["phase"] == "cold"
                        and record["error"] is None
                        and _scope_id(record).startswith("suite:")
                        and record["total_seconds"] is None
                    ):
                        raise ValueError("a successful suite cold record requires total_seconds")
                    if record["phase"] == "warmup" and record["error"] is None:
                        raise ValueError("successful warm-ups must not be persisted")
            except (TypeError, ValueError) as error:
                raise ValueError(f"{path}:{line_number}: {error}") from error
            records.append(record)
    return records


def _scope_id(record):
    if "phase" not in record:
        return "legacy"
    suite = record.get("suite_id")
    return f"suite:{suite}" if isinstance(suite, str) and suite.strip() else "history"


def _timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    except ValueError:
        return None


def _display_date(value):
    parsed = _timestamp(value)
    return parsed.strftime("%Y-%m-%d %H:%M:%S UTC") if parsed else "date not recorded"


def _display_id(value):
    return f"{value[:8]}…{value[-8:]}" if len(value) > 20 else value


def _report_scopes(records):
    groups = defaultdict(list)
    for record in records:
        groups[_scope_id(record)].append(record)
    scopes = []
    for scope_id, rows in groups.items():
        kind = "suite" if scope_id.startswith("suite:") else "unassigned" if scope_id == "history" else "legacy"
        dates = [row.get("suite_started_at") for row in rows] if kind == "suite" else []
        dates = [value for value in dates if _timestamp(value) is not None]
        if not dates:
            dates = [row.get("recorded_at") for row in rows if _timestamp(row.get("recorded_at")) is not None]
        started_at = max(dates, key=_timestamp) if dates else None
        label = {
            "suite": f"Suite {_display_id(scope_id.removeprefix('suite:'))}",
            "unassigned": "Unassigned historical batches",
            "legacy": "Legacy attempts",
        }[kind]
        scopes.append(
            {"id": scope_id, "kind": kind, "label": f"{label} · {_display_date(started_at)}", "started_at": started_at}
        )
    scopes.sort(
        key=lambda scope: (_timestamp(scope["started_at"]) or datetime.min.replace(tzinfo=UTC), scope["id"]),
        reverse=True,
    )
    suites = [scope for scope in scopes if scope["kind"] == "suite"]
    latest = max(
        suites,
        key=lambda scope: (_timestamp(scope["started_at"]) or datetime.min.replace(tzinfo=UTC), scope["id"]),
        default=None,
    )
    return scopes, latest["id"] if latest else None


def _comparison(candidate, baseline):
    """All comparison policy lives here; the browser only displays this result."""

    def unavailable(reason):
        return {"speedup": None, "reason": reason}

    phase = candidate.get("phase", "legacy")
    if phase == "legacy" or baseline.get("phase", "legacy") == "legacy":
        return unavailable("Legacy timer scopes are not comparable.")
    if phase == "warmup" or baseline.get("phase") == "warmup":
        return unavailable("Warm-up attempts are not comparable.")
    if any(candidate.get(key) != baseline.get(key) for key in ("dataset", "query", "phase")):
        return unavailable("Different workload or phase.")
    if candidate["error"] is not None or baseline["error"] is not None:
        return unavailable("Candidate or baseline failed or has incomplete samples.")
    metric = "total_seconds" if phase == "cold" else "duration_seconds"
    for label, row in (("Candidate", candidate), ("Baseline", baseline)):
        value = row.get(metric)
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            return unavailable(f"{label} {metric} is missing or not strictly positive.")
    scopes = [row.get("timer_scope") for row in (candidate, baseline)]
    scopes = [scope.get(metric) if isinstance(scope, dict) else None for scope in scopes]
    known_scopes = {"startup-and-attempt", "attempt"} if phase == "cold" else {"read-compute-write"}
    if any(not isinstance(scope, str) or scope not in known_scopes for scope in scopes):
        return unavailable(f"Unknown timer scope for {metric}.")
    if scopes[0] != scopes[1]:
        return unavailable(f"Different timer scopes for {metric}.")
    policies = [row.get("cache_policy") for row in (candidate, baseline)]
    if any(not isinstance(policy, str) or not policy.strip() for policy in policies):
        return unavailable("Unknown cache policy.")
    if policies[0] != policies[1]:
        return unavailable("Different cache policies.")
    snapshots = []
    for row in (candidate, baseline):
        snapshot = row.get("input_snapshot")
        if not isinstance(snapshot, list) or not snapshot:
            return unavailable("Unknown or incomplete input snapshot.")
        items = []
        for item in snapshot:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("path"), str)
                or not item["path"].strip()
                or type(item.get("size_bytes")) is not int
                or item["size_bytes"] < 0
                or type(item.get("mtime_ns")) is not int
                or item["mtime_ns"] < 0
            ):
                return unavailable("Unknown or incomplete input snapshot.")
            items.append((item["path"], item["size_bytes"], item["mtime_ns"]))
        snapshots.append(sorted(items))
    if snapshots[0] != snapshots[1]:
        return unavailable("Different input snapshots (path, size or modification time).")
    if any(row["device"].lower() not in ("cpu", "gpu") for row in (candidate, baseline)):
        return unavailable("Unknown execution device.")
    hardware = []
    for row in (candidate, baseline):
        resources = row.get("resources")
        host = resources.get("hardware") if isinstance(resources, dict) else None
        if (
            not isinstance(host, dict)
            or any(not isinstance(host.get(key), str) or not host[key].strip() for key in ("host_id", "cpu_model"))
            or type(host.get("memory_bytes")) is not int
            or host["memory_bytes"] <= 0
        ):
            return unavailable("Unknown or incomplete hardware identity.")
        hardware.append(host)
    if any(hardware[0][key] != hardware[1][key] for key in ("host_id", "cpu_model", "memory_bytes")):
        return unavailable("Different hardware (host, CPU or memory).")
    if any(row["device"].lower() == "gpu" for row in (candidate, baseline)):
        inventories = []
        for host in hardware:
            gpus = host.get("gpus")
            if not isinstance(gpus, list) or not gpus:
                return unavailable("Unknown or incomplete GPU inventory.")
            inventory = []
            for gpu in gpus:
                if (
                    not isinstance(gpu, dict)
                    or any(
                        not isinstance(gpu.get(key), str) or not gpu[key].strip()
                        for key in ("uuid", "name", "driver_version")
                    )
                    or type(gpu.get("memory_bytes")) is not int
                    or gpu["memory_bytes"] <= 0
                ):
                    return unavailable("Unknown or incomplete GPU inventory.")
                inventory.append(tuple(gpu[key] for key in ("uuid", "name", "memory_bytes", "driver_version")))
            inventories.append(sorted(inventory))
        if inventories[0] != inventories[1]:
            return unavailable("Different GPU inventories.")
    for label, row in (("Candidate", candidate), ("Baseline", baseline)):
        validation = row["validation"]
        if validation["status"] != "passed":
            return unavailable(
                f"{label} validation {validation['status']}: {validation['reason'] or 'not all attempts passed'}."
            )
        if validation["reference"] is None:
            return unavailable(f"{label} validation reference is missing or inconsistent across attempts.")
    if candidate["validation"]["reference"] != baseline["validation"]["reference"]:
        return unavailable("Different validation references.")
    modes = [row["memory_profile"]["enabled"] for row in (candidate, baseline)]
    if any(mode is None for mode in modes):
        return unavailable("Unknown or inconsistent memory profiling mode across attempts.")
    if modes[0] != modes[1]:
        return unavailable("Different memory profiling modes (enabled versus disabled).")
    speedup = baseline[metric] / candidate[metric]
    if not math.isfinite(speedup) or speedup <= 0:
        return unavailable("The speedup ratio is not finite and strictly positive.")
    return {"speedup": speedup, "reason": None}


def _validation_summary(attempts):
    counts = dict.fromkeys(("passed", "mismatch", "error", "unchecked"), 0)
    references = set()
    reasons = []
    for attempt in attempts:
        validation = attempt.get("validation")
        validation = validation if isinstance(validation, dict) else {}
        status = validation.get("status")
        if not isinstance(status, str) or status not in counts:
            status = "unchecked"
        counts[status] += 1
        reference = validation.get("reference")
        references.add(reference if isinstance(reference, str) and reference.strip() else None)
        reason = validation.get("reason")
        if isinstance(reason, str) and reason:
            reasons.append(reason)
        elif status == "unchecked":
            reasons.append("Validation not recorded or unchecked")
    status = next(value for value in ("error", "mismatch", "unchecked", "passed") if counts[value])
    return {
        "status": status,
        "reference": next(iter(references)) if len(references) == 1 else None,
        "reason": "; ".join(dict.fromkeys(reasons)) or None,
        "counts": counts,
    }


def _profile_mode(attempt):
    profile = attempt.get("memory_profile")
    if profile is None:
        return False
    return profile.get("enabled") if isinstance(profile, dict) and type(profile.get("enabled")) is bool else None


def _memory_summary(attempts):
    modes = {_profile_mode(attempt) for attempt in attempts}
    profiles = [attempt.get("memory_profile") for attempt in attempts]
    profiles = [profile if isinstance(profile, dict) else {} for profile in profiles]
    summary = {"enabled": next(iter(modes)) if len(modes) == 1 else None}
    for field in ("peak_rss_bytes", "peak_gpu_memory_bytes"):
        values = [
            profile[field]
            for profile in profiles
            if profile.get("enabled") is True and type(profile.get(field)) is int and profile[field] >= 0
        ]
        summary[field] = max(values) if values else None
    summary["errors"] = list(
        dict.fromkeys(
            error for profile in profiles for error in (profile.get("errors") or []) if isinstance(error, str)
        )
    )
    return summary


def _validation_text(validation):
    counts = ", ".join(f"{count} {status}" for status, count in validation["counts"].items() if count)
    reference = validation["reference"] or "reference unavailable / inconsistent"
    return f"{counts}; {reference}" + (f"; {validation['reason']}" if validation["reason"] else "")


def _selectivity_text(attempts):
    values = []
    for attempt in attempts:
        selectivity = attempt.get("selectivity")
        if not isinstance(selectivity, dict):
            values.append("Not recorded")
            continue
        matched, total, fraction = (selectivity.get(field) for field in ("matched_rows", "input_rows", "fraction"))
        if type(matched) is not int or type(total) is not int:
            values.append("Unavailable")
            continue
        percent = (
            f"{fraction:.4%}" if type(fraction) in (int, float) and math.isfinite(fraction) else "fraction unavailable"
        )
        values.append(f"{matched:,} / {total:,} rows ({percent})")
    return "; ".join(dict.fromkeys(values))


def _memory_text(row, field):
    profile = row["memory_profile"]
    if profile["enabled"] is False:
        return "Disabled / not profiled"
    if profile["enabled"] is None:
        return "Unavailable: inconsistent / unknown profiling mode"
    peak = profile[field]
    text = f"{peak / 1024**2:.4g} MiB ({peak:,} bytes)" if peak is not None else "Unavailable"
    missing = sum(
        not isinstance(attempt.get("memory_profile"), dict)
        or type(attempt["memory_profile"].get(field)) is not int
        or attempt["memory_profile"][field] < 0
        for attempt in row["_records"]
    )
    if peak is not None and missing:
        text += f"; unavailable for {missing}/{len(row['_records'])} attempts"
    if profile["errors"]:
        text += "; " + "; ".join(profile["errors"])
    return text


def _summarize_runs(records):
    """Summarize one process phase at a time; never combine legacy attempts or batches."""
    groups = defaultdict(list)
    for index, record in enumerate(records):
        if "phase" not in record:
            key = ("legacy", index)
        else:
            provenance = json.dumps(
                {
                    key: record.get(key)
                    for key in (
                        "benchmark_revision",
                        "benchmark_dirty",
                        "input_snapshot",
                        "resources",
                        "cache_policy",
                        "timer_scope",
                        "suite_started_at",
                        "repetitions",
                        "warmups",
                    )
                },
                sort_keys=True,
            )
            key = tuple(
                record[key]
                for key in (
                    "dataset",
                    "query",
                    "library",
                    "device",
                    "engine",
                    "version",
                    "backend_version",
                    "batch_id",
                    "phase",
                )
            ) + (_scope_id(record), provenance)
        groups[key].append(record)
    summaries = []
    for attempts in groups.values():
        first = attempts[0]
        successes = [record for record in attempts if record["error"] is None]
        expected = first["repetitions"] if first.get("phase") == "warm" else 1
        complete = len(successes) == len(attempts) == expected
        if "phase" in first:
            complete = complete and {record["repetition"] for record in attempts} == set(range(1, expected + 1))
        errors = list(dict.fromkeys(record["error"] for record in attempts if record["error"] is not None))
        summary = {
            **first,
            "error": None if complete else "; ".join(errors) or f"Incomplete: {len(successes)}/{expected} samples",
            "_samples": len(successes),
            "_expected": expected,
            "_records": attempts,
            "_ranges": {},
            "_scope": _scope_id(first),
            "_attempt": len(summaries) + 1,
            "validation": _validation_summary(attempts),
            "memory_profile": _memory_summary(attempts),
        }
        for field in ("duration_seconds", "total_seconds"):
            values = [record[field] for record in successes if record[field] is not None]
            summary[field] = median(values) if values else None
            summary["_ranges"][field] = (min(values), max(values)) if values else None
        summaries.append(summary)
    return summaries


def _run_identity(record):
    batch = record.get("batch_id") if "phase" in record else None
    identity = f"Batch {_display_id(batch)}" if batch else f"Legacy attempt {record.get('_attempt', '?')}"
    return f"{identity}\n{_display_date(record.get('recorded_at'))}"


def _baseline_label(record):
    backend = f" / cudf-polars {record['backend_version']}" if record["backend_version"] else ""
    return (
        f"{record['library']} {record['version'] or 'version not recorded'}{backend}"
        f" · {record['device']} / {record['engine']} · {_run_identity(record).replace(chr(10), ' · ')}"
    )


def _plot_runs(runs, colors, metric="duration_seconds"):
    """Compare versions side by side; repeated warm samples include min/max whiskers."""
    groups = defaultdict(list)
    for record in runs:
        groups[(record["library"], record["device"], record["engine"])].append(record)
    width = 0.8 / max(map(len, groups.values()))
    figure = Figure(figsize=(max(10, 1.6 * len(groups)), 5), layout="constrained")
    axes = figure.subplots()
    for position, group in enumerate(groups.values()):
        for offset, record in enumerate(group):
            x = position + (offset - (len(group) - 1) / 2) * width
            if record["error"] is not None:
                axes.text(
                    x,
                    0,
                    f"{record['version'] or 'not recorded'}\nfailed\n{_run_identity(record)}",
                    ha="center",
                    va="bottom",
                    fontsize=7,
                )
                continue
            value = record[metric]
            if value is None:
                axes.text(x, 0, f"Time unavailable\n{_run_identity(record)}", ha="center", va="bottom", fontsize=7)
                continue
            limits = record.get("_ranges", {}).get(metric)
            error_range = [[value - limits[0]], [limits[1] - value]] if limits and limits[0] != limits[1] else None
            bars = axes.bar(
                x,
                value,
                width=width,
                color=colors[(record["version"], record["backend_version"])],
                yerr=error_range,
                capsize=3 if error_range else 0,
            )
            axes.bar_label(bars, labels=[f"{value:.4g}\n{_run_identity(record)}"], padding=4, fontsize=7)
    axes.set_xticks(range(len(groups)), [f"{library}\n{device} · {engine}" for library, device, engine in groups])
    axes.set_xlim(-0.5, len(groups) - 0.5)
    label = "Library/session startup + query" if metric == "total_seconds" else "Query time"
    axes.set_ylabel(f"{label} (seconds) — lower is better")
    axes.margins(y=0.15)
    axes.set_ylim(bottom=0)
    axes.spines[["top", "right"]].set_visible(False)
    versions = {(record["version"], record["backend_version"]) for record in runs}
    axes.legend(
        handles=[
            Patch(
                color=color,
                label=(version or "not recorded") + (f" / cudf-polars {backend}" if backend is not None else ""),
            )
            for (version, backend), color in colors.items()
            if (version, backend) in versions
        ],
        title="Version",
        loc="lower left",
        bbox_to_anchor=(0, 1.02),
        ncols=3,
        frameon=False,
    )
    return figure


def render_report(records):
    """Render independent suite/workload/phase sections with precomputed comparisons."""
    workloads = defaultdict(list)
    for index, record in enumerate(_summarize_runs(records)):
        record["_result_id"] = f"result-{index}"
        workloads[(record["_scope"], record["dataset"], record["query"], record.get("phase", "legacy"))].append(record)
    scopes, latest_scope = _report_scopes(records)
    scope_labels = {scope["id"]: scope["label"] for scope in scopes}
    payload = {"latest_scope": latest_scope, "scopes": scopes, "comparisons": {}}
    versions = dict.fromkeys((record["version"], record["backend_version"]) for record in records)
    colors = {key: f"C{index % 10}" for index, key in enumerate(versions)}
    parts = [
        """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Benchmark results</title>
<style>
:root { color-scheme: light dark; }
body { font: 1rem/1.5 system-ui, sans-serif; margin: 2rem auto; padding: 0 1rem; max-width: 1200px; }
h1, h2, td, option { overflow-wrap: anywhere; }
h1, h2 { line-height: 1.25; }
section { margin-block: 2rem; }
[hidden] { display: none !important; }
.filters { display: flex; flex-wrap: wrap; gap: .75rem; padding: 1rem; border: 1px solid; border-radius: .4rem; }
label { display: grid; min-width: 0; max-width: 100%; gap: .25rem; font-size: .9rem; }
select { font: inherit; min-width: 0; max-width: 100%; padding: .35rem; }
:focus-visible { outline: 3px solid #267abf; outline-offset: 3px; }
.baseline-select { width: 100%; }
.table-scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: .85rem; }
th, td { padding: .5rem; text-align: left; border-bottom: 1px solid color-mix(in srgb, currentColor 20%, transparent); vertical-align: top; }
th { white-space: nowrap; background: color-mix(in srgb, currentColor 7%, transparent); }
.number { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
small { display: block; }
details { margin-top: .25rem; font-size: .8rem; }
summary { cursor: pointer; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; }
figure { margin: 1rem 0 0; overflow-x: auto; }
figcaption, .comparison-note, [data-comparison-reason] { font-size: .85rem; }
svg { display: block; width: 100%; min-width: 900px; height: auto; }
svg text { fill: currentColor !important; }
svg [style*="stroke: #000000"] { stroke: currentColor !important; }
</style>
</head>
<body>
<h1>Benchmark results</h1>
<p>Select a suite, workload and phase. Speedup is baseline time divided by candidate time.
Values above 1× are faster.</p>
<details><summary>Measurement and comparison rules</summary>
<p>Each table and chart contains one suite, workload and phase. Unassigned historical batches
and legacy attempts remain separate. Warm rows show the median and min–max within one batch;
raw attempts remain in JSONL. Cold charts use total time including recorded startup; warm and
legacy charts use query time. Cold does not mean a flushed filesystem cache. Failed or
incomplete execution groups have no bar. Unchecked or incorrect results retain their timings
but never receive speedups. Every attempt on both sides must pass the same independent
validation reference, with matching memory profiling modes and known measurement metadata.
Input snapshots describe paths, sizes and modification times, not content hashes.</p>
<p>Selectivity is observed qualifying rows / input rows, not row-group pruning. Sampled
memory peaks are the maximum observed across attempts, not guaranteed instantaneous peaks.
RSS sums live process-tree RSS (shared pages may be counted twice); GPU memory is PID-scoped.
Unavailable probes are not zero usage. Raw validation, selectivity and profiling measurements
remain in each row's details and the original JSONL.</p>
</details>
<noscript><p>JavaScript is disabled. Filters and baseline controls do not update;
all result sections are shown below.</p></noscript>
<div class="filters" role="group" aria-label="Report filters">
<label for="report-view">View<select id="report-view">
<option value="latest">Latest suite</option><option value="history">History</option>
<option value="legacy">Legacy</option></select></label>
<label for="report-suite">Suite / scope<select id="report-suite">
"""
    ]
    for scope in scopes:
        selected = " selected" if scope["id"] == latest_scope else ""
        parts.append(f'<option value="{escape(scope["id"])}"{selected}>{escape(scope["label"])}</option>\n')
    parts.append("</select></label>\n")
    for field, label in (("dataset", "Dataset"), ("query", "Query"), ("phase", "Phase")):
        values = sorted({record.get(field, "legacy" if field == "phase" else "") for record in records})
        parts.append(f'<label for="report-{field}">{label}<select id="report-{field}"><option value="">All</option>')
        for value in values:
            parts.append(f'<option value="{escape(value)}">{escape(value)}</option>')
        parts.append("</select></label>\n")
    parts.append(
        '</div>\n<p id="report-status" aria-live="polite">All recorded measurements are shown below.</p>\n'
        '<p id="scope-summary"></p>\n'
        f'<p id="no-results"{"" if not workloads else " hidden"}>No benchmark runs match this view.</p>\n'
    )
    for section_number, ((scope_id, dataset, query, phase), runs) in enumerate(workloads.items(), 1):
        runs = sorted(runs, key=lambda record: (record["library"], record["device"], record["engine"]))
        metric = "total_seconds" if phase == "cold" else "duration_seconds"
        baseline = next(
            (row for row in runs if row["error"] is None and row.get(metric) is not None and row[metric] > 0), runs[0]
        )
        baseline = next((row for row in runs if _comparison(row, row)["speedup"] is not None), baseline)
        for candidate in runs:
            payload["comparisons"][candidate["_result_id"]] = {
                row["_result_id"]: _comparison(candidate, row) for row in runs
            }
        phase_label = {
            "cold": "Cold process",
            "warm": "Warm process",
            "warmup": "Warm-up failure",
            "legacy": "Legacy single measurements",
        }[phase]
        parts.append(
            f'<section class="workload" data-scope="{escape(scope_id)}" data-dataset="{escape(dataset)}" '
            f'data-query="{escape(query)}" data-phase="{phase}" aria-labelledby="workload-{section_number}">\n'
            f'<h2 id="workload-{section_number}">{escape(f"{dataset} — {query} — {phase_label}")}</h2>\n'
            f"<p>{escape(scope_labels[scope_id])}</p>\n"
            f'<label for="baseline-{section_number}">Comparison baseline'
            f'<select class="baseline-select" id="baseline-{section_number}">\n'
        )
        for row in runs:
            selected = " selected" if row is baseline else ""
            disabled = " disabled" if row["error"] is not None or row.get(metric) is None or row[metric] <= 0 else ""
            parts.append(
                f'<option value="{row["_result_id"]}"{selected}{disabled}>{escape(_baseline_label(row))}</option>\n'
            )
        parts.append(
            "</select></label>\n"
            f'<p class="comparison-note">Speedup uses the '
            f"{'total median for cold measurements' if phase == 'cold' else 'query median'}.</p>\n"
            '<div class="table-scroll" role="region" aria-label="Benchmark results" tabindex="0">\n'
            f'<table aria-labelledby="workload-{section_number}"><thead><tr>'
            '<th scope="col">Library</th><th scope="col">Configuration</th><th scope="col">Version</th>'
            '<th scope="col" class="number">Samples</th><th scope="col" class="number">Query median (s)</th>'
            '<th scope="col" class="number">Query min–max (s)</th><th scope="col" class="number">Total median (s)</th>'
            '<th scope="col">Batch / date</th><th scope="col">Speedup</th>'
            '<th scope="col">Execution / details</th><th scope="col">Validation</th>'
            '<th scope="col">Actual selectivity</th><th scope="col">Sampled peak RSS</th>'
            '<th scope="col">Sampled peak GPU memory</th></tr></thead><tbody>\n'
        )
        for row in runs:
            version = escape(row["version"] or "not recorded")
            if row["backend_version"] is not None:
                version += f"<small>cudf-polars {escape(row['backend_version'])}</small>"
            duration = "—" if row["duration_seconds"] is None else f"{row['duration_seconds']:.6g}"
            total = "—" if row["total_seconds"] is None else f"{row['total_seconds']:.6g}"
            limits = row["_ranges"]["duration_seconds"]
            interval = f"{limits[0]:.6g}–{limits[1]:.6g}" if limits and row["_samples"] > 1 else "—"
            result = "Success" if row["error"] is None else f"Failed / incomplete: {row['error']}"
            metadata = {
                key: value for key, value in row.items() if key not in REQUIRED_FIELDS and not key.startswith("_")
            }
            if isinstance(metadata.get("output"), dict):
                metadata["output"] = {key: value for key, value in metadata["output"].items() if key != "files"}
            metadata["attempts"] = [
                {
                    key: attempt.get(key)
                    for key in (
                        "recorded_at",
                        "repetition",
                        "duration_seconds",
                        "total_seconds",
                        "error",
                        "input_format",
                        "validation",
                        "selectivity",
                        "memory_profile",
                    )
                }
                for attempt in row["_records"]
            ]
            details = escape(json.dumps(metadata, ensure_ascii=False, indent=2))
            comparison = payload["comparisons"][row["_result_id"]][baseline["_result_id"]]
            speedup = "Unavailable" if comparison["speedup"] is None else f"{comparison['speedup']:.3g}×"
            identity = "<br>".join(escape(part) for part in _run_identity(row).split("\n"))
            parts.append(
                f'<tr data-result-id="{row["_result_id"]}"><td>{escape(row["library"])}</td>'
                f"<td>{escape(row['device'])} · {escape(row['engine'])}</td><td>{version}</td>"
                f'<td class="number">{row["_samples"]}/{row["_expected"]}</td>'
                f'<td class="number">{duration}</td><td class="number">{interval}</td><td class="number">{total}</td>'
                f"<td>{identity}</td><td><span data-speedup>{speedup}</span>"
                f"<small data-comparison-reason>{escape(comparison['reason'] or '')}</small></td>"
                f"<td>{escape(result)}<details><summary>Measurement details</summary>"
                f"<pre>{details}</pre></details></td>"
                f"<td>{escape(_validation_text(row['validation']))}</td>"
                f"<td>{escape(_selectivity_text(row['_records']))}</td>"
                f"<td>{escape(_memory_text(row, 'peak_rss_bytes'))}</td>"
                f"<td>{escape(_memory_text(row, 'peak_gpu_memory_bytes'))}</td></tr>\n"
            )
        parts.append("</tbody></table></div>\n")
        if any(row["error"] is None and row.get(metric) is not None for row in runs):
            with rc_context(
                {
                    "svg.fonttype": "none",
                    "svg.hashsalt": str(section_number),
                    "text.parse_math": False,
                    "text.usetex": False,
                }
            ):
                figure = _plot_runs(runs, colors, metric=metric)
                output = StringIO()
                figure.savefig(output, format="svg", transparent=True, metadata={"Date": None})
            # Matplotlib reuses figure/text IDs; namespace them across inline charts.
            ElementTree.register_namespace("", "http://www.w3.org/2000/svg")
            ElementTree.register_namespace("xlink", "http://www.w3.org/1999/xlink")
            chart = ElementTree.fromstring(output.getvalue())
            prefix = f"chart-{section_number}-"
            for element in chart.iter():
                for attribute, value in element.attrib.items():
                    if attribute == "id":
                        element.set(attribute, prefix + value)
                    elif attribute in ("href", "{http://www.w3.org/1999/xlink}href") and value.startswith("#"):
                        element.set(attribute, "#" + prefix + value[1:])
                    elif "url(#" in value:
                        element.set(attribute, value.replace("url(#", f"url(#{prefix}"))
            svg = ElementTree.tostring(chart, encoding="unicode")
            caption = "Cold total time" if phase == "cold" else "Query medians"
            parts.append(
                f'<figure tabindex="0" aria-label="Scrollable latency chart"><figcaption>{caption} by library/configuration; '
                "annotations identify batches or legacy attempts. Whiskers show min–max.</figcaption>\n"
                + svg[svg.index("<svg") :]
                + "</figure>\n"
            )
        else:
            parts.append("<p>No complete successful measurements for this scope, workload and phase.</p>\n")
        parts.append("</section>\n")
    encoded = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
    parts.append(f'<script type="application/json" id="benchmark-data">{encoded}</script>\n')
    parts.append(
        "<script>\n" + Path(__file__).with_name("benchmark_report.js").read_text(encoding="utf-8") + "\n</script>\n"
    )
    parts.append("</body>\n</html>\n")
    return "".join(parts)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("benchmarks.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("BENCHMARKS.html"))
    args = parser.parse_args(argv)
    try:
        report = render_report(load_records(args.input))
        args.output.write_text(report, encoding="utf-8")
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
