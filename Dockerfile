FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    INVENTORY_DATABASE_PATH=/app/persist/inventory.db

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/persist \
    && chown appuser:appuser /app/persist

COPY --chown=appuser:appuser config ./config
COPY --chown=appuser:appuser database ./database
COPY --chown=appuser:appuser models ./models
COPY --chown=appuser:appuser ui ./ui
COPY --chown=appuser:appuser data/sample_data.csv ./data/sample_data.csv
COPY --chown=appuser:appuser streamlit_app.py .

USER appuser

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "from urllib.request import urlopen; urlopen('http://127.0.0.1:8501/_stcore/health', timeout=3).read()"

CMD ["streamlit", "run", "streamlit_app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true", "--browser.gatherUsageStats=false"]
