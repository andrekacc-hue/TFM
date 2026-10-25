# Contexto de build: ./services
#   docker build -f services/api-gateway/Dockerfile services
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv
COPY shared /srv/shared
RUN pip install /srv/shared

COPY api-gateway/requirements.txt /srv/api-gateway/requirements.txt
RUN pip install -r /srv/api-gateway/requirements.txt

COPY api-gateway/app /srv/api-gateway/app
WORKDIR /srv/api-gateway

RUN useradd --create-home --uid 10001 app && chown -R app /srv
USER app

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status==200 else 1)"

# --proxy-headers: respeta X-Forwarded-For si hay un reverse proxy (nginx) delante
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
