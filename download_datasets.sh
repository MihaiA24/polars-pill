#!/bin/bash

# Ecommerce: https://www.kaggle.com/datasets/mkechinov/ecommerce-behavior-data-from-multi-category-store
mkdir data
mkdir data/out
curl -L -o data/ecommerce-behavior-data-from-multi-category-store.zip https://www.kaggle.com/api/v1/datasets/download/mkechinov/ecommerce-behavior-data-from-multi-category-store
unzip data/ecommerce-behavior-data-from-multi-category-store.zip -d data

# NyC Taxi Dataset: https://www.kaggle.com/datasets/madalagopichand/nyc-green-yellow-taxi-trip-records
curl -L -o data/nyc-green-yellow-taxi-trip-records.zip https://www.kaggle.com/api/v1/datasets/download/madalagopichand/nyc-green-yellow-taxi-trip-records
unzip data/nyc-green-yellow-taxi-trip-records.zip -d data/nyc-taxi