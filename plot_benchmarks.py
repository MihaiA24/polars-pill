"""Render benchmarks.jsonl as a table-first HTML report with Matplotlib charts."""

import argparse
import json
import math
from collections import defaultdict
from html import escape
from io import StringIO
from pathlib import Path

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
            except (TypeError, ValueError) as error:
                raise ValueError(f"{path}:{line_number}: {error}") from error
            records.append(record)
    return records


def _plot_runs(runs, colors):
    """Plot successful query durations; row numbers link bars to the results table."""
    successes = [(number, record) for number, record in runs if record["error"] is None]
    figure = Figure(figsize=(10, 1.8 + 0.4 * len(successes)), layout="constrained")
    axes = figure.subplots()
    series = [(record["library"], record["device"]) for _, record in successes]
    bars = axes.barh(
        range(len(successes)),
        [record["duration_seconds"] for _, record in successes],
        color=[colors[key] for key in series],
    )
    axes.set_yticks(range(len(successes)), [f"#{number} · {record['engine']}" for number, record in successes])
    axes.invert_yaxis()
    axes.set_xlabel("Query time (seconds) — lower is better")
    axes.set_xlim(left=0)
    axes.margins(x=0.15)
    axes.spines[["top", "right"]].set_visible(False)
    axes.bar_label(bars, fmt="%.6g", padding=4)
    axes.legend(
        handles=[Patch(color=colors[key], label=" / ".join(key)) for key in dict.fromkeys(series)],
        loc="lower left",
        bbox_to_anchor=(0, 1.02),
        ncols=3,
        frameon=False,
    )
    return figure


def render_report(records):
    """Show every attempt in a workload table, followed by its comparison chart."""
    workloads = defaultdict(list)
    for number, record in enumerate(records, 1):
        workloads[(record["dataset"], record["query"])].append((number, record))
    series = sorted({(record["library"], record["device"]) for record in records})
    colors = {key: f"C{index % 10}" for index, key in enumerate(series)}
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
.number { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
small { display: block; }
details { margin-top: .25rem; font-size: .8rem; }
summary { cursor: pointer; }
figure { margin: 1rem 0 0; overflow-x: auto; }
figcaption { font-size: .9rem; }
svg { display: block; width: 100%; min-width: 900px; height: auto; }
svg text { fill: currentColor !important; }
svg [style*="stroke: #000000"] { stroke: currentColor !important; }
</style>
</head>
<body>
<h1>Benchmark results</h1>
<p>One table per dataset/query; every attempt is retained without averaging.
Query times exclude startup; totals include it when recorded. Lower is better.
Charts compare successful query times on a separate linear scale per workload.
Bar colours identify library/device pairs consistently; row numbers link back to the table.
Historical execution labels are retained, including old eager/streaming and duplicate query labels.</p>
"""
    ]
    if not workloads:
        parts.append("<p>No benchmark runs recorded.</p>\n")
    for section_number, ((dataset, query), runs) in enumerate(workloads.items(), 1):
        parts.append(
            f'<section aria-labelledby="workload-{section_number}">\n'
            f'<h2 id="workload-{section_number}">{escape(f"{dataset} — {query}")}</h2>\n'
            '<div class="table-scroll" role="region" aria-label="Benchmark results" tabindex="0">\n'
            f'<table aria-labelledby="workload-{section_number}"><thead><tr>'
            '<th scope="col">Run</th><th scope="col">Library</th><th scope="col">Version</th>'
            '<th scope="col">Device</th><th scope="col">Execution</th>'
            '<th scope="col" class="number">Query (s)</th><th scope="col" class="number">Total (s)</th>'
            '<th scope="col">Result / details</th></tr></thead><tbody>\n'
        )
        for number, record in runs:
            version = escape(record["version"] or "not recorded")
            if record["backend_version"] is not None:
                version += f"<small> cudf-polars {escape(record['backend_version'])}</small>"
            duration = "—" if record["duration_seconds"] is None else f"{record['duration_seconds']:.6g}"
            total = "—" if record["total_seconds"] is None else f"{record['total_seconds']:.6g}"
            result = "Success" if record["error"] is None else f"Failed: {record['error']}"
            details = [f"Recorded: {record['recorded_at'] or 'not recorded'}"]
            details.extend(
                f"{key}: {value}"
                for key, value in record.items()
                if key not in REQUIRED_FIELDS and isinstance(value, str)
            )
            parts.append(
                f"<tr><td>{number}</td><td>{escape(record['library'])}</td><td>{version}</td>"
                f"<td>{escape(record['device'])}</td><td>{escape(record['engine'])}</td>"
                f'<td class="number">{duration}</td><td class="number">{total}</td>'
                f"<td>{escape(result)}<details><summary>Run details</summary>"
                f"<p>{escape(' · '.join(details))}</p></details></td></tr>\n"
            )
        parts.append("</tbody></table></div>\n")
        if any(record["error"] is None for _, record in runs):
            with rc_context(
                {
                    "svg.fonttype": "none",
                    "svg.hashsalt": str(section_number),
                    "text.parse_math": False,
                    "text.usetex": False,
                }
            ):
                figure = _plot_runs(runs, colors)
                output = StringIO()
                figure.savefig(output, format="svg", transparent=True, metadata={"Date": None})
            svg = output.getvalue()
            parts.append(
                '<figure tabindex="0" aria-label="Scrollable query-time chart"><figcaption>Successful query times — legend: library / device.</figcaption>\n'
                + svg[svg.index("<svg") :]
                + "</figure>\n"
            )
        else:
            parts.append("<p>No successful runs for this workload.</p>\n")
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
