#!/bin/bash
warmups="${BENCHMARK_WARMUPS-1}"
repetitions="${BENCHMARK_REPETITIONS-5}"
if [[ ! "$warmups" =~ ^[0-9]+$ ]]; then
  echo "BENCHMARK_WARMUPS must be an integer >= 0" >&2
  exit 2
fi
if [[ ! "$repetitions" =~ ^[0-9]+$ || "$repetitions" =~ ^0+$ ]]; then
  echo "BENCHMARK_REPETITIONS must be an integer >= 1" >&2
  exit 2
fi
export BENCHMARK_BATCH_ID="${BENCHMARK_BATCH_ID:-$(date -u +%Y%m%dT%H%M%SZ)-$$-$RANDOM}"

ecom_path_20M="data/2019-Oct-20M.csv"
ecom_path="data/2019-Oct.csv"
ecom_path_parquet="data/2019-Oct.parquet"

commands=(
   "source .venv/bin/activate"
   "python pandas_evaluation.py --file_path $ecom_path_20M"
   "python duckdb_evaluation.py --file_path $ecom_path_20M"
   "python duckdb_evaluation.py --file_path $ecom_path"
   "python duckdb_evaluation.py --file_path $ecom_path_parquet --file_type parquet"
   "python polars_evaluation.py --file_path $ecom_path_20M --mode eager --engine in-memory"
   "python polars_evaluation.py --file_path $ecom_path --mode eager --engine in-memory"
   "python polars_evaluation.py --file_path $ecom_path_parquet --file_type parquet --mode eager --engine in-memory"
   "python polars_evaluation.py --file_path $ecom_path --mode lazy --engine in-memory"
   "python polars_evaluation.py --file_path $ecom_path_parquet --file_type parquet --mode lazy --engine in-memory"
   "python polars_evaluation.py --file_path $ecom_path --mode lazy --engine streaming"
   "python polars_evaluation.py --file_path $ecom_path_parquet --file_type parquet --mode lazy --engine streaming"
   "python pyspark_evaluation.py --file_path $ecom_path"
   "python pyspark_evaluation.py --file_path $ecom_path_parquet --file_type parquet"

   # nyc green dataset
   "python polars_evaluation.py --dataset_type nyc-green --engine in-memory --gpu_engine False --execution_query simple"
   "python polars_evaluation.py --dataset_type nyc-green --engine in-memory --gpu_engine False --execution_query complex"

   "python polars_evaluation.py --dataset_type nyc-green --engine streaming --gpu_engine False --execution_query simple"
   "python polars_evaluation.py --dataset_type nyc-green --engine streaming --gpu_engine False --execution_query complex"

   "python pyspark_evaluation.py --dataset_type nyc-green --execution_query simple"
   "python pyspark_evaluation.py --dataset_type nyc-green --execution_query complex"
   "python duckdb_evaluation.py --dataset_type nyc-green --execution_query simple"
   "python duckdb_evaluation.py --dataset_type nyc-green --execution_query complex"

   # nyc yellow dataset
   "python polars_evaluation.py --dataset_type nyc-yellow --engine in-memory --gpu_engine False --execution_query simple"
   "python polars_evaluation.py --dataset_type nyc-yellow --engine in-memory --gpu_engine False --execution_query complex"

   "python polars_evaluation.py --dataset_type nyc-yellow --engine streaming --gpu_engine False --execution_query simple"
   "python polars_evaluation.py --dataset_type nyc-yellow --engine streaming --gpu_engine False --execution_query complex"

   "python pyspark_evaluation.py --dataset_type nyc-yellow --execution_query simple"
   "python pyspark_evaluation.py --dataset_type nyc-yellow --execution_query complex"
   "python duckdb_evaluation.py --dataset_type nyc-yellow --execution_query simple"
   "python duckdb_evaluation.py --dataset_type nyc-yellow --execution_query complex"

  # Change to GPU env
  "deactivate"
  "uv sync --locked --group gpu_polars --no-dev"
  "source .venv/bin/activate"
  # Repeat the e-commerce workloads to measure the Polars version change too.
  "python polars_evaluation.py --file_path $ecom_path_20M --mode eager --engine in-memory"
  "python polars_evaluation.py --file_path $ecom_path --mode eager --engine in-memory"
  "python polars_evaluation.py --file_path $ecom_path_parquet --file_type parquet --mode eager --engine in-memory"
  "python polars_evaluation.py --file_path $ecom_path --mode lazy --engine in-memory"
  "python polars_evaluation.py --file_path $ecom_path_parquet --file_type parquet --mode lazy --engine in-memory"
  "python polars_evaluation.py --file_path $ecom_path --mode lazy --engine streaming"
  "python polars_evaluation.py --file_path $ecom_path_parquet --file_type parquet --mode lazy --engine streaming"

  # Same-version CPU baselines isolate GPU acceleration from Polars version changes.
  "python polars_evaluation.py --dataset_type nyc-green --engine in-memory --gpu_engine False --execution_query simple"
  "python polars_evaluation.py --dataset_type nyc-green --engine in-memory --gpu_engine False --execution_query complex"
  "python polars_evaluation.py --dataset_type nyc-green --engine streaming --gpu_engine False --execution_query simple"
  "python polars_evaluation.py --dataset_type nyc-green --engine streaming --gpu_engine False --execution_query complex"
  "python polars_evaluation.py --dataset_type nyc-yellow --engine in-memory --gpu_engine False --execution_query simple"
  "python polars_evaluation.py --dataset_type nyc-yellow --engine in-memory --gpu_engine False --execution_query complex"
  "python polars_evaluation.py --dataset_type nyc-yellow --engine streaming --gpu_engine False --execution_query simple"
  "python polars_evaluation.py --dataset_type nyc-yellow --engine streaming --gpu_engine False --execution_query complex"

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
benchmark_failed=0

for command in "${commands[@]}"; do
  case "$command" in
    python\ *evaluation.py*)
      command+=" --warmups $warmups --repetitions $repetitions"
      ;;
  esac
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
      benchmark_failed=1
      case "$command" in
        "uv sync "*|"source "*|"deactivate")
          echo "Environment setup failed; recorded JSON results are preserved." >&2
          exit "$exit_code"
          ;;
      esac
  fi
done

# Load development dependencies only for report generation, after timing the GPU runs.
uv run --locked --group gpu_polars python plot_benchmarks.py || exit "$?"
exit "$benchmark_failed"