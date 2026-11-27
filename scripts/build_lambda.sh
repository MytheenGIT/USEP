#!/usr/bin/env bash
# Assemble the two Lambda deployment directories under build/ (run from the repo root).
#   build/connectors  C-01: services/connectors (bare-module layout) + its requirements
#   build/pipeline    C-02: src/usep + ontology/ definitions + config/runtime policy files + pyyaml/boto3
# Use --platform so wheels match the Lambda runtime (python3.12, x86_64).
set -euo pipefail
rm -rf build && mkdir -p build/connectors build/pipeline
PIP="${PIP:-.venv/bin/pip}"
cp -R services/connectors/. build/connectors/
mkdir -p build/connectors/config && cp config/sources.yaml build/connectors/config/sources.yaml
rm -rf build/connectors/tests build/connectors/.pytest_cache build/connectors/__pycache__
grep -v -E '^(uvicorn|apscheduler|fastapi|boto3)' services/connectors/requirements.txt > build/connectors/req.lambda.txt
$PIP install -q -r build/connectors/req.lambda.txt -t build/connectors --platform manylinux2014_x86_64 --only-binary=:all: --python-version 3.12
rm build/connectors/req.lambda.txt
cp -R src/usep build/pipeline/usep
cp -R ontology build/pipeline/ontology
rm -rf build/pipeline/ontology/tests build/pipeline/ontology/tools
mkdir -p build/pipeline/config && cp -R config/runtime build/pipeline/config/runtime && cp config/sources.yaml build/pipeline/config/sources.yaml && mkdir -p build/pipeline/config/registry && cp config/registry/trusted_keys.yaml build/pipeline/config/registry/trusted_keys.yaml
$PIP install -q pyyaml==6.0.3 cryptography==50.0.2 -t build/pipeline --platform manylinux2014_x86_64 --only-binary=:all: --python-version 3.12
find build -name __pycache__ -prune -exec rm -rf {} +
echo "built: build/connectors build/pipeline (boto3 is provided by the Lambda runtime)"
