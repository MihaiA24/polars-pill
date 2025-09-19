from pathlib import Path

# Fixed column widths
w_lib = 16
w_time = 22
w_cpu_gpu = 8
w_engine = 12
w_dataset = 25
w_query = 12


def file_header() -> tuple[str, str]:
    # Build a separator row for Markdown with alignment markers using widths
    def _md_separator(width):
        return "-" * (width + 2)

    header = (
        f"| {'Library':<{w_lib}} | {'Duration (s)':>{w_time}} | "
        f"{'CPU/GPU':<{w_cpu_gpu}} | {'Engine':<{w_engine}} | {'Dataset':<{w_dataset}} | {'Query':<{w_query}} |\n"
    )

    sep_parts = [
        _md_separator(w_lib),
        _md_separator(w_time),
        _md_separator(w_cpu_gpu),
        _md_separator(w_engine),
        _md_separator(w_dataset),
        _md_separator(w_query),
    ]
    separator = "|" + "|".join(f"{part}" for part in sep_parts) + "| \n"
    return header, separator


def save_execution_time(library, duration, cpu_gpu, engine, dataset, execution_query):
    path = Path("benchmark.txt")
    is_new_file = not path.exists() or path.stat().st_size == 0

    header, separator = file_header()
    if type(duration) is float:
        duration = '{:.3f}'.format(duration)
    line = (
        f"| {library:<{w_lib}} | {duration:>{w_time}} | "
        f"{cpu_gpu:<{w_cpu_gpu}} | {engine:<{w_engine}} | {dataset:<{w_dataset}} | {execution_query:<{w_query}} |\n"
    )

    with path.open("a", encoding="utf-8") as f:
        if is_new_file:
            f.write(header)
            f.write(separator)
        f.write(line)


def remove_benchmark_table():
    readme_path = Path("README.md")
    lines = readme_path.read_text(encoding="utf-8").splitlines()

    new_lines = []

    header, _ = file_header()

    for line in lines:
        if line == header.rstrip("\r\n"):
            break  # Found the header, stop processing. Benchmark table is the last one in README
        new_lines.append(line)
    # Write back cleaned README without the benchmark table
    readme_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def append_benchmark_to_readme(remove_table_from_readme: bool = True):
    if remove_table_from_readme:
        remove_benchmark_table()

    bench_path = Path("benchmark.txt")
    readme_path = Path("README.md")

    # Read benchmark content
    bench_content = bench_path.read_text(encoding="utf-8")

    # Append to README.md with a preceding newline for separation
    with readme_path.open("a", encoding="utf-8") as readme_file:
        readme_file.write(bench_content)
        readme_file.write("\n")
