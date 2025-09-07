import re
from pathlib import Path


def save_execution_time(library, duration, cpu_gpu, engine, dataset, execution_query):
    # Fixed column widths
    w_lib = 16
    w_time = 18
    w_cpu_gpu = 8
    w_engine = 12
    w_dataset = 25  # Adjusted width to replace the file column width
    w_query = 12

    path = Path("benchmark.txt")
    is_new_file = not path.exists() or path.stat().st_size == 0

    header = (
        f"{'Library':<{w_lib}} | {'Duration (s)':>{w_time}} | "
        f"{'CPU/GPU':<{w_cpu_gpu}} | {'Engine':<{w_engine}} | {'Dataset':<{w_dataset}} | {'Query':<{w_query}}\n"
    )
    separator = "-" * (len(header) - 1) + "\n"

    line = (
        f"{library:<{w_lib}} | {'{:.3f}'.format(duration):>{w_time}} | "
        f"{cpu_gpu:<{w_cpu_gpu}} | {engine:<{w_engine}} | {dataset:<{w_dataset}} | {execution_query:<{w_query}}\n"
    )

    with path.open("a", encoding="utf-8") as f:
        if is_new_file:
            f.write(header)
            f.write(separator)
        f.write(line)
