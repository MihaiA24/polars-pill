import contextlib
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import benchmark_profiling
from benchmark_profiling import MemoryProfiler


class MemoryProfilerTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.proc = self.root / "proc"
        self.proc.mkdir()
        self.pid = os.getpid()
        self.native_page_size = os.sysconf("SC_PAGE_SIZE")
        self.child_pid = self.pid + 100000
        self.grandchild_pid = self.pid + 100001
        self.write_process(self.pid, 7, children=(self.child_pid,))
        self.write_process(self.child_pid, 11, children=(self.grandchild_pid,))
        self.write_process(self.grandchild_pid, 13)
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(benchmark_profiling, "_PROC_ROOT", self.proc))
        self.stack.enter_context(patch.object(benchmark_profiling.os, "sysconf", return_value=4096))

    def write_process(self, pid, pages, *, children=(), start_time=42):
        process = self.proc / str(pid)
        process.mkdir(exist_ok=True)
        # Fields 3 through 24, with deliberately awkward parentheses in comm.
        fields = ["S", str(self.pid)] + ["0"] * 17 + [str(start_time), "0", str(pages)]
        (process / "stat").write_text(f"{pid} (fixture (JVM) worker) {' '.join(fields)}\n")
        task = process / "task" / str(pid)
        task.mkdir(parents=True, exist_ok=True)
        (task / "children").write_text(" ".join(map(str, children)))

    def gpu_command(self, output="", *, exit_code=0, sleep=0, before_output=""):
        marker = self.root / f"gpu-{time.monotonic_ns()}.pid"
        command = self.root / "nvidia-smi"
        command.write_text(
            f"#!{sys.executable}\n"
            "import os, time\n"
            "from pathlib import Path\n"
            f"Path({str(marker)!r}).write_text(str(os.getpid()))\n"
            f"time.sleep({sleep!r})\n"
            f"{before_output}\n"
            f"print({output!r}, end='')\n"
            f"raise SystemExit({exit_code})\n"
        )
        command.chmod(0o755)
        self.stack.enter_context(patch.object(benchmark_profiling.shutil, "which", return_value=str(command)))
        return marker

    def profile_gpu(self, output="", *, exit_code=0, sleep=0, before_output="", interval_seconds=60):
        marker = self.gpu_command(output, exit_code=exit_code, sleep=sleep, before_output=before_output)
        profiler = MemoryProfiler(True, interval_seconds=interval_seconds)
        self.addCleanup(profiler.stop)
        profiler.start()
        deadline = time.monotonic() + 5
        while not marker.exists() or not marker.read_text():
            if time.monotonic() >= deadline:
                self.fail("GPU probe did not start")
            time.sleep(0.005)
        return profiler, marker

    def test_disabled_never_touches_probe_resources(self):
        with (
            patch.object(Path, "read_text", side_effect=AssertionError("read /proc")),
            patch.object(Path, "iterdir", side_effect=AssertionError("listed /proc")),
            patch.object(benchmark_profiling.shutil, "which", side_effect=AssertionError("searched PATH")),
            patch.object(benchmark_profiling.os, "sysconf", side_effect=AssertionError("queried page size")),
            patch.object(threading, "Thread", side_effect=AssertionError("started sampler")),
            patch.object(subprocess, "run", side_effect=AssertionError("spawned process")),
        ):
            profiler = MemoryProfiler(False)
            profiler.start()
            record = profiler.stop()
            self.assertEqual(record, profiler.stop())
        self.assertFalse(record["enabled"])
        self.assertIsNone(record["peak_rss_bytes"])
        self.assertIsNone(record["peak_gpu_memory_bytes"])
        self.assertEqual((record["rss_samples"], record["gpu_samples"]), (0, 0))
        self.assertEqual(record["errors"], [])

    def test_live_tree_includes_grandchildren_and_children_of_other_threads(self):
        thread = self.proc / str(self.pid) / "task" / str(self.pid + 1)
        thread.mkdir()
        other_child = self.pid + 100002
        (thread / "children").write_text(str(other_child))
        self.write_process(other_child, 17)
        profiler, _ = self.profile_gpu()
        record = profiler.stop()
        self.assertEqual(record["peak_rss_bytes"], 48 * 4096)
        self.assertEqual(record["rss_samples"], 1)
        self.assertEqual(record["peak_gpu_memory_bytes"], 0)
        self.assertEqual(record["gpu_samples"], 1)
        self.assertEqual(record["errors"], [])
        self.assertEqual(record, profiler.stop())

    def test_zero_usage_is_a_successful_measurement_not_missing_data(self):
        self.write_process(self.pid, 0, children=(self.child_pid,))
        self.write_process(self.child_pid, 0, children=(self.grandchild_pid,))
        self.write_process(self.grandchild_pid, 0)
        profiler, _ = self.profile_gpu()
        record = profiler.stop()
        self.assertEqual((record["peak_rss_bytes"], record["peak_gpu_memory_bytes"]), (0, 0))
        self.assertEqual((record["rss_samples"], record["gpu_samples"]), (1, 1))
        self.assertEqual(record["errors"], [])

    def test_exited_child_is_not_an_unavailable_probe(self):
        self.write_process(self.pid, 7, children=(self.child_pid, self.pid + 100003))
        profiler, _ = self.profile_gpu()
        record = profiler.stop()
        self.assertEqual(record["peak_rss_bytes"], 31 * 4096)
        self.assertEqual(record["errors"], [])

    def test_repeated_samples_keep_earlier_rss_and_gpu_peaks(self):
        stat_path = self.proc / str(self.child_pid) / "stat"
        self.write_process(self.child_pid, 71, children=(self.grandchild_pid,))
        high_stat = stat_path.read_text()
        self.write_process(self.child_pid, 3, children=(self.grandchild_pid,))
        low_stat = stat_path.read_text()
        self.write_process(self.child_pid, 11, children=(self.grandchild_pid,))
        sample_count = self.root / "gpu-sample-count"
        script = (
            f"count_path = Path({str(sample_count)!r})\n"
            "count = int(count_path.read_text()) + 1 if count_path.exists() else 1\n"
            f"Path({str(stat_path)!r}).write_text({high_stat!r} if count == 1 else {low_stat!r})\n"
            f"print('{self.pid}, GPU-a, ' + ('9' if count == 1 else '2'))\n"
            "count_path.with_suffix('.next').write_text(str(count))\n"
            "count_path.with_suffix('.next').replace(count_path)"
        )
        profiler, _ = self.profile_gpu(before_output=script, interval_seconds=0.01)
        deadline = time.monotonic() + 5
        while not sample_count.exists() or not sample_count.read_text() or int(sample_count.read_text()) < 3:
            if time.monotonic() >= deadline:
                self.fail("Sampler did not observe the high and subsequent low allocations")
            time.sleep(0.005)
        record = profiler.stop()
        self.assertEqual(record["peak_rss_bytes"], 91 * 4096)
        self.assertEqual(record["peak_gpu_memory_bytes"], 9437184)
        self.assertGreaterEqual(record["rss_samples"], 3)
        self.assertGreaterEqual(record["gpu_samples"], 3)
        self.assertEqual(record["errors"], [])

    def test_gpu_sum_is_pid_scoped_across_devices(self):
        profiler, _ = self.profile_gpu(
            f"{self.pid}, GPU-a, 2.5\n"
            f"{self.child_pid}, GPU-a, 3\n"
            f"{self.child_pid}, GPU-b, 7\n"
            "999999999, GPU-a, 900000\n"
            "999999998, GPU-b, [N/A]\n"
        )
        record = profiler.stop()
        self.assertEqual(record["peak_gpu_memory_bytes"], 13107200)
        self.assertEqual(record["gpu_samples"], 1)
        self.assertEqual(record["errors"], [])
        self.assertGreaterEqual(record["gpu_interval_seconds"], record["interval_seconds"])

    def test_pid_reuse_during_gpu_query_cannot_charge_unrelated_allocation(self):
        self.write_process(self.child_pid, 11, children=(self.grandchild_pid,), start_time=99)
        stat_path = self.proc / str(self.child_pid) / "stat"
        replacement = stat_path.read_text()
        self.write_process(self.child_pid, 11, children=(self.grandchild_pid,))
        profiler, _ = self.profile_gpu(
            f"{self.child_pid}, GPU-a, 128\n", before_output=f"Path({str(stat_path)!r}).write_text({replacement!r})"
        )
        record = profiler.stop()
        self.assertIsNone(record["peak_gpu_memory_bytes"])
        self.assertEqual(record["gpu_samples"], 0)
        self.assertTrue(any("identity" in error for error in record["errors"]))

    def test_invalid_gpu_rows_are_unavailable_not_zero(self):
        for output in (
            f"{self.pid}, GPU-a, [N/A]\n",
            f"{self.pid}, GPU-a, -1\n",
            f"{self.pid}, GPU-a, NaN\n",
            f"{self.pid}, GPU-a, Infinity\n",
            f"{self.pid}, GPU-a\n",
            "not-a-pid, GPU-a, 1\n",
            f"{self.pid}, , 1\n",
            f"{self.pid}, [Unknown Error], 1\n",
            f"{self.pid}, GPU-a, 1\n{self.pid}, GPU-a, 1\n",
        ):
            with self.subTest(output=output):
                profiler, _ = self.profile_gpu(output)
                record = profiler.stop()
                self.assertIsNone(record["peak_gpu_memory_bytes"])
                self.assertEqual(record["gpu_samples"], 0)
                self.assertTrue(any("GPU" in error for error in record["errors"]))
                self.assertEqual(record["peak_rss_bytes"], 31 * 4096)

    def test_missing_gpu_executable_keeps_rss_and_explicit_unavailability(self):
        with patch.object(benchmark_profiling.shutil, "which", return_value=None):
            profiler = MemoryProfiler(True, interval_seconds=60)
            self.addCleanup(profiler.stop)
            profiler.start()
            record = profiler.stop()
        self.assertEqual(record["peak_rss_bytes"], 31 * 4096)
        self.assertIsNone(record["peak_gpu_memory_bytes"])
        self.assertEqual(record["gpu_samples"], 0)
        self.assertTrue(any("nvidia-smi" in error for error in record["errors"]))

    def test_invalid_or_incomplete_process_tree_never_becomes_partial_peak(self):
        for missing_file, contents in (("stat", "malformed"), ("task", None)):
            with self.subTest(missing_file=missing_file):
                self.write_process(self.child_pid, 11, children=(self.grandchild_pid,))
                target = self.proc / str(self.child_pid) / missing_file
                if contents is None:
                    (target / str(self.child_pid) / "children").unlink()
                else:
                    target.write_text(contents)
                with patch.object(benchmark_profiling.shutil, "which", return_value=None):
                    profiler = MemoryProfiler(True, interval_seconds=60)
                    self.addCleanup(profiler.stop)
                    profiler.start()
                    record = profiler.stop()
                self.assertIsNone(record["peak_rss_bytes"])
                self.assertEqual(record["rss_samples"], 0)
                self.assertTrue(any("RSS" in error for error in record["errors"]))

    def test_nonzero_gpu_exit_is_metadata_error(self):
        profiler, _ = self.profile_gpu("", exit_code=7)
        record = profiler.stop()
        self.assertIsNone(record["peak_gpu_memory_bytes"])
        self.assertEqual(record["gpu_samples"], 0)
        self.assertTrue(any("GPU" in error and "7" in error for error in record["errors"]))

    def test_timeout_and_stop_reap_probe_and_sampler_even_during_exception(self):
        threads_before = set(threading.enumerate())
        profiler, marker = self.profile_gpu(sleep=60)
        probe_pid = int(marker.read_text())
        started = time.monotonic()
        try:
            raise RuntimeError("workload failed")
        except RuntimeError:
            record = profiler.stop()
        self.assertLess(time.monotonic() - started, 4)
        self.assertEqual(set(threading.enumerate()) - threads_before, set())
        with self.assertRaises(ProcessLookupError):
            os.kill(probe_pid, 0)
        self.assertIsNone(record["peak_gpu_memory_bytes"])
        self.assertEqual(record["gpu_samples"], 0)
        self.assertTrue(any("GPU" in error and "timeout" in error.lower() for error in record["errors"]))
        self.assertEqual(record, profiler.stop())

    @unittest.skipUnless(sys.platform == "linux" and Path("/proc/self/stat").exists(), "requires Linux /proc")
    def test_real_child_and_grandchild_allocations_raise_process_tree_rss(self):
        self.stack.enter_context(patch.object(benchmark_profiling, "_PROC_ROOT", Path("/proc")))
        self.stack.enter_context(patch.object(benchmark_profiling.shutil, "which", return_value=None))
        self.stack.enter_context(patch.object(benchmark_profiling.os, "sysconf", return_value=self.native_page_size))
        baseline = MemoryProfiler(True, interval_seconds=60)
        baseline.start()
        baseline_record = baseline.stop()
        allocation = 48 * 1024 * 1024
        script = self.root / "allocate.py"
        script.write_text(
            "import subprocess, sys\n"
            f"memory = bytearray({allocation})\n"
            "for offset in range(0, len(memory), 4096): memory[offset] = 1\n"
            "child = None\n"
            "if len(sys.argv) == 1:\n"
            "    child = subprocess.Popen([sys.executable, __file__, 'grandchild'], "
            "stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)\n"
            "    assert child.stdout.readline().strip() == 'ready'\n"
            "print('ready', flush=True)\n"
            "try:\n"
            "    sys.stdin.read()\n"
            "finally:\n"
            "    if child is not None:\n"
            "        child.stdin.close()\n"
            "        child.wait(timeout=5)\n"
        )
        process = subprocess.Popen(
            [sys.executable, str(script)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True
        )
        try:
            self.assertEqual(process.stdout.readline().strip(), "ready")
            profiler = MemoryProfiler(True, interval_seconds=60)
            self.addCleanup(profiler.stop)
            profiler.start()
            record = profiler.stop()
            self.assertGreaterEqual(record["peak_rss_bytes"] - baseline_record["peak_rss_bytes"], allocation * 2)
            self.assertEqual(record["errors"], baseline_record["errors"])
        finally:
            process.stdin.close()
            process.wait(timeout=10)
            process.stdout.close()


if __name__ == "__main__":
    unittest.main()
