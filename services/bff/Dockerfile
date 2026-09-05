# LumiRSS BFF production image (FastAPI + uvicorn).
#
# The Lumi SQLite database, secrets.json and local backups all live under
# /data (a named volume in docker-compose.prod.yml). FreshRSS data is
# mounted READ-ONLY at /freshrss-data for consistent online backup.
#
# 0020 AUDIT (dependency reproducibility): the production image installs
# EXACTLY the dependency set represented by the tested uv.lock (`uv sync
# --frozen`), instead of independently resolving pyproject's `>=` ranges with
# pip. A multi-stage build keeps uv and all build tooling out of the final
# image — only the resolved virtualenv is shipped.

# syntax=docker/dockerfile:1

# ---- builder: resolve + install the locked set into a venv with uv ----
FROM python:3.12-slim AS builder

# Pin uv to the version used in development/CI so the resolve is reproducible.
COPY --from=ghcr.io/astral-sh/uv:0.12.6 /uv /uvx /bin/

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Copy the lock + manifest first (layer-cache friendly), then the source.
COPY pyproject.toml uv.lock ./
COPY src ./src

# --frozen: install EXACTLY the tested lockfile (never re-resolve);
# --no-dev: skip dev/test dependencies; --no-editable: build a real wheel for
# lumirss so the venv is self-contained (the runtime stage does not copy src).
RUN uv sync --frozen --no-dev --no-editable

# ---- runtime: minimal image carrying only the resolved venv ----
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LUMIRSS_DB_PATH=/data/lumi.sqlite \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv

# Run as a non-root user with a writable /data volume (mounted at runtime).
RUN useradd --create-home --uid 10001 lumirss && mkdir -p /data && chown lumirss:lumirss /data
USER lumirss

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=3)"]

CMD ["uvicorn", "lumirss.main:app", "--host", "0.0.0.0", "--port", "8000"]
