# Build from the repo root so the image includes the shared code in src/usep:
#   docker build -f services/connectors/Dockerfile .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# git and ssh: reading a repository with an SSH key the admin typed in (see common/git_ssh.py)
RUN apt-get update && apt-get install -y --no-install-recommends git openssh-client && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY services/connectors/requirements.txt services/connectors/requirements.txt
RUN pip install --no-cache-dir -r services/connectors/requirements.txt

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[crypto,s3]"

COPY services/connectors ./services/connectors
WORKDIR /app/services/connectors

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
