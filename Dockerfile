FROM python:3.13-slim-bookworm

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/app/data \
    PORT=3000

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && apt-get update \
    && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/*

COPY app ./app
COPY run.py ./run.py
COPY docker-entrypoint.sh /docker-entrypoint.sh

RUN mkdir -p /app/data \
    && useradd --system --home /app --uid 10001 hop \
    && chown -R hop:hop /app \
    && chmod 755 /docker-entrypoint.sh

EXPOSE 3000
VOLUME ["/app/data"]

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3000/health')"

ENTRYPOINT ["/docker-entrypoint.sh"]
