from pathlib import Path


def save_execution_time(library, file, duration):
    # Fixed column widths
    w_lib = 16
    w_file = 32
    w_time = 12

    path = Path("benchmark.txt")
    is_new_file = not path.exists() or path.stat().st_size == 0

    header = f"{'Library':<{w_lib}} | {'File':<{w_file}} | {'Duration (s)':>{w_time}}\n"
    separator = "-" * (len(header) - 1) + "\n"  # -1 to not count the header's newline

    line = f"{library:<{w_lib}} | {file:<{w_file}} | {duration:>{w_time}.3f}\n"

    with path.open("a", encoding="utf-8") as f:
        if is_new_file:
            f.write(header)
            f.write(separator)
        f.write(line)
