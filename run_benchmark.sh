#!/usr/bin/env zsh

files=(
   pandas_evaluation.py
   eager_evaluation.py
   lazy_evaluation.py
   pyspark_evaluation.py
)

file_path_20M="data/2019-Oct-20M.csv"
file_path="data/2019-Oct.csv"

# shellcheck disable=SC2128
for script  in $files; do
	echo "Running $script..."
	start_time=$(date +%s.%N)
	python "$script" $file_path
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
