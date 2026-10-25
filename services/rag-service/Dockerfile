# Contexto de build: ./services  (para poder copiar la librería shared)
#   docker build -f services/rag-service/Dockerfile services
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/models/hf

# Usuario sin privilegios creado ANTES de descargar modelos: un "chown -R" posterior
# duplicaría ~1 GB de modelos en una capa nueva.
RUN useradd --create-home --uid 10001 app && mkdir -p /models && chown app /models

WORKDIR /srv

# PyTorch CPU (evita descargar ~2 GB de CUDA)
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu

COPY shared /srv/shared
RUN pip install "/srv/shared[ml]"

COPY rag-service/requirements.txt /srv/rag-service/requirements.txt
RUN pip install -r /srv/rag-service/requirements.txt

USER app

# Pre-descarga de modelos en la imagen (arranque en frío más rápido)
ARG EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
ARG RERANK_MODEL=cross-encoder/mmarco-mMiniLMv2-L12-H384-v1
RUN python -c "from sentence_transformers import SentenceTransformer, CrossEncoder; \
SentenceTransformer('${EMBEDDING_MODEL}'); CrossEncoder('${RERANK_MODEL}')"

# El código va al final: cambiarlo no invalida las capas de dependencias y modelos
COPY --chown=app rag-service/app /srv/rag-service/app
WORKDIR /srv/rag-service

EXPOSE 8001
HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8001/health').status==200 else 1)"

CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8001"]
