import json
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

from matplotlib.colors import to_rgba

from plot_benchmarks import _plot_runs, _summarize_runs, load_records, render_report

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


def measured_record(*, phase="warm", batch_id="batch-a", repetition=1, **changes):
    duration = changes.get("duration_seconds", 1)
    return record(
        **{
            "batch_id": batch_id,
            "phase": phase,
            "repetition": repetition,
            "warmups": 1,
            "repetitions": 3,
            "startup_seconds": 10 if phase == "cold" else 0,
            "total_seconds": None if duration is None else duration + (10 if phase == "cold" else 0),
            **changes,
        }
    )


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
        self.assertEqual([row[4:7:2] for row in report.tables[0]], [["1", "1000"], ["2", "—"], ["—", "—"]])
        self.assertEqual(report.tables[1][0][4], "100")
        self.assertEqual(report.tables[2][0][4], "50")
        self.assertIn("out of memory", report.tables[0][2][-1])
        self.assertIn("GPU", report.tables[0][2][1])
        self.assertIn("25.8.0", report.tables[0][2][2])

    def test_charts_group_versions_without_stacking_averaging_or_plotting_failures(self):
        runs = [
            record(version="1.33.1", engine="in-memory", duration_seconds=1, total_seconds=1000),
            record(version="1.33.1", duration_seconds=None, error="out of memory"),
            record(engine="in-memory", duration_seconds=2),
            record(duration_seconds=0),
            record(engine="in-memory", duration_seconds=1.5),
        ]
        axes = _plot_runs(runs, {("1.33.1", None): "C0", ("2.1.0", None): "C1"}).axes[0]
        self.assertEqual([bar.get_height() for bar in axes.patches], [1, 2, 1.5, 0])
        self.assertEqual([bar.get_y() for bar in axes.patches], [0, 0, 0, 0])
        self.assertEqual(axes.get_ylim()[0], 0)
        centers = [bar.get_x() + bar.get_width() / 2 for bar in axes.patches]
        self.assertLess(centers[0], centers[1])
        self.assertLess(centers[1], centers[2])
        self.assertLess(centers[2], centers[3])
        labels = [label.get_text() for label in axes.get_xticklabels()]
        self.assertEqual(len(labels), 2)
        for label, engine in zip(labels, ("in-memory", "streaming"), strict=True):
            self.assertIn("Polars", label)
            self.assertIn("CPU", label)
            self.assertIn(engine, label)
        legend = axes.get_legend()
        self.assertEqual([label.get_text() for label in legend.get_texts()], ["1.33.1", "2.1.0"])
        expected_colors = [to_rgba("C0"), to_rgba("C1")]
        self.assertEqual([handle.get_facecolor() for handle in legend.legend_handles], expected_colors)
        self.assertEqual(
            [bar.get_facecolor() for bar in axes.patches],
            [expected_colors[0], expected_colors[1], expected_colors[1], expected_colors[1]],
        )

    def test_warm_medians_ranges_and_cold_totals_keep_batches_and_legacy_samples_separate(self):
        rows = [
            record(duration_seconds=99),
            record(duration_seconds=88),
            measured_record(phase="cold"),
            *[measured_record(repetition=index, duration_seconds=value) for index, value in enumerate((1, 2, 9), 1)],
            *[
                measured_record(batch_id="batch-b", repetition=index, duration_seconds=value)
                for index, value in enumerate((20, 30, 40), 1)
            ],
        ]
        report = self.report(rows)
        self.assertEqual([len(table) for table in report.tables], [2, 1, 2])
        self.assertEqual([row[4] for row in report.tables[0]], ["99", "88"])
        self.assertEqual(report.tables[1][0][6], "11")
        self.assertEqual([row[3:6] for row in report.tables[2]], [["3/3", "2", "1–9"], ["3/3", "30", "20–40"]])
        summaries = _summarize_runs(rows)
        colors = {("2.1.0", None): "C0"}
        cold_axes = _plot_runs([summaries[2]], colors, metric="total_seconds").axes[0]
        self.assertEqual([bar.get_height() for bar in cold_axes.patches], [11])
        warm_axes = _plot_runs(summaries[3:], colors).axes[0]
        self.assertEqual([bar.get_height() for bar in warm_axes.patches], [2, 30])

    def test_failed_or_missing_warm_samples_are_not_charted_as_complete_results(self):
        for rows in (
            [measured_record()],
            [
                measured_record(),
                measured_record(repetition=2, duration_seconds=None, total_seconds=None, error="out of memory"),
            ],
            [measured_record(phase="warmup", duration_seconds=None, total_seconds=None, error="warm-up failed")],
        ):
            with self.subTest(rows=rows):
                report = self.report(rows)
                self.assertFalse(any(tag == "svg" for tag, _ in report.tags))
                self.assertEqual(len(report.tables[0]), 1)
                self.assertNotIn("Success", report.tables[0][0][-1])

    def test_failed_attempts_are_not_zero_time_successes(self):
        report = self.report([record(duration_seconds=None, error="crashed"), record(duration_seconds=0)])
        self.assertEqual([row[4] for row in report.tables[0]], ["—", "0"])
        self.assertIn("crashed", report.tables[0][0][-1])
        failures_only = self.report([record(duration_seconds=None, error="out of memory")])
        self.assertEqual(failures_only.tables[0][0][4], "—")
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
        for invalid in (
            record(duration_seconds=None),
            record(duration_seconds=0, error="crash"),
            record(duration_seconds=None, total_seconds=1, error="crash"),
            measured_record(phase="cold", total_seconds=None),
            measured_record(phase="warmup"),
            measured_record(batch_id=""),
            measured_record(phase="unknown"),
            measured_record(repetition=4),
            measured_record(repetitions=True),
        ):
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
        self.assertIn(payload, report.tables[0][0][0])
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
