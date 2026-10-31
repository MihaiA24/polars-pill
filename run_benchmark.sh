#!/bin/bash
ecom_path_20M="data/2019-Oct-20M.csv"
ecom_path="data/2019-Oct.csv"
ecom_path_parquet="data/2019-Oct.parquet"

commands=(
   "source .venv/bin/activate"
   "python pandas_evaluation.py --file_path $ecom_path_20M"
   "python polars_evaluation.py --file_path $ecom_path_20M --mode eager"
   "python polars_evaluation.py --file_path $ecom_path --mode eager"
   "python polars_evaluation.py --file_path $ecom_path_parquet --file_type parquet --mode eager"
   "python polars_evaluation.py --file_path $ecom_path --mode lazy"
   "python polars_evaluation.py --file_path $ecom_path_parquet --file_type parquet --mode lazy"
   "python pyspark_evaluation.py --file_path $ecom_path"
   "python pyspark_evaluation.py --file_path $ecom_path_parquet --file_type parquet"

   # nyc green dataset
   "python polars_evaluation.py --dataset_type nyc-green --engine in-memory --gpu_engine False --execution_query simple"
   "python polars_evaluation.py --dataset_type nyc-green --engine in-memory --gpu_engine False --execution_query complex"

   "python polars_evaluation.py --dataset_type nyc-green --engine streaming --gpu_engine False --execution_query simple"
   "python polars_evaluation.py --dataset_type nyc-green --engine streaming --gpu_engine False --execution_query complex"

   "python pyspark_evaluation.py --dataset_type nyc-green --execution_query simple"
   "python pyspark_evaluation.py --dataset_type nyc-green --execution_query complex"

   # nyc yellow dataset
   "python polars_evaluation.py --dataset_type nyc-yellow --engine in-memory --gpu_engine False --execution_query simple"
   "python polars_evaluation.py --dataset_type nyc-yellow --engine in-memory --gpu_engine False --execution_query complex"

   "python polars_evaluation.py --dataset_type nyc-yellow --engine streaming --gpu_engine False --execution_query simple"
   "python polars_evaluation.py --dataset_type nyc-yellow --engine streaming --gpu_engine False --execution_query complex"

   "python pyspark_evaluation.py --dataset_type nyc-yellow --execution_query simple"
   "python pyspark_evaluation.py --dataset_type nyc-yellow --execution_query complex"

  # Change to GPU env
  "deactivate"
  "uv sync --locked --group gpu_polars --no-dev"
  "source .venv/bin/activate"
  # nyc green dataset
  "python polars_evaluation.py --dataset_type nyc-green --engine in-memory --gpu_engine True --execution_query simple"
  "python polars_evaluation.py --dataset_type nyc-green --engine in-memory --gpu_engine True --execution_query complex"

  "python polars_evaluation.py --dataset_type nyc-green --engine streaming --gpu_engine True --execution_query simple"
  "python polars_evaluation.py --dataset_type nyc-green --engine streaming --gpu_engine True --execution_query complex"

  # nyc yellow dataset
  "python polars_evaluation.py --dataset_type nyc-yellow --engine in-memory --gpu_engine True --execution_query simple"
  "python polars_evaluation.py --dataset_type nyc-yellow --engine in-memory --gpu_engine True --execution_query complex"

  "python polars_evaluation.py --dataset_type nyc-yellow --engine streaming --gpu_engine True --execution_query simple"
  "python polars_evaluation.py --dataset_type nyc-yellow --engine streaming --gpu_engine True --execution_query complex"
)

uv sync --locked --group cpu_polars --no-dev || exit "$?"

[ -f "benchmark.txt" ] && rm "benchmark.txt" # Safe remove previous broken file if exists

for command in "${commands[@]}"; do
	echo "Running $command"
  SECONDS=0
  if eval "$command"; then
    exit_code=0
  else
    exit_code=$?
  fi
  duration=$SECONDS
  if [[ $exit_code -eq 0 ]]; then
      echo "✓ Completed in ${duration}s"
  else
      echo "✗ Script failed with exit code: $exit_code"
      case "$command" in
        "uv sync "*|"source "*|"deactivate")
          echo "Environment setup failed; preserving benchmark.txt and leaving README.md untouched." >&2
          exit "$exit_code"
          ;;
      esac
  fi
done

# Append benchmark to README.md
python -c "from utils import append_benchmark_to_readme; append_benchmark_to_readme()"
rm -f benchmark.txt