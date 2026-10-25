# Contexto de build: ./services  (para poder copiar la librería shared)
#   docker build -f services/rag-service/Dockerfile services
#
# Orden de capas pensado para la caché: dependencias y modelos (lentos, ~1 GB) primero;
# el código propio y el de shared al final, para que cambiarlos no fuerce otra descarga.
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

# Dependencias de terceros (incluyen las de shared): cambian poco
COPY rag-service/requirements.txt /srv/rag-service/requirements.txt
RUN pip install -r /srv/rag-service/requirements.txt

# Modelos descargados por el usuario de la aplicación (sin chown posterior)
USER app
ARG EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
ARG RERANK_MODEL=cross-encoder/mmarco-mMiniLMv2-L12-H384-v1
RUN python -c "from sentence_transformers import SentenceTransformer, CrossEncoder; \
SentenceTransformer('${EMBEDDING_MODEL}'); CrossEncoder('${RERANK_MODEL}')"

# Código propio: librería shared (sin dependencias, ya instaladas) y la aplicación
USER root
COPY shared /srv/shared
RUN pip install --no-deps /srv/shared
USER app
COPY --chown=app rag-service/app /srv/rag-service/app
WORKDIR /srv/rag-service

EXPOSE 8001
HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8001/health').status==200 else 1)"

CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8001"]
