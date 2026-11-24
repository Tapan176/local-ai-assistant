FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TAPAN_ENV=prod \
    TAPAN_API_HOST=0.0.0.0 \
    TAPAN_INTENT_CLASSIFIER=heuristic \
    TAPAN_SQLITE_PATH=/data/tapan_ai.db \
    TAPAN_CHROMA_PATH=/data/chroma \
    TAPAN_WORKSPACE_DIR=/data/workspace \
    TAPAN_LOG_LEVEL=INFO

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY src ./src
COPY web ./web

# Run unprivileged; /data is where the SQLite database lives (mount a persistent disk here).
RUN useradd --create-home --uid 1000 tapan && mkdir -p /data && chown -R tapan:tapan /data /app
USER tapan

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import os,urllib.request as u; u.urlopen('http://127.0.0.1:%s/health' % os.getenv('PORT', '8000'), timeout=4)"

# TAPAN_API_TOKEN is mandatory when TAPAN_ENV != local: the container refuses to start without it.
CMD ["python", "-m", "src.main"]
