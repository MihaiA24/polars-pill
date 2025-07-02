def save_execution_time(library, file, duration):
    with open("benchmark.txt", "a") as f:
        f.write(f"{library} | {file} | {duration} seconds \n")
