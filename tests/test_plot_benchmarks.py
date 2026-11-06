import json
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

from plot_benchmarks import load_records, render_report

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


def comparable_record(**changes):
    return measured_record(
        **{
            "suite_id": "suite-a",
            "suite_started_at": "2026-11-05T12:00:00Z",
            "recorded_at": "2026-11-05T12:01:00Z",
            "repetitions": 1,
            "timer_scope": {"duration_seconds": "read-compute-write", "total_seconds": "startup-and-attempt"},
            "cache_policy": "uncontrolled; no cache flushing; same-process repetitions",
            "input_snapshot": [{"path": "fixture.csv", "size_bytes": 50, "mtime_ns": 1234}],
            "resources": {
                "threads": 4,
                "hardware": {"host_id": "hashed-host", "cpu_model": "Test CPU", "memory_bytes": 1024, "gpus": None},
            },
            **changes,
        }
    )


class Report(HTMLParser):
    def __init__(self, document):
        super().__init__()
        self.document = document
        self.tags = []
        self.tables = []
        self.sections = []
        self.scripts = []
        self.selects = {}
        self.text = ""
        self.cell = None
        self.row = []
        self.section = None
        self.in_chart = False
        self.script = None
        self.select = None
        self.option = None
        self.feed(document)
        self.data = json.loads(
            next(script["text"] for script in self.scripts if script["attributes"].get("id") == "benchmark-data")
        )

    def handle_starttag(self, tag, attributes):
        attributes = dict(attributes)
        self.tags.append((tag, attributes))
        if tag == "section":
            self.section = {"attributes": attributes, "tables": [], "text": "", "charts": 0, "chart_text": ""}
            self.sections.append(self.section)
        elif tag == "svg" and self.section is not None:
            self.section["charts"] += 1
            self.in_chart = True
        elif tag == "script":
            self.script = {"attributes": attributes, "text": ""}
            self.scripts.append(self.script)
        elif tag == "select":
            self.select = {"attributes": attributes, "options": []}
            self.selects[attributes["id"]] = self.select
        elif tag == "option":
            self.option = {"attributes": attributes, "text": ""}
            self.select["options"].append(self.option)
        elif tag == "table":
            self.tables.append([])
            if self.section is not None:
                self.section["tables"].append(self.tables[-1])
        elif tag == "tr":
            self.row = []
        elif tag == "td":
            self.cell = []
        elif tag in ("br", "small") and self.cell is not None:
            self.cell.append(" ")

    def handle_endtag(self, tag):
        if tag == "section":
            self.section = None
        elif tag == "script":
            self.script = None
        elif tag == "select":
            self.select = None
        elif tag == "option":
            self.option = None
        elif tag == "svg":
            self.in_chart = False
        elif tag == "td":
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row:
            self.tables[-1].append(self.row)

    def handle_data(self, data):
        if self.script is not None:
            self.script["text"] += data
            return
        self.text += data
        if self.section is not None:
            self.section["text"] += data
            if self.in_chart:
                self.section["chart_text"] += data
        if self.option is not None:
            self.option["text"] += data
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

    def test_scopes_use_actual_suites_timestamps_and_keep_historical_attempts(self):
        rows = [
            comparable_record(suite_id="newest", suite_started_at="2026-11-06T10:00:00Z", duration_seconds=2),
            comparable_record(
                suite_id="fallback", suite_started_at=None, recorded_at="2026-11-05T11:00:00Z", duration_seconds=3
            ),
            comparable_record(
                suite_id="older",
                suite_started_at="2026-11-04T10:00:00Z",
                recorded_at="2030-01-01T00:00:00Z",
                duration_seconds=4,
            ),
            measured_record(
                batch_id="history-a", repetitions=1, duration_seconds=5, recorded_at="2025-01-01T00:00:00Z"
            ),
            measured_record(
                batch_id="history-b", repetitions=1, duration_seconds=6, recorded_at="2025-01-02T00:00:00Z"
            ),
            record(batch_id="old-batch", suite_id="not-a-suite", duration_seconds=7),
            record(duration_seconds=8),
            comparable_record(
                suite_id="newest", suite_started_at="2026-11-06T10:00:00Z", phase="cold", duration_seconds=9
            ),
            comparable_record(
                suite_id="newest", suite_started_at="2026-11-06T10:00:00Z", query="complex", duration_seconds=10
            ),
            comparable_record(
                suite_id="older",
                suite_started_at="2026-11-04T10:00:00Z",
                recorded_at="2030-01-01T00:00:00Z",
                dataset="other-data",
                duration_seconds=11,
            ),
        ]
        report = self.report(rows)
        self.assertEqual(report.data["latest_scope"], "suite:newest")
        self.assertEqual(
            [scope["id"] for scope in report.data["scopes"]],
            ["suite:newest", "suite:fallback", "suite:older", "history", "legacy"],
        )
        sections = {
            tuple(
                section["attributes"][key] for key in ("data-scope", "data-dataset", "data-query", "data-phase")
            ): section
            for section in report.sections
        }
        self.assertEqual(len(sections), 8)
        self.assertEqual(sections[("suite:newest", "nyc-green", "simple", "warm")]["tables"][0][0][4], "2")
        self.assertEqual(sections[("suite:older", "nyc-green", "simple", "warm")]["tables"][0][0][4], "4")
        history = sections[("history", "nyc-green", "simple", "warm")]
        self.assertEqual([row[4] for row in history["tables"][0]], ["5", "6"])
        self.assertIn("Batch history-a", history["chart_text"])
        legacy = sections[("legacy", "nyc-green", "simple", "legacy")]
        self.assertEqual([row[4] for row in legacy["tables"][0]], ["7", "8"])
        self.assertIn("Legacy attempt", legacy["chart_text"])
        for section in report.sections:
            self.assertEqual(len(section["tables"]), 1)
            self.assertEqual(section["charts"], 1)
        for candidate, baselines in report.data["comparisons"].items():
            if candidate in {"result-3", "result-4"}:
                expected = {"result-3", "result-4"}
            elif candidate in {"result-5", "result-6"}:
                expected = {"result-5", "result-6"}
            else:
                expected = {candidate}
            self.assertEqual(set(baselines), expected)
        ids = [attrs["id"] for _, attrs in report.tags if "id" in attrs]
        self.assertEqual(len(ids), len(set(ids)))

    def test_compatible_speedups_use_phase_metric_and_medians_not_engine_resources(self):
        rows = []
        for batch, values, total, engine in (
            ("baseline", (6, 8, 10), 100, "streaming"),
            ("candidate", (2, 4, 100), 1000, "in-memory"),
        ):
            for repetition, duration in enumerate(values, 1):
                rows.append(
                    comparable_record(
                        batch_id=batch,
                        repetition=repetition,
                        repetitions=3,
                        duration_seconds=duration,
                        total_seconds=total,
                        engine=engine,
                        resources={**comparable_record()["resources"], "threads": 2 if batch == "baseline" else 8},
                    )
                )
        rows += [
            comparable_record(phase="cold", batch_id="baseline", duration_seconds=1, total_seconds=20),
            comparable_record(phase="cold", batch_id="candidate", duration_seconds=4, total_seconds=5),
        ]
        report = self.report(rows)
        comparisons = report.data["comparisons"]
        self.assertEqual(comparisons["result-1"]["result-0"], {"speedup": 2, "reason": None})
        self.assertEqual(comparisons["result-0"]["result-1"], {"speedup": 0.5, "reason": None})
        self.assertEqual(comparisons["result-3"]["result-2"], {"speedup": 4, "reason": None})
        self.assertIn("4×", report.tables[1][1][8])
        self.assertIn("20", report.sections[1]["chart_text"])
        self.assertEqual(report.tables[0][0][3:6], ["3/3", "4", "2–100"])

    def test_unavailable_comparisons_keep_measurements_and_concrete_reasons(self):
        hardware = comparable_record()["resources"]["hardware"]
        cases = [
            ({"timer_scope": None}, "Unknown timer scope"),
            ({"timer_scope": {"duration_seconds": []}}, "Unknown timer scope"),
            ({"cache_policy": None}, "Unknown cache policy"),
            ({"cache_policy": "flushed"}, "Different cache policies"),
            ({"input_snapshot": None}, "Unknown or incomplete input snapshot"),
            ({"input_snapshot": []}, "Unknown or incomplete input snapshot"),
            (
                {"input_snapshot": [{"path": "fixture.csv", "size_bytes": 50, "mtime_ns": None}]},
                "Unknown or incomplete input snapshot",
            ),
            (
                {"input_snapshot": [{"path": "other.csv", "size_bytes": 50, "mtime_ns": 1234}]},
                "Different input snapshots",
            ),
            (
                {"input_snapshot": [{"path": "fixture.csv", "size_bytes": 51, "mtime_ns": 1234}]},
                "Different input snapshots",
            ),
            (
                {"input_snapshot": [{"path": "fixture.csv", "size_bytes": 50, "mtime_ns": 1235}]},
                "Different input snapshots",
            ),
            ({"resources": None}, "Unknown or incomplete hardware"),
            ({"resources": {"hardware": {**hardware, "cpu_model": None}}}, "Unknown or incomplete hardware"),
            ({"resources": {"hardware": {**hardware, "host_id": "another-host"}}}, "Different hardware"),
            ({"resources": {"hardware": {**hardware, "cpu_model": "Another CPU"}}}, "Different hardware"),
            ({"resources": {"hardware": {**hardware, "memory_bytes": 2048}}}, "Different hardware"),
            ({"device": "GPU"}, "Unknown or incomplete GPU inventory"),
            ({"device": "TPU"}, "Unknown execution device"),
            ({"duration_seconds": 0}, "not strictly positive"),
            ({"duration_seconds": None, "total_seconds": None, "error": "crashed"}, "failed or has incomplete"),
            ({"repetitions": 2}, "failed or has incomplete"),
        ]
        for changes, reason in cases:
            with self.subTest(changes=changes):
                report = self.report(
                    [comparable_record(batch_id="baseline"), comparable_record(batch_id="candidate", **changes)]
                )
                comparison = report.data["comparisons"]["result-1"]["result-0"]
                self.assertIsNone(comparison["speedup"])
                self.assertIn(reason, comparison["reason"])
                self.assertEqual(len(report.tables[0]), 2)
                self.assertIn(reason, report.tables[0][1][8])
                self.assertIn("Batch candidate", report.tables[0][1][7])
        for phase, changes, reason in (
            ("cold", {"timer_scope": {"total_seconds": "attempt"}}, "Different timer scopes"),
            ("cold", {"total_seconds": 0}, "not strictly positive"),
            ("warm", {"timer_scope": {"duration_seconds": "attempt"}}, "Unknown timer scope"),
        ):
            with self.subTest(phase=phase, changes=changes):
                report = self.report(
                    [comparable_record(phase=phase), comparable_record(phase=phase, batch_id="candidate", **changes)]
                )
                comparison = report.data["comparisons"]["result-1"]["result-0"]
                self.assertIsNone(comparison["speedup"])
                self.assertIn(reason, comparison["reason"])
        for row, reason in (
            (record(), "Legacy timer scopes"),
            (
                measured_record(phase="warmup", duration_seconds=None, total_seconds=None, error="warm-up failed"),
                "Warm-up attempts",
            ),
            (measured_record(repetitions=1), "Unknown timer scope"),
        ):
            report = self.report([row])
            comparison = report.data["comparisons"]["result-0"]["result-0"]
            self.assertIsNone(comparison["speedup"])
            self.assertIn(reason, comparison["reason"])

    def test_historical_missing_cold_total_remains_visible_without_a_ratio(self):
        report = self.report(
            [
                comparable_record(suite_id=None, phase="cold"),
                comparable_record(suite_id=None, phase="cold", batch_id="candidate", total_seconds=None),
            ]
        )
        self.assertEqual(report.sections[0]["attributes"]["data-scope"], "history")
        self.assertEqual(report.tables[0][1][4:7:2], ["1", "—"])
        comparison = report.data["comparisons"]["result-1"]["result-0"]
        self.assertIsNone(comparison["speedup"])
        self.assertIn("total_seconds is missing", comparison["reason"])

    def test_gpu_inventory_is_required_only_when_a_gpu_participates(self):
        gpu = {"uuid": "hashed-gpu", "name": "Test GPU", "memory_bytes": 4096, "driver_version": "1.0"}
        hardware = comparable_record()["resources"]["hardware"]
        resources = {"hardware": {**hardware, "gpus": [gpu]}}
        for candidate_resources, expected_reason in (
            (resources, None),
            ({"hardware": {**hardware, "gpus": [{**gpu, "driver_version": "2.0"}]}}, "Different GPU inventories"),
            (
                {"hardware": {**hardware, "gpus": [{**gpu, "memory_bytes": None}]}},
                "Unknown or incomplete GPU inventory",
            ),
        ):
            with self.subTest(resources=candidate_resources):
                report = self.report(
                    [
                        comparable_record(resources=resources, duration_seconds=4),
                        comparable_record(
                            batch_id="gpu", device="GPU", resources=candidate_resources, duration_seconds=2
                        ),
                    ]
                )
                comparison = report.data["comparisons"]["result-1"]["result-0"]
                if expected_reason is None:
                    self.assertEqual(comparison, {"speedup": 2, "reason": None})
                else:
                    self.assertIsNone(comparison["speedup"])
                    self.assertIn(expected_reason, comparison["reason"])

    def test_timer_scope_changes_never_pool_samples(self):
        report = self.report(
            [
                comparable_record(repetitions=2),
                comparable_record(repetitions=2, repetition=2, timer_scope={"duration_seconds": "another-scope"}),
            ]
        )
        self.assertEqual([row[3] for row in report.tables[0]], ["1/2", "1/2"])
        self.assertTrue(all("incomplete" in row[-1] for row in report.tables[0]))
        self.assertEqual(report.sections[0]["charts"], 0)

    def test_extreme_ratios_are_unavailable_not_nonfinite_json(self):
        for candidate, baseline in ((1e-300, 1e300), (1e300, 1e-300)):
            with self.subTest(candidate=candidate):
                report = self.report(
                    [
                        comparable_record(duration_seconds=baseline),
                        comparable_record(batch_id="candidate", duration_seconds=candidate),
                    ]
                )
                comparison = report.data["comparisons"]["result-1"]["result-0"]
                self.assertIsNone(comparison["speedup"])
                self.assertIn("finite and strictly positive", comparison["reason"])
                embedded = next(
                    script["text"] for script in report.scripts if script["attributes"].get("id") == "benchmark-data"
                )
                self.assertNotIn("Infinity", embedded)

    def test_native_controls_default_baseline_and_safe_embedded_data(self):
        payload = '</script><img src=x onerror="boom">&'
        report = self.report(
            [
                comparable_record(
                    batch_id="failed", duration_seconds=None, total_seconds=None, error="crash", suite_id=payload
                ),
                comparable_record(batch_id="positive", duration_seconds=2, suite_id=payload),
                comparable_record(batch_id="zero", duration_seconds=0, suite_id=payload),
            ]
        )
        self.assertEqual(report.data["latest_scope"], f"suite:{payload}")
        embedded = next(
            script["text"] for script in report.scripts if script["attributes"].get("id") == "benchmark-data"
        )
        self.assertNotIn("<", embedded)
        self.assertEqual(len(report.scripts), 2)
        self.assertFalse(
            any(tag == "img" or any(key.lower().startswith("on") for key in attrs) for tag, attrs in report.tags)
        )
        controls = {"report-view", "report-suite", "report-dataset", "report-query", "report-phase", "baseline-1"}
        self.assertEqual(set(report.selects), controls)
        labels = {attrs["for"] for tag, attrs in report.tags if tag == "label"}
        self.assertTrue(controls <= labels)
        options = report.selects["baseline-1"]["options"]
        selected = [option for option in options if "selected" in option["attributes"]]
        self.assertEqual([option["attributes"]["value"] for option in selected], ["result-1"])
        self.assertIn("Batch positive", selected[0]["text"])
        self.assertIn("disabled", options[0]["attributes"])
        self.assertIn("failed", report.tables[0][0][8])
        self.assertTrue(all("hidden" not in section["attributes"] for section in report.sections))

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
            comparable_record(phase="cold", total_seconds=None),
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
        self.assertFalse(any(tag in ("img", "iframe") for tag, _ in report.tags))
        self.assertEqual(len(report.scripts), 2)
        self.assertFalse(any(key.lower().startswith("on") for _, attributes in report.tags for key in attributes))
        self.assertFalse(any("src" in script["attributes"] for script in report.scripts))

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
        self.assertFalse(any(tag in ("svg", "link", "iframe") for tag, _ in report.tags))
        self.assertEqual(len(report.scripts), 2)
        self.assertEqual(report.data, {"latest_scope": None, "scopes": [], "comparisons": {}})
        self.assertIn("No benchmark runs match", report.text)


if __name__ == "__main__":
    unittest.main()
