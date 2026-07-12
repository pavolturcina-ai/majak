# MAJÁK API + scheduler image (used by the web service and both cron jobs).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Minimal build deps; most wheels are prebuilt. curl is handy for health checks.
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential curl \
 && rm -rf /var/lib/apt/lists/*

# Install the package (deps resolved from pyproject).
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --upgrade pip && pip install .

# Migrations are read at runtime by `python -m majak.migrate`.
COPY supabase ./supabase

EXPOSE 8000

# Render provides $PORT; default to 8000 locally.
CMD ["sh", "-c", "uvicorn majak.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
