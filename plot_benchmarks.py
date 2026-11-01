"""Render benchmarks.jsonl as a table-first HTML report with Matplotlib charts."""

import argparse
import json
import math
from collections import defaultdict
from html import escape
from io import StringIO
from pathlib import Path
from statistics import median

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
                if record["error"] is None and record["duration_seconds"] is None:
                    raise ValueError("a successful record requires duration_seconds")
                if record["error"] is not None and record["duration_seconds"] is not None:
                    raise ValueError("a failed record requires null duration_seconds")
                if record["error"] is not None and record["total_seconds"] is not None:
                    raise ValueError("a failed record requires null total_seconds")
                if "phase" in record or "batch_id" in record:
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
                    if record["phase"] == "cold" and record["error"] is None and record["total_seconds"] is None:
                        raise ValueError("a successful cold record requires total_seconds")
                    if record["phase"] == "warmup" and record["error"] is None:
                        raise ValueError("successful warm-ups must not be persisted")
            except (TypeError, ValueError) as error:
                raise ValueError(f"{path}:{line_number}: {error}") from error
            records.append(record)
    return records


def _summarize_runs(records):
    """Summarize one process phase at a time; never combine legacy attempts or batches."""
    groups = defaultdict(list)
    for index, record in enumerate(records):
        if "batch_id" not in record:
            key = ("legacy", index)
        else:
            provenance = json.dumps(
                {
                    key: record.get(key)
                    for key in ("benchmark_revision", "benchmark_dirty", "input_snapshot", "resources", "cache_policy")
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
            ) + (provenance,)
        groups[key].append(record)
    summaries = []
    for attempts in groups.values():
        first = attempts[0]
        successes = [record for record in attempts if record["error"] is None]
        expected = first["repetitions"] if first.get("phase") == "warm" else 1
        complete = len(successes) == len(attempts) == expected
        if "batch_id" in first:
            complete = complete and {record["repetition"] for record in attempts} == set(range(1, expected + 1))
        errors = list(dict.fromkeys(record["error"] for record in attempts if record["error"] is not None))
        summary = {
            **first,
            "error": None if complete else "; ".join(errors) or f"Incomplete: {len(successes)}/{expected} samples",
            "_samples": len(successes),
            "_expected": expected,
            "_records": attempts,
            "_ranges": {},
        }
        for field in ("duration_seconds", "total_seconds"):
            values = [record[field] for record in successes if record[field] is not None]
            summary[field] = median(values) if values else None
            summary["_ranges"][field] = (min(values), max(values)) if values else None
        summaries.append(summary)
    return summaries


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
                axes.text(x, 0, f"{record['version'] or 'not recorded'}\nfailed", ha="center", va="bottom", fontsize=8)
                continue
            value = record[metric]
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
            axes.bar_label(bars, fmt="%.4g", padding=4)
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
    """Show phase-specific medians and ranges without pooling independent benchmark batches."""
    workloads = defaultdict(list)
    for record in _summarize_runs(records):
        workloads[(record["dataset"], record["query"], record.get("phase", "legacy"))].append(record)
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
body { font: 1rem/1.5 system-ui, sans-serif; margin: 2rem auto; padding: 0 1rem; max-width: 1100px; }
h1, h2, td { overflow-wrap: anywhere; }
h1, h2 { line-height: 1.25; }
section { margin-block: 2.5rem; }
.table-scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: .9rem; }
th, td { padding: .6rem .65rem; text-align: left; border-bottom: 1px solid color-mix(in srgb, currentColor 20%, transparent); vertical-align: top; }
th { white-space: nowrap; background: color-mix(in srgb, currentColor 7%, transparent); }
td:nth-child(-n+3) { white-space: nowrap; }
.number { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
small { display: block; }
details { margin-top: .25rem; font-size: .8rem; }
summary { cursor: pointer; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; }
figure { margin: 1rem 0 0; overflow-x: auto; }
figcaption { font-size: .9rem; }
svg { display: block; width: 100%; min-width: 900px; height: auto; }
svg text { fill: currentColor !important; }
svg [style*="stroke: #000000"] { stroke: currentColor !important; }
</style>
</head>
<body>
<h1>Benchmark results</h1>
<p>Tables separate cold, warm and legacy measurements. Warm rows show the median and min–max
within one benchmark batch; raw attempts remain in JSONL. Cold charts include library/session
startup; warm and legacy charts use query time. Cold does not mean a flushed filesystem cache.
Adjacent bars compare versions; whiskers show min–max. Failed or incomplete groups have no bar.
Legacy attempts retain their original timer scopes and are not pooled with the new protocol.</p>
"""
    ]
    if not workloads:
        parts.append("<p>No benchmark runs recorded.</p>\n")
    for section_number, ((dataset, query, phase), runs) in enumerate(workloads.items(), 1):
        runs = sorted(runs, key=lambda record: (record["library"], record["device"], record["engine"]))
        phase_label = {
            "cold": "Cold process",
            "warm": "Warm process",
            "warmup": "Warm-up failure",
            "legacy": "Legacy single measurements",
        }[phase]
        parts.append(
            f'<section aria-labelledby="workload-{section_number}">\n'
            f'<h2 id="workload-{section_number}">{escape(f"{dataset} — {query} — {phase_label}")}</h2>\n'
            '<div class="table-scroll" role="region" aria-label="Benchmark results" tabindex="0">\n'
            f'<table aria-labelledby="workload-{section_number}"><thead><tr>'
            '<th scope="col">Library</th><th scope="col">Configuration</th><th scope="col">Version</th>'
            '<th scope="col" class="number">Samples</th><th scope="col" class="number">Query median (s)</th>'
            '<th scope="col" class="number">Query min–max (s)</th><th scope="col" class="number">Total median (s)</th>'
            '<th scope="col">Result / details</th></tr></thead><tbody>\n'
        )
        for record in runs:
            version = escape(record["version"] or "not recorded")
            if record["backend_version"] is not None:
                version += f"<small> cudf-polars {escape(record['backend_version'])}</small>"
            duration = "—" if record["duration_seconds"] is None else f"{record['duration_seconds']:.6g}"
            total = "—" if record["total_seconds"] is None else f"{record['total_seconds']:.6g}"
            limits = record["_ranges"]["duration_seconds"]
            interval = f"{limits[0]:.6g}–{limits[1]:.6g}" if limits and record["_samples"] > 1 else "—"
            result = "Success" if record["error"] is None else f"Failed / incomplete: {record['error']}"
            metadata = {
                key: value for key, value in record.items() if key not in REQUIRED_FIELDS and not key.startswith("_")
            }
            if isinstance(metadata.get("output"), dict):
                metadata["output"] = {key: value for key, value in metadata["output"].items() if key != "files"}
            metadata["attempts"] = [
                {
                    key: attempt.get(key)
                    for key in ("recorded_at", "repetition", "duration_seconds", "total_seconds", "error")
                }
                for attempt in record["_records"]
            ]
            details = escape(json.dumps(metadata, ensure_ascii=False, indent=2))
            parts.append(
                f"<tr><td>{escape(record['library'])}</td>"
                f"<td>{escape(record['device'])} · {escape(record['engine'])}</td><td>{version}</td>"
                f'<td class="number">{record["_samples"]}/{record["_expected"]}</td>'
                f'<td class="number">{duration}</td><td class="number">{interval}</td><td class="number">{total}</td>'
                f"<td>{escape(result)}<details><summary>Measurement details</summary>"
                f"<pre>{details}</pre></details></td></tr>\n"
            )
        parts.append("</tbody></table></div>\n")
        if any(record["error"] is None for record in runs):
            metric = "total_seconds" if phase == "cold" else "duration_seconds"
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
            svg = output.getvalue()
            caption = "Library/session startup + query" if phase == "cold" else "Query medians"
            parts.append(
                f'<figure tabindex="0" aria-label="Scrollable latency chart"><figcaption>{caption} by library/configuration; adjacent bars compare versions. Whiskers show min–max.</figcaption>\n'
                + svg[svg.index("<svg") :]
                + "</figure>\n"
            )
        else:
            parts.append("<p>No complete successful measurements for this workload and phase.</p>\n")
        parts.append("</section>\n")
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
