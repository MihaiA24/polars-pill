import json
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

from matplotlib.colors import to_rgba

from plot_benchmarks import _plot_runs, load_records, render_report

ROOT = Path(__file__).resolve().parents[1]


def record(**changes):
    return {
        "recorded_at": None,
        "library": "Polars",
        "version": "2.1.0",
        "backend_version": None,
        "duration_seconds": 1,
        "total_seconds": None,
        "device": "CPU",
        "engine": "streaming",
        "dataset": "nyc-green",
        "query": "simple",
        "error": None,
        **changes,
    }


class Report(HTMLParser):
    def __init__(self, document):
        super().__init__()
        self.tags = []
        self.tables = []
        self.text = ""
        self.cell = None
        self.row = []
        self.feed(document)

    def handle_starttag(self, tag, attributes):
        self.tags.append((tag, dict(attributes)))
        if tag == "table":
            self.tables.append([])
        elif tag == "tr":
            self.row = []
        elif tag == "td":
            self.cell = []

    def handle_endtag(self, tag):
        if tag == "td":
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row:
            self.tables[-1].append(self.row)

    def handle_data(self, data):
        self.text += data
        if self.cell is not None:
            self.cell.append(data)


class PlotBenchmarksTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.input = self.directory / "benchmarks.jsonl"

    def report(self, records):
        self.input.write_text("".join(json.dumps(row) + "\n" for row in records), encoding="utf-8")
        return Report(render_report(load_records(self.input)))

    def test_tables_keep_versions_durations_and_outcomes_with_their_workloads(self):
        report = self.report(
            [
                record(version="1.33.1", duration_seconds=1, total_seconds=1000),
                record(version="2.1.0", duration_seconds=2),
                record(
                    version="1.31.0",
                    backend_version="25.8.0",
                    device="GPU",
                    duration_seconds=None,
                    error="out of memory",
                ),
                record(duration_seconds=100, dataset="nyc-yellow"),
                record(duration_seconds=50, query="complex"),
            ]
        )
        self.assertEqual(len(report.tables), 3)
        self.assertEqual([row[2].split()[0] for row in report.tables[0]], ["1.33.1", "2.1.0", "1.31.0"])
        self.assertEqual([row[5:7] for row in report.tables[0]], [["1", "1000"], ["2", "—"], ["—", "—"]])
        self.assertEqual(report.tables[1][0][5], "100")
        self.assertEqual(report.tables[2][0][5], "50")
        self.assertIn("out of memory", report.tables[0][2][-1])
        self.assertEqual(report.tables[0][2][3], "GPU")
        self.assertIn("25.8.0", report.tables[0][2][2])

    def test_charts_use_query_times_skip_failures_and_match_the_legend(self):
        runs = [
            (1, record(duration_seconds=1, total_seconds=1000)),
            (2, record(duration_seconds=2, device="GPU")),
            (3, record(duration_seconds=None, error="out of memory")),
            (4, record(duration_seconds=0, device="GPU")),
        ]
        axes = _plot_runs(runs, {("Polars", "CPU"): "C0", ("Polars", "GPU"): "C1"}).axes[0]
        self.assertEqual([bar.get_width() for bar in axes.patches], [1, 2, 0])
        self.assertEqual(axes.get_xlim()[0], 0)
        legend = axes.get_legend()
        self.assertEqual([label.get_text() for label in legend.get_texts()], ["Polars / CPU", "Polars / GPU"])
        expected_colors = [to_rgba("C0"), to_rgba("C1")]
        self.assertEqual([handle.get_facecolor() for handle in legend.legend_handles], expected_colors)
        self.assertEqual([bar.get_facecolor() for bar in axes.patches], [*expected_colors, expected_colors[1]])
        self.assertEqual([label.get_text().split(" · ")[0] for label in axes.get_yticklabels()], ["#1", "#2", "#4"])

    def test_failed_attempts_are_not_zero_time_successes(self):
        report = self.report([record(duration_seconds=None, error="crashed"), record(duration_seconds=0)])
        self.assertEqual([row[5] for row in report.tables[0]], ["—", "0"])
        self.assertIn("crashed", report.tables[0][0][-1])
        failures_only = self.report([record(duration_seconds=None, error="out of memory")])
        self.assertEqual(failures_only.tables[0][0][5], "—")
        self.assertFalse(any(tag == "svg" for tag, _ in failures_only.tags))

    def test_malformed_json_reports_original_line_and_path(self):
        self.input.write_text(json.dumps(record()) + "\n\n{broken}\n", encoding="utf-8")
        with self.assertRaises(ValueError) as caught:
            load_records(self.input)
        self.assertIn(f"{self.input}:3:", str(caught.exception))

    def test_invalid_numbers_and_inconsistent_outcomes_are_rejected(self):
        for field in ("duration_seconds", "total_seconds"):
            for value in (-1, float("nan"), float("inf"), -float("inf"), True, "1", []):
                with self.subTest(field=field, value=value):
                    self.input.write_text(json.dumps(record(**{field: value})) + "\n", encoding="utf-8")
                    with self.assertRaises(ValueError) as caught:
                        load_records(self.input)
                    self.assertIn(f"{self.input}:1:", str(caught.exception))
                    self.assertIn(field, str(caught.exception))
        for invalid in (record(duration_seconds=None), record(duration_seconds=0, error="crash")):
            with self.subTest(record=invalid):
                self.input.write_text(json.dumps(invalid) + "\n", encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_records(self.input)
        for invalid in ([], {}, {**record(), "library": 42}):
            with self.subTest(record=invalid):
                self.input.write_text(json.dumps(invalid) + "\n", encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_records(self.input)

    def test_untrusted_labels_and_errors_remain_text_not_markup(self):
        payload = '<script>alert("x")</script><img src=x onerror="boom">&'
        malicious = record(
            **dict.fromkeys(
                ("library", "version", "backend_version", "device", "engine", "dataset", "query", "recorded_at"),
                payload,
            ),
            provenance=payload,
        )
        report = self.report([malicious, record(duration_seconds=None, error=payload)])
        self.assertIn(payload, report.tables[0][0][1])
        self.assertIn(payload, report.tables[-1][0][-1])
        self.assertFalse(any(tag in ("script", "img") for tag, _ in report.tags))
        self.assertFalse(any("onerror" in attributes for _, attributes in report.tags))
        self.assertFalse(
            any(payload in value for _, attributes in report.tags for value in attributes.values() if value is not None)
        )

    def test_no_argument_cli_generates_standalone_empty_report(self):
        self.input.write_text("", encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(ROOT / "plot_benchmarks.py")],
            cwd=self.directory,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = Report((self.directory / "BENCHMARKS.html").read_text(encoding="utf-8"))
        self.assertEqual(report.tables, [])
        self.assertFalse(any(tag in ("svg", "script", "link", "iframe") for tag, _ in report.tags))


if __name__ == "__main__":
    unittest.main()
