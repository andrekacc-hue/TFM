# Contexto de build: ./services
#   docker build -f services/analytics-service/Dockerfile services
# Imagen liviana: no necesita PyTorch ni modelos (las agregaciones las hace PostgreSQL).
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv
COPY shared /srv/shared
RUN pip install /srv/shared

COPY analytics-service/requirements.txt /srv/analytics-service/requirements.txt
RUN pip install -r /srv/analytics-service/requirements.txt

COPY analytics-service/app /srv/analytics-service/app
WORKDIR /srv/analytics-service

RUN useradd --create-home --uid 10001 app && chown -R app /srv
USER app

EXPOSE 8003
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8003/health').status==200 else 1)"

CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8003"]
