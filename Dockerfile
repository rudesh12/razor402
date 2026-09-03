FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml .
RUN pip install -e ".[dev]" 2>/dev/null || pip install .
COPY . .
