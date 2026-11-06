#!/usr/bin/env python3
"""Run the fixed benchmark matrix with an inline dashboard or streaming output."""

import argparse
import errno
import os
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4


@dataclass(frozen=True)
class Operation:
    phase: str
    command: tuple[str, ...]
    benchmark: bool = False

    @property
    def workload(self):
        if not self.benchmark:
            return "Environment synchronization" if self.command[1] == "sync" else "Generate benchmark report"
        args = self.command[2:]
        options = dict(zip(args[::2], args[1::2]))
        engine = {"polars": "Polars", "duckdb": "DuckDB", "pandas": "pandas", "pyspark": "PySpark"}[
            self.command[1].removesuffix("_evaluation.py")
        ]
        dataset = options.get("--dataset_type", options.get("--file_path", ""))
        details = [options[key] for key in ("--mode", "--engine", "--execution_query") if key in options]
        if "--gpu_engine" in options:
            details.append("GPU" if options["--gpu_engine"] == "True" else "CPU")
        return " | ".join([engine, dataset, *details])


def operations(warmups, repetitions, *, datasets=None, queries=None, device="all"):
    """Preserve the CPU, same-version baseline, and GPU matrix ordering."""
    counts = ("--warmups", warmups, "--repetitions", repetitions)

    def benchmark(phase, script, *args):
        return Operation(phase, (".venv/bin/python", script + "_evaluation.py", *args, *counts), True)

    ecommerce = (
        ("--file_path", "data/2019-Oct-20M.csv", "--mode", "eager", "--engine", "in-memory"),
        ("--file_path", "data/2019-Oct.csv", "--mode", "eager", "--engine", "in-memory"),
        ("--file_path", "data/2019-Oct.parquet", "--file_type", "parquet", "--mode", "eager", "--engine", "in-memory"),
        ("--file_path", "data/2019-Oct.csv", "--mode", "lazy", "--engine", "in-memory"),
        ("--file_path", "data/2019-Oct.parquet", "--file_type", "parquet", "--mode", "lazy", "--engine", "in-memory"),
        ("--file_path", "data/2019-Oct.csv", "--mode", "lazy", "--engine", "streaming"),
        ("--file_path", "data/2019-Oct.parquet", "--file_type", "parquet", "--mode", "lazy", "--engine", "streaming"),
    )

    def polars_nyc(phase, dataset, gpu):
        return [
            benchmark(
                phase,
                "polars",
                "--dataset_type",
                dataset,
                "--engine",
                engine,
                "--gpu_engine",
                gpu,
                "--execution_query",
                query,
            )
            for engine in ("in-memory", "streaming")
            for query in ("simple", "complex", "filtered", "date-window")
        ]

    cpu = "CPU benchmarks"
    matrix = [Operation("CPU setup", ("uv", "sync", "--locked", "--group", "cpu_polars", "--no-dev"))]
    matrix.append(benchmark(cpu, "pandas", "--file_path", "data/2019-Oct-20M.csv"))
    for path in ("data/2019-Oct-20M.csv", "data/2019-Oct.csv", "data/2019-Oct.parquet"):
        file_type = ("--file_type", "parquet") if path.endswith(".parquet") else ()
        matrix.append(benchmark(cpu, "duckdb", "--file_path", path, *file_type))
    matrix.extend(benchmark(cpu, "polars", *args) for args in ecommerce)
    for path in ("data/2019-Oct.csv", "data/2019-Oct.parquet"):
        file_type = ("--file_type", "parquet") if path.endswith(".parquet") else ()
        matrix.append(benchmark(cpu, "pyspark", "--file_path", path, *file_type))
    for dataset in ("nyc-green", "nyc-yellow"):
        matrix.extend(polars_nyc(cpu, dataset, "False"))
        for script in ("pyspark", "duckdb"):
            for query in ("simple", "complex", "filtered", "date-window"):
                matrix.append(benchmark(cpu, script, "--dataset_type", dataset, "--execution_query", query))
    matrix.append(Operation("GPU setup", ("uv", "sync", "--locked", "--group", "gpu_polars", "--no-dev")))
    baseline = "GPU-version CPU baselines"
    matrix.extend(benchmark(baseline, "polars", *args) for args in ecommerce)
    for dataset in ("nyc-green", "nyc-yellow"):
        matrix.extend(polars_nyc(baseline, dataset, "False"))
    for dataset in ("nyc-green", "nyc-yellow"):
        matrix.extend(polars_nyc("GPU benchmarks", dataset, "True"))
    selected = []
    setup = None
    last_setup = None
    for operation in matrix:
        if not operation.benchmark:
            setup = operation
            continue
        options = dict(zip(operation.command[2::2], operation.command[3::2]))
        dataset = options.get("--dataset_type", "ecommerce")
        query = options.get("--execution_query", "simple")
        execution_device = "gpu" if options.get("--gpu_engine") == "True" else "cpu"
        if (
            (datasets is not None and dataset not in datasets)
            or (queries is not None and query not in queries)
            or (device != "all" and execution_device != device)
        ):
            continue
        if setup != last_setup:
            selected.append(setup)
            last_setup = setup
        selected.append(operation)
    if selected:
        group = last_setup.command[last_setup.command.index("--group") + 1]
        selected.append(
            Operation("Report", ("uv", "run", "--locked", "--group", group, "python", "plot_benchmarks.py"))
        )
    return selected


def elapsed(seconds):
    total_ms = max(0, round(seconds * 1000))
    seconds, milliseconds = divmod(total_ms, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}.{milliseconds:03} ({total_ms:,} ms)"


class Dashboard:
    def __init__(self, live, total, suite):
        self.live = live
        self.colors = live and not os.environ.get("NO_COLOR")
        self.total = total
        self.suite = suite
        self.started = time.monotonic()
        self.active_started = self.started
        self.active = None
        self.completed = 0
        self.passed = 0
        self.failed = 0
        self.cancelled = 0
        self.recent = deque(maxlen=4)
        self.rows = 0
        self.size = None

    def clear(self):
        if self.rows:
            sys.stdout.write(f"\033[{self.rows}F\033[J")
            self.rows = 0

    def render(self, outcome=None):
        if not self.live:
            return
        columns, height = shutil.get_terminal_size((80, 24))
        if self.size != (columns, height) and self.rows:
            # Reflow changes old row positions; leave that frame in scrollback.
            sys.stdout.write("\n")
            self.rows = 0
        self.size = (columns, height)
        width = max(1, columns - 1)
        available = max(1, height - 1)
        now = time.monotonic()
        phase = self.active.phase if self.active else (outcome or "Complete")
        counts = f"{self.passed} passed | {self.failed} failed"
        if self.cancelled:
            counts += f" | {self.cancelled} interrupted"
        percentage = 100 * self.completed / self.total
        bar_width = min(28, max(0, width - 22 - 2 * len(str(self.total))))
        if bar_width:
            filled = bar_width * self.completed // self.total
            bar = "#" * filled + "-" * (bar_width - filled)
            progress = f"Progress: [{bar}] {percentage:5.1f}%  {self.completed}/{self.total}"
        else:
            progress = f"Progress: {self.completed}/{self.total} ({percentage:.1f}%)"
        spacious = available >= 16
        lines = ["Benchmark suite  " + self.suite]
        if spacious:
            lines.extend(["-" * width, ""])
        lines.extend([progress, f"{'Results:':<10}{counts}"])
        if spacious:
            lines.append("")
        lines.extend(
            [
                f"{'Active:':<10}{elapsed(now - self.active_started) if self.active else '--:--:--.---'}",
                f"{'Total:':<10}{elapsed(now - self.started)}",
            ]
        )
        if spacious:
            lines.append("")
        if self.active:
            marker = "|/-\\"[int((now - self.active_started) * 10) % 4]
            phase = f"{marker} {phase}"
        fields = [("Phase:", phase)]
        if self.active:
            fields.extend([("Workload:", self.active.workload), ("Command:", shlex.join(self.active.command))])
        for label, value in fields:
            # Keep continuation lines aligned without triggering terminal autowrap.
            lines.extend(
                textwrap.wrap(
                    f"{label:<10}{value}",
                    width=width,
                    subsequent_indent=" " * min(10, width - 1),
                    replace_whitespace=False,
                    drop_whitespace=False,
                )
            )
        room = available - len(lines)
        if self.recent and room >= 3:
            lines.extend(["", "Recent outcomes:"])
            lines.extend(f"  {result}" for result in list(self.recent)[-(room - 2) :])
        self.clear()
        for line in lines[:available]:
            visible = "".join(char if char.isascii() and char.isprintable() else "?" for char in line)
            style = ""
            if self.colors:
                status_line = line.lstrip()
                if status_line.startswith("FAIL"):
                    style = "\033[31m"
                elif status_line.startswith("INTERRUPTED"):
                    style = "\033[33m"
                elif status_line.startswith("PASS"):
                    style = "\033[32m"
                elif line.startswith(("Phase:", "Progress:")):
                    if self.failed:
                        style = "\033[31m"
                    elif self.cancelled:
                        style = "\033[33m"
                    else:
                        style = "\033[36m"
                elif line.startswith("Benchmark suite"):
                    style = "\033[1m"
                elif line.startswith(("Active:", "Total:")):
                    style = "\033[2m"
            sys.stdout.write(style + visible[:width] + ("\033[0m" if style else "") + "\n")
        self.rows = min(len(lines), available)
        sys.stdout.flush()

    def start(self, operation):
        self.active = operation
        self.active_started = time.monotonic()
        if self.live:
            self.render()
        else:
            print(
                f"\n[{self.completed + 1}/{self.total}] {operation.phase}\n"
                f"\n  {'Workload:':<10}{operation.workload}\n"
                f"  {'Command:':<10}{shlex.join(operation.command)}\n",
                flush=True,
            )

    def complete(self, status, interrupted=False):
        duration = elapsed(time.monotonic() - self.active_started)
        outcome = "INTERRUPTED" if interrupted else ("PASS" if status == 0 else "FAIL")
        workload = self.active.workload
        if not self.active.benchmark:
            workload = f"{self.active.phase}: {workload}"
        result = f"{outcome:<11} ({status:>3})  {duration}  | {workload}"
        self.completed += 1
        self.passed += status == 0
        self.failed += status != 0 and not interrupted
        self.cancelled += interrupted
        self.recent.append(result)
        self.active = None
        if not self.live:
            print("\n  " + result, flush=True)

    def diagnostic(self, message):
        self.clear()
        sys.stdout.flush()
        print(message, file=sys.stderr, flush=True)

    def logs(self, capture):
        self.clear()
        print(f"--- {self.active.phase}: {self.active.workload} ---", flush=True)
        print("Command: " + shlex.join(self.active.command), flush=True)
        capture.seek(0)
        last = "\n"
        while chunk := capture.read(65536):
            sys.stdout.write(chunk)
            last = chunk[-1]
        if last != "\n":
            sys.stdout.write("\n")
        sys.stdout.flush()

    def finish(self, outcome):
        self.active = None
        if self.live:
            self.render(outcome)
        else:
            interruptions = f", {self.cancelled} interrupted" if self.cancelled else ""
            print(
                f"\n{outcome}",
                f"  {'Operations:':<12}{self.completed}/{self.total} completed",
                f"  {'Results:':<12}{self.passed} passed, {self.failed} failed{interruptions}",
                f"  {'Elapsed:':<12}{elapsed(time.monotonic() - self.started)}",
                f"  {'Suite:':<12}{self.suite}",
                sep="\n",
                flush=True,
            )
        self.rows = 0


def stop_group(process, signum):
    """Stop descendants too, even when the direct child exits before they do."""
    try:
        os.killpg(process.pid, signum)
    except ProcessLookupError:
        process.wait()
        return
    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline:
        process.poll()
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait()


def execute(operation, dashboard, environment, interrupted):
    # Plain mode inherits both streams: no buffering or terminal escapes are added.
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as capture:
        try:
            process = subprocess.Popen(
                operation.command,
                env=environment,
                start_new_session=True,
                stdout=capture if dashboard.live else None,
                stderr=subprocess.STDOUT if dashboard.live else None,
            )
        except OSError as error:
            dashboard.diagnostic(f"Cannot run {shlex.join(operation.command)}: {error}")
            return 127 if error.errno == errno.ENOENT else 126
        try:
            while process.poll() is None:
                if interrupted[0]:
                    break
                dashboard.render()
                time.sleep(0.1)
            if interrupted[0]:
                # A child can exit between receiving the signal and the next poll.
                stop_group(process, interrupted[0])
            status = 128 + interrupted[0] if interrupted[0] else process.returncode
            if status < 0:
                status = 128 - status
            if status and dashboard.live:
                dashboard.logs(capture)
            return status
        finally:
            if process.poll() is None:
                stop_group(process, signal.SIGTERM)


def main():
    parser = argparse.ArgumentParser(description="Run the locked CPU/GPU benchmark matrix and generate the report.")
    parser.add_argument(
        "--plain", action="store_true", help="Stream commands and child output without a live dashboard."
    )
    parser.add_argument(
        "--dataset", nargs="+", choices=("ecommerce", "nyc-green", "nyc-yellow"), help="Run only these datasets."
    )
    parser.add_argument(
        "--query",
        nargs="+",
        choices=("simple", "complex", "filtered", "date-window"),
        help="Run only these query workloads (ecommerce is simple).",
    )
    parser.add_argument("--device", choices=("cpu", "gpu", "all"), default="all", help="Filter execution devices.")
    parser.add_argument("--profile-memory", action="store_true", help="Sample process-tree RAM and GPU memory.")
    args = parser.parse_args()
    environment = os.environ.copy()
    counts = []
    for name, default, minimum in (("BENCHMARK_WARMUPS", "1", 0), ("BENCHMARK_REPETITIONS", "5", 1)):
        value = environment.get(name, default)
        if not value or any(char not in "0123456789" for char in value) or (minimum and not value.strip("0")):
            print(f"{name} must be an integer >= {minimum}", file=sys.stderr)
            return 2
        counts.append(value)
    matrix = operations(*counts, datasets=args.dataset, queries=args.query, device=args.device)
    if not matrix:
        parser.error("No benchmark workloads match the selected dataset, query, and device.")
    if args.profile_memory:
        environment["BENCHMARK_PROFILE_MEMORY"] = "1"
    venv = os.path.abspath(".venv")
    environment["VIRTUAL_ENV"] = venv
    environment["PATH"] = os.path.join(venv, "bin") + os.pathsep + environment.get("PATH", "")
    suite = environment.get("BENCHMARK_SUITE_ID") or uuid4().hex
    environment["BENCHMARK_SUITE_ID"] = suite
    environment["BENCHMARK_SUITE_STARTED_AT"] = datetime.now(UTC).isoformat()
    environment.pop("BENCHMARK_BATCH_ID", None)
    live = not args.plain and sys.stdout.isatty() and environment.get("TERM") != "dumb"
    dashboard = Dashboard(live, len(matrix), suite)
    interrupted = [0]

    def on_signal(signum, frame):
        if not interrupted[0]:
            interrupted[0] = signum

    previous = {signum: signal.signal(signum, on_signal) for signum in (signal.SIGINT, signal.SIGTERM)}
    benchmark_failed = False
    status = 0
    try:
        if live:
            sys.stdout.write("\033[?25l")
            sys.stdout.flush()
        for operation in matrix:
            if interrupted[0]:
                break
            dashboard.start(operation)
            if interrupted[0]:
                break
            operation_environment = environment.copy()
            if operation.benchmark:
                operation_environment["BENCHMARK_BATCH_ID"] = uuid4().hex
            result = execute(operation, dashboard, operation_environment, interrupted)
            dashboard.complete(result, bool(interrupted[0]))
            if interrupted[0]:
                break
            if result:
                if operation.benchmark:
                    benchmark_failed = True
                else:
                    status = result
                    if operation.phase.endswith("setup"):
                        dashboard.diagnostic("Environment setup failed; recorded JSON results are preserved.")
                    break
        status = 128 + interrupted[0] if interrupted[0] else (status or int(benchmark_failed))
        outcome = (
            f"Interrupted by {signal.Signals(interrupted[0]).name}"
            if interrupted[0]
            else ("Failed" if status else "Complete")
        )
        dashboard.finish(outcome)
        return status
    finally:
        if live:
            sys.stdout.write("\033[?25h")
            sys.stdout.flush()
        for signum, handler in previous.items():
            signal.signal(signum, handler)


if __name__ == "__main__":
    sys.exit(main())
