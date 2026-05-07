FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# ── deps layer (cached unless pyproject.toml changes) ────────────────────────
FROM base AS deps
COPY pyproject.toml requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# ── final image ───────────────────────────────────────────────────────────────
FROM deps AS runtime
COPY src/ ./src/
COPY ui/ ./ui/

# Volumes for credentials and persistent data (mounted at run time)
VOLUME ["/app/config", "/app/data", "/app/logs"]

EXPOSE 8501

# Streamlit health endpoint (built-in, no extra code needed)
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')" || exit 1

CMD ["streamlit", "run", "ui/app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--server.fileWatcherType=none"]
