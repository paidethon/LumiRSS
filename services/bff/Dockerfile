# LumiRSS BFF production image (FastAPI + uvicorn).
#
# The Lumi SQLite database, secrets.json and local backups all live under
# /data (a named volume in docker-compose.prod.yml). FreshRSS data is
# mounted READ-ONLY at /freshrss-data for consistent online backup.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    LUMIRSS_DB_PATH=/data/lumi.sqlite

WORKDIR /app

# Install the BFF package (hatchling builds the wheel from src/lumirss).
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

# Run as a non-root user with a writable /data volume (mounted at runtime).
RUN useradd --create-home --uid 10001 lumirss && mkdir -p /data && chown lumirss:lumirss /data
USER lumirss

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=3)"]

CMD ["uvicorn", "lumirss.main:app", "--host", "0.0.0.0", "--port", "8000"]
