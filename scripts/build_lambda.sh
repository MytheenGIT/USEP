#!/usr/bin/env bash
# Assemble the two Lambda deployment directories under build/ (run from the repo root).
#   build/connectors  C-01: services/connectors (bare-module layout) + its requirements
#   build/pipeline    C-02: src/usep + ontology/ definitions + pyyaml/boto3
# Use --platform so wheels match the Lambda runtime (python3.12, x86_64).
set -euo pipefail
rm -rf build && mkdir -p build/connectors build/pipeline
PIP="${PIP:-.venv/bin/pip}"
cp -R services/connectors/. build/connectors/
rm -rf build/connectors/tests build/connectors/.pytest_cache build/connectors/__pycache__
grep -v -E '^(uvicorn|apscheduler|fastapi|boto3)' services/connectors/requirements.txt > build/connectors/req.lambda.txt
$PIP install -q -r build/connectors/req.lambda.txt -t build/connectors --platform manylinux2014_x86_64 --only-binary=:all: --python-version 3.12
rm build/connectors/req.lambda.txt
cp -R src/usep build/pipeline/usep
cp -R ontology build/pipeline/ontology
rm -rf build/pipeline/ontology/tests build/pipeline/ontology/tools
$PIP install -q pyyaml==6.0.3 -t build/pipeline --platform manylinux2014_x86_64 --only-binary=:all: --python-version 3.12
find build -name __pycache__ -prune -exec rm -rf {} +
echo "built: build/connectors build/pipeline (boto3 is provided by the Lambda runtime)"
