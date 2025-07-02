#!/bin/bash
file_path_20M="data/2019-Oct-20M.csv"
file_path="data/2019-Oct.csv"
file_path_parquet="data/2019-Oct.parquet"

commands=(
  "pandas_evaluation.py --file_path $file_path_20M"
  "eager_evaluation.py --file_path $file_path_20M"
  "eager_evaluation.py --file_path $file_path"
  "eager_evaluation.py --file_path $file_path_parquet --file_type parquet"
  "lazy_evaluation.py --file_path $file_path"
  "lazy_evaluation.py --file_path $file_path_parquet --file_type parquet"
  "pyspark_evaluation.py --file_path $file_path"
  "pyspark_evaluation.py --file_path $file_path_parquet --file_type parquet"
)

rm benchmark.txt
for command in "${commands[@]}"; do
	echo "Running $command..."
	start_time=$(date +%s.%N)
  eval "python $command"
#	echo "$script"
	exit_code=$?
	end_time=$(date +%s.%N)
	duration=$(echo "$end_time - $start_time" | bc -l)
  # Store result
  if [[ $exit_code -eq 0 ]]; then
      printf "✓ Completed in %.4f seconds\n" "$duration"
  else
      echo "✗ Script failed with exit code: $exit_code"
  fi
done
