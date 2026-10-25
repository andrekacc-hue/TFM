# Contexto de build: ./services
#   docker build -f services/ingest-service/Dockerfile services
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/models/hf

WORKDIR /srv

RUN pip install torch --index-url https://download.pytorch.org/whl/cpu

COPY shared /srv/shared
RUN pip install "/srv/shared[ml]"

COPY ingest-service/requirements.txt /srv/ingest-service/requirements.txt
RUN pip install -r /srv/ingest-service/requirements.txt

COPY ingest-service/app /srv/ingest-service/app
WORKDIR /srv/ingest-service

ARG EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('${EMBEDDING_MODEL}')"

RUN useradd --create-home --uid 10001 app && chown -R app /srv /models
USER app

EXPOSE 8002
HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8002/health').status==200 else 1)"

# API + worker en el mismo proceso (WORKER_ENABLED=true). Para escalar workers aparte:
#   command: ["python", "-m", "app.workers.stream_consumer"]  con WORKER_ENABLED=false en la API
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8002"]
