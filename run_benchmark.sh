#!/bin/bash
ecom_path_20M="data/2019-Oct-20M.csv"
ecom_path="data/2019-Oct.csv"
ecom_path_parquet="data/2019-Oct.parquet"

commands=(
  # "pandas_evaluation.py --file_path $ecom_path_20M"
  "polars_evaluation.py --file_path $ecom_path_20M --mode eager"
  "polars_evaluation.py --file_path $ecom_path --mode eager"
  "polars_evaluation.py --file_path $ecom_path_parquet --file_type parquet --mode eager"
  "polars_evaluation.py --file_path $ecom_path --mode lazy"
  "polars_evaluation.py --file_path $ecom_path_parquet --file_type parquet --mode lazy"
  "pyspark_evaluation.py --file_path $ecom_path"
  "pyspark_evaluation.py --file_path $ecom_path_parquet --file_type parquet"

  # nyc green dataset
  "polars_evaluation.py --dataset_type nyc-green --engine in-memory --gpu_engine False --execution_query simple"
  "polars_evaluation.py --dataset_type nyc-green --engine in-memory --gpu_engine False --execution_query complex"

  "polars_evaluation.py --dataset_type nyc-green --engine streaming --gpu_engine False --execution_query simple"
  "polars_evaluation.py --dataset_type nyc-green --engine streaming --gpu_engine False --execution_query complex"

  "polars_evaluation.py --dataset_type nyc-green --engine in-memory --gpu_engine True --execution_query simple"
  "polars_evaluation.py --dataset_type nyc-green --engine in-memory --gpu_engine True --execution_query complex"

  "polars_evaluation.py --dataset_type nyc-green --engine streaming --gpu_engine True --execution_query simple"
  "polars_evaluation.py --dataset_type nyc-green --engine streaming --gpu_engine True --execution_query complex"

  "pyspark_evaluation.py --dataset_type nyc-green --execution_query simple"
  "pyspark_evaluation.py --dataset_type nyc-green --execution_query complex"

  # nyc yellow dataset
  "polars_evaluation.py --dataset_type nyc-yellow --engine in-memory --gpu_engine False --execution_query simple"
  "polars_evaluation.py --dataset_type nyc-yellow --engine in-memory --gpu_engine False --execution_query complex"

  "polars_evaluation.py --dataset_type nyc-yellow --engine streaming --gpu_engine False --execution_query simple"
  "polars_evaluation.py --dataset_type nyc-yellow --engine streaming --gpu_engine False --execution_query complex"

  "polars_evaluation.py --dataset_type nyc-yellow --engine in-memory --gpu_engine True --execution_query simple"
  "polars_evaluation.py --dataset_type nyc-yellow --engine in-memory --gpu_engine True --execution_query complex"

  "polars_evaluation.py --dataset_type nyc-yellow --engine streaming --gpu_engine True --execution_query simple"
  "polars_evaluation.py --dataset_type nyc-yellow --engine streaming --gpu_engine True --execution_query complex"

  "pyspark_evaluation.py --dataset_type nyc-yellow --execution_query simple"
  "pyspark_evaluation.py --dataset_type nyc-yellow --execution_query complex"

)

for command in "${commands[@]}"; do
	echo "Running $command"
  SECONDS=0
  eval "python $command"
#	echo "$script"
	exit_code=$?
  duration=$SECONDS
  if [[ $exit_code -eq 0 ]]; then
      echo "✓ Completed in ${duration}s"
  else
      echo "✗ Script failed with exit code: $exit_code"
  fi
done

# Append benchmark to README.md
python -c "from utils import append_benchmark_to_readme; append_benchmark_to_readme()"
rm -f benchmark.txt