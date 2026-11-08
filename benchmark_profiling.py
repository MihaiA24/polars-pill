"""Optional sampled process-tree peaks, not instantaneous allocation high-water marks."""

import csv
import io
import math
import os
import shutil
import subprocess
import threading
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path

_PROC_ROOT = Path("/proc")
_GPU_TIMEOUT_SECONDS = 1.0


def _process_stat(pid):
    text = (_PROC_ROOT / str(pid) / "stat").read_text()
    pid_text, opening, remainder = text.partition("(")
    _, closing, tail = remainder.rpartition(")")
    fields = tail.split()
    if not opening or not closing or int(pid_text) != pid or len(fields) < 22:
        raise ValueError(f"invalid stat for PID {pid}")
    start_time, rss_pages = int(fields[19]), int(fields[21])
    if start_time < 0 or rss_pages < 0:
        raise ValueError(f"negative process data for PID {pid}")
    return start_time, rss_pages


def _process_tree(root_pid):
    """Read every thread's children: JVMs need not be launched by the main thread."""
    pending = [root_pid]
    identities = {}
    rss_pages = 0
    while pending:
        pid = pending.pop()
        if pid in identities:
            continue
        process = _PROC_ROOT / str(pid)
        try:
            start_time, pages = _process_stat(pid)
            children = []
            for task in (process / "task").iterdir():
                if not task.name.isdecimal():
                    continue
                try:
                    child_pids = (task / "children").read_text().split()
                except FileNotFoundError:
                    if task.exists():
                        raise
                    continue  # A thread exited while its process remained alive.
                for value in child_pids:
                    child_pid = int(value)
                    if child_pid <= 0:
                        raise ValueError(f"invalid child PID for PID {pid}")
                    children.append(child_pid)
        except FileNotFoundError:
            if pid == root_pid or process.exists():
                raise
            continue  # An exited child is no longer part of the live tree.
        identities[pid] = start_time
        rss_pages += pages
        pending.extend(children)
    return identities, rss_pages


def _gpu_memory_bytes(output, identities):
    total = 0
    seen = set()
    verified = set()
    for row in csv.reader(io.StringIO(output), strict=True):
        if not row or all(not value.strip() for value in row):
            continue
        pid = int(row[0].strip())
        if pid <= 0:
            raise ValueError("invalid GPU process PID")
        if pid not in identities:
            continue  # Unrelated processes, including their unsupported fields, do not count.
        if len(row) != 3:
            raise ValueError(f"invalid GPU memory row for PID {pid}")
        gpu_uuid = row[1].strip()
        if not gpu_uuid.startswith(("GPU-", "MIG-")):
            raise ValueError(f"unavailable GPU UUID for PID {pid}")
        key = (pid, gpu_uuid)
        if key in seen:
            raise ValueError(f"duplicate GPU process/device row for PID {pid}")
        seen.add(key)
        try:
            memory_mib = Decimal(row[2].strip())
        except InvalidOperation as error:
            raise ValueError(f"unavailable GPU memory for PID {pid}") from error
        if not memory_mib.is_finite() or memory_mib < 0:
            raise ValueError(f"invalid GPU memory for PID {pid}")
        if pid not in verified:
            # Do not attribute a reused PID's GPU allocation to the old child.
            if _process_stat(pid)[0] != identities[pid]:
                raise ValueError(f"PID {pid} changed identity during GPU sampling")
            verified.add(pid)
        total += int(memory_mib * 1024 * 1024)
    return total


class MemoryProfiler:
    """Single-use sampler; callers must stop it in a finally block around execution.

    RSS includes a baseline at start and live descendants, including Spark JVMs.
    Shared pages can be counted more than once. GPU queries run less frequently
    (at least 0.5 seconds apart) to limit subprocess overhead. The single worker
    never counts its own nvidia-smi helper in an RSS snapshot. Probe runtime adds
    to the requested pauses, so short-lived allocations can be missed.
    """

    def __init__(self, enabled: bool, interval_seconds: float = 0.05):
        interval_seconds = float(interval_seconds)
        if not math.isfinite(interval_seconds) or interval_seconds <= 0:
            raise ValueError("memory sampling interval must be finite and positive")
        self.enabled = bool(enabled)
        self.interval_seconds = interval_seconds
        self.gpu_interval_seconds = max(0.5, interval_seconds)
        self._stop_event = threading.Event()
        self._ready = threading.Event()
        self._thread = None
        self._started = False
        self._stopped = False
        self._root_pid = None
        self._page_size = None
        self._gpu_command = None
        self._peak_rss_bytes = None
        self._peak_gpu_memory_bytes = None
        self._rss_samples = 0
        self._gpu_samples = 0
        self._errors = []

    def _error(self, message):
        if message not in self._errors:
            self._errors.append(message)

    def start(self):
        if not self.enabled or self._started or self._stopped:
            return self
        self._started = True
        self._root_pid = os.getpid()
        try:
            self._page_size = os.sysconf("SC_PAGE_SIZE")
            if self._page_size <= 0:
                raise ValueError("invalid operating-system page size")
        except (AttributeError, OSError, ValueError) as error:
            self._page_size = None
            self._error(f"RSS probe unavailable: {type(error).__name__}: {error}")
        try:
            self._gpu_command = shutil.which("nvidia-smi")
            if self._gpu_command is None:
                self._error("GPU probe unavailable: nvidia-smi not found")
        except (OSError, ValueError) as error:
            self._error(f"GPU probe unavailable: {type(error).__name__}: {error}")
        try:
            self._thread = threading.Thread(target=self._run, name="benchmark-memory-profiler", daemon=True)
            self._thread.start()
        except (OSError, RuntimeError) as error:
            self._thread = None
            self._error(f"Memory sampler unavailable: {type(error).__name__}: {error}")
            return self
        self._ready.wait()
        return self

    def _sample_gpu(self, identities):
        try:
            # NVIDIA documents selective compute-process queries and CSV formatting:
            # https://docs.nvidia.com/deploy/nvidia-smi/index.html#selective-query-options
            result = subprocess.run(
                [
                    self._gpu_command,
                    "--query-compute-apps=pid,gpu_uuid,used_gpu_memory",
                    "--format=csv,noheader,nounits",
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=_GPU_TIMEOUT_SECONDS,
            )
            value = _gpu_memory_bytes(result.stdout, identities)
        except subprocess.TimeoutExpired:
            self._error(f"GPU probe timeout after {_GPU_TIMEOUT_SECONDS:g} seconds")
        except subprocess.CalledProcessError as error:
            detail = (error.stderr or error.stdout or "").strip()[:500]
            self._error(f"GPU probe failed: nvidia-smi exited with status {error.returncode}: {detail}")
        except (OSError, ValueError, OverflowError, csv.Error) as error:
            self._error(f"GPU probe failed: {type(error).__name__}: {error}")
        else:
            self._gpu_samples += 1
            self._peak_gpu_memory_bytes = max(self._peak_gpu_memory_bytes or 0, value)

    def _run(self):
        next_gpu_sample = 0.0
        try:
            while not self._stop_event.is_set():
                identities = None
                try:
                    identities, rss_pages = _process_tree(self._root_pid)
                    if self._page_size is not None:
                        value = rss_pages * self._page_size
                        self._rss_samples += 1
                        self._peak_rss_bytes = max(self._peak_rss_bytes or 0, value)
                except (OSError, ValueError) as error:
                    self._error(f"RSS process-tree probe failed: {type(error).__name__}: {error}")
                    if self._gpu_command is not None:
                        self._error("GPU probe unavailable: complete live process tree could not be read")
                self._ready.set()
                if (
                    identities is not None
                    and self._gpu_command is not None
                    and not self._stop_event.is_set()
                    and time.monotonic() >= next_gpu_sample
                ):
                    self._sample_gpu(identities)
                    next_gpu_sample = time.monotonic() + self.gpu_interval_seconds
                if self._stop_event.wait(self.interval_seconds):
                    break
        except (OSError, ValueError, RuntimeError, OverflowError, csv.Error) as error:
            self._error(f"Memory sampler failed: {type(error).__name__}: {error}")
        finally:
            self._ready.set()

    def stop(self):
        if not self._stopped:
            self._stop_event.set()
            if self._thread is not None:
                self._thread.join()
            self._stopped = True
            if (
                self.enabled
                and self._started
                and self._gpu_command is not None
                and not self._gpu_samples
                and not any("GPU" in error for error in self._errors)
            ):
                self._error("GPU probe unavailable: sampling stopped before a completed GPU sample")
        return {
            "enabled": self.enabled,
            "interval_seconds": self.interval_seconds,
            "gpu_interval_seconds": self.gpu_interval_seconds,
            "peak_rss_bytes": self._peak_rss_bytes,
            "peak_gpu_memory_bytes": self._peak_gpu_memory_bytes,
            "rss_samples": self._rss_samples,
            "gpu_samples": self._gpu_samples,
            "errors": list(self._errors),
            "method": "sampled peaks; probe runtime adds to requested sampling intervals",
            "rss_scope": (
                "execute-attempt live process-tree RSS including pre-execute baseline; "
                "shared pages may be double-counted"
            ),
            "gpu_scope": "live process-tree PIDs; sum of visible compute-process memory across GPU devices",
        }
