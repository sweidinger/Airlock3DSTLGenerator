FROM python:3.12-slim

# OpenSCAD (headless) + DejaVu/Liberation-Schriften für die Prägung
RUN apt-get update && apt-get install -y --no-install-recommends \
        openscad \
        fonts-liberation \
        fonts-dejavu-core \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY templates/ ./templates/

# Laufzeit-Verzeichnisse (werden i. d. R. als Volumes gemountet)
RUN mkdir -p /app/output /app/data
ENV AIRLOCK_OUTPUT_DIR=/app/output \
    AIRLOCK_DB_PATH=/app/data/registry.db \
    OPENSCAD_BIN=openscad

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -fsS http://localhost:8000/healthz || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
