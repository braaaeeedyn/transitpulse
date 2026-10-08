# Linux + Java 17 + PySpark 3.5 — the same runtime as the Oracle VM and CI.
# (Spark 3.5 doesn't run reliably on Windows: it needs winutils.exe and supports Java ≤ 17.)
#
#   docker build -t transitpulse-spark -f pipeline/spark/Dockerfile .
#   docker run --rm -v "$PWD:/app" transitpulse-spark python -m pipeline.spark.clean_bart_od --input ... --output ...
FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends openjdk-17-jre-headless procps \
    && rm -rf /var/lib/apt/lists/*

ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

RUN pip install --no-cache-dir "pyspark>=3.5,<3.6" "holidays>=0.56" "pytest>=8.3"

WORKDIR /app
