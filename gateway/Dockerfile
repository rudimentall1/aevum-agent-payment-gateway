FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AEVUMPAY_DB=/data/aevumpay-gateway.db

WORKDIR /app

COPY gateway/requirements-prod.txt /app/gateway/requirements-prod.txt
RUN pip install --no-cache-dir -r /app/gateway/requirements-prod.txt

COPY gateway /app/gateway

RUN useradd --system --uid 10001 --create-home aevumpay \
    && mkdir -p /data \
    && chown -R aevumpay:aevumpay /app /data

USER aevumpay

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3)"

CMD ["uvicorn", "gateway.app:app", "--host", "0.0.0.0", "--port", "8080"]
