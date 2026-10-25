# Soporte TI Produbanco — Base de Conocimientos Inteligente con RAG

Trabajo Fin de Máster — Máster en Inteligencia Artificial (UNIR).

Sistema de soporte técnico para el área de **TI Producción** de Produbanco: una base de conocimientos
indexada con **RAG** (Retrieval-Augmented Generation) que responde consultas en lenguaje natural desde
un **portal React** y desde **Microsoft Teams**, con citas verificables de las fuentes y métricas para
la evaluación académica.

## Arquitectura (4 capas)

| Capa | Componentes |
|------|-------------|
| 1. Frontend | Admin Portal (React + Vite + TS) · Teams Bot (Bot Framework, Python) |
| 2. Middleware | `api-gateway` · `rag-service` · `ingest-service` · `analytics-service` (FastAPI) · Redis Streams/cache |
| 3. Backend | Supabase: PostgreSQL 15 + pgvector · Storage · Auth (Azure AD) · RLS · Realtime · Edge Functions |
| 4. IA | Ollama (`gemma4:31b-cloud`, plan gratuito) · embeddings multilingual-MiniLM (384d) · reranker cross-encoder multilingüe · adapters Claude/OpenAI |

## Estado por fases

| Fase | Contenido | Estado |
|------|-----------|--------|
| 1 | Infraestructura, Supabase, migraciones, bootstrap | ✅ |
| 2 | Librería compartida + rag-service | ✅ |
| 3 | ingest-service + worker Redis Streams | ✅ |
| 4 | api-gateway + analytics-service | ✅ |
| 5 | Edge Functions de Supabase | ✅ |
| 6 | Frontend React (Admin Portal) | ⏳ |
| 7 | Bot de Microsoft Teams | ⏳ |
| 8 | Evaluación RAGAs, observabilidad, documentación | ⏳ |

---

## Fase 5 — Edge Functions de Supabase

| Función | Disparador | Qué hace |
|---------|-----------|----------|
| `on-document-upload` | Trigger SQL en `storage.objects` → `pg_net` | Registra en `tfm.documents` (estado `pending`) los archivos que un usuario sube directamente al bucket `documents` |
| `reindex-document` | Portal (`supabase.functions.invoke`) con la sesión del usuario | Devuelve un documento a `pending` (editor de su área o admin) |

**Patrón outbox.** Las funciones corren en la nube de Supabase y no alcanzan Redis ni el ingest-service.
Por eso registran el documento con `enqueued_at = NULL`, y un *outbox poller* del ingest-service lo reclama
cada 15 s con `tfm.claim_pending_documents()` (`FOR UPDATE SKIP LOCKED`) y lo publica en Redis. Así no hay
acoplamiento de red, se escala con varias réplicas sin duplicados y los documentos atascados en `pending` se
reencolan solos si Redis pierde mensajes. Guía completa: [`docs/edge-functions.md`](docs/edge-functions.md).

```powershell
npx supabase login                                              # una vez
.\.venv\Scripts\python.exe scripts\configure_edge_functions.py  # Vault + secretos + despliegue
cd supabase\functions; deno task test                           # 16 tests unitarios (Deno)
```

Verificado de extremo a extremo (`tests/integration/test_edge_functions.py`): un editor sube un Markdown
directamente a Storage con su JWT, el trigger avisa a la función, el outbox lo encola, el worker lo indexa y el
RAG lo cita a través del gateway. `reindex-document` rechaza a un viewer y a un editor de otra área, y Storage
impide subir a un área ajena. La suite de integración completa queda en **16 tests**.

---

## Fase 4 — API Gateway y Analytics

### Arranque del sistema completo (Docker)

```powershell
cd C:\Frontend\TFM\soporte-bancario-rag
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build   # o: make up
Invoke-RestMethod http://localhost:8000/ready        # {"status":"ok", "checks": {...4 servicios}}
```

| Modo | Comando | Qué levanta |
|------|---------|-------------|
| **Cloud** (por defecto) | `docker compose ... up -d` | Redis + rag + ingest + analytics + gateway. Supabase Cloud y Ollama nativo del host (`host.docker.internal`) |
| Self-hosted | `make up-local` / `scripts/bootstrap.*` | Lo anterior + Supabase y Ollama en contenedores (perfiles `supabase-local`, `ollama-local`) |

Solo el gateway se publica (`8000`); los servicios internos se exponen únicamente en `127.0.0.1` con el
override de desarrollo.

### API pública (`http://localhost:8000/docs`)

| Endpoint | Rol mínimo | Límite por defecto |
|----------|-----------|--------------------|
| `GET /api/v1/me` | viewer | 120/min |
| `POST /api/v1/query` | viewer · servicio interno | 20/min |
| `POST /api/v1/feedback` | viewer | 120/min |
| `POST /api/v1/documents` (multipart) | editor (su área) | 10/min |
| `POST /api/v1/documents/{id}/reindex` · `GET .../status` | editor | 10/min · — |
| `GET /api/v1/documents/queue/stats` | admin | — |
| `GET /api/v1/analytics/{summary,timeseries,top-documents,unanswered,knowledge-base}` | editor | 120/min |
| `GET /api/v1/reports/queries.{csv,json}` | admin | 5/min |
| `GET /health` · `GET /ready` | — | — |

Especificación exportada: [`docs/api/openapi.yaml`](docs/api/openapi.yaml) (pública) y
[`docs/api/internal/`](docs/api/internal/) (servicios internos). Se regenera con `make openapi`.

### Decisiones técnicas

- **El rol y el área se leen de `tfm.profiles` en cada petición** (cache de 60 s), no del JWT: si un admin
  degrada a un usuario, el cambio se aplica en un minuto sin esperar a que caduque su token.
- **RLS de extremo a extremo.** El gateway reenvía el JWT del usuario al rag-service, que busca con él;
  Supabase filtra por área. El área que envíe un viewer o un editor se ignora: solo un admin puede elegirla.
- **Servicios internos** (bot de Teams, Fase 7): `X-Internal-Api-Key` + `X-User-Email` para actuar en nombre de
  un usuario registrado. El correo se compara de forma **exacta**: con `ilike`, un `_` funcionaría como comodín
  y permitiría suplantar a otro usuario (hay un test para este caso).
- **Rate limiting con `limits`** (la librería sobre la que se construye slowapi) usada directamente: los límites
  salen de la configuración, los contadores se comparten entre réplicas vía Redis, la API es asíncrona y, si Redis
  falla, deja pasar la petición (*fail-open*) y lo registra.
- **Proxy transparente.** Las subidas multipart se reenvían sin reinterpretarlas (con límite de tamaño) y los
  errores de los servicios llegan al cliente con su formato y código originales. Un servicio caído devuelve 503
  y un *timeout* devuelve 504.
- **Métricas calculadas en PostgreSQL** (migración 08: `tfm.metrics_*`). Percentiles y tasas se calculan en
  la base de datos en lugar de traer las filas a Python. `tfm.queries` guarda además la latencia por etapa y el
  motivo de abstención.
- **"Preguntas sin respuesta"** (`/analytics/unanswered`): las abstenciones agrupadas señalan qué documentación
  falta. Los bloqueos de los guardrails se excluyen.
- **Contexto SSL compartido** entre todos los clientes HTTP. Crear uno por cliente costaba ~1 s en Windows y
  hacía que el *setup* de cada test del gateway tardara 5,5 s.
- **Imágenes Docker.** El usuario sin privilegios se crea antes de descargar los modelos: el `chown -R`
  posterior duplicaba ~1 GB. rag-service bajó de 5,7 a 3,9 GB.

### Hallazgo de la integración: rol asignado por la API de Supabase

La API de administración de Supabase Auth inserta el usuario solo con `{provider}` y **después** actualiza
`app_metadata` con el rol y el área, así que el trigger `AFTER INSERT` de la Fase 1 nunca los veía. La migración
09 añade un trigger `AFTER UPDATE OF raw_app_meta_data` que sincroniza `tfm.profiles`. Desde ahora un admin puede
asignar roles tanto desde el SQL Editor como desde *Authentication → Users → app_metadata*, y el cambio
queda auditado. Lo cubre `supabase/tests/database/auth_sync.test.sql`.

### Tests

```powershell
make test                     # unitarios: 225 tests en 5 paquetes (cobertura 94–99 %)
make test-integration         # extremo a extremo contra el stack: 11 tests
.\.venv\Scripts\python.exe scripts\apply_migrations.py --test   # pgTAP: 57 tests
```

Los tests de integración crean usuarios temporales reales en Supabase Auth (viewer y editor de
`operaciones`, viewer de `creditos` y un admin), obtienen JWT reales con contraseña y verifican: autenticación,
roles, **aislamiento por área a través de toda la cadena** (un usuario de créditos no recupera el procedimiento
del HSM de operaciones), ingesta y búsqueda de un documento nuevo, feedback, guardrails, métricas y exportación.
Al terminar borran usuarios, consultas, documentos y archivos de Storage.

---

## Fase 3 — Microservicio de ingesta

### Flujo

```
POST /v1/ingest (multipart) ─► Supabase Storage  documents/{area}/{id}/{archivo}
                            ─► tfm.documents  status=pending (sha256 para detectar duplicados)
                            ─► XADD documents.ingest {document_id, attempt, trace_id}
                                       │
         worker (XREADGROUP, grupo ingest-workers)
                                       ▼
   processing ─► descarga ─► loader (PDF/DOCX/MD/TXT) ─► chunker ─► embeddings ─► tfm.chunks
              └─► indexed (+ métricas en metadata.ingestion)   │  Realtime notifica al portal
              └─► failed  (+ error_message) ──► reintento / DLQ documents.ingest.dlq
```

| Componente | Archivo | Responsabilidad |
|------------|---------|-----------------|
| Loaders | `app/core/loaders/` | PDF (por página), DOCX (por encabezado, con tablas), Markdown (por `#`), TXT |
| Chunker | `app/core/chunker.py` | Recursivo párrafo → línea → frase → palabra, 700 caracteres con 120 de solapamiento |
| Embedder | `app/core/embedder.py` | Lotes + cabecera contextual "título · sección" |
| Pipeline | `app/core/pipeline.py` | Estados, reemplazo idempotente de chunks y métricas |
| Cola | `app/core/queue.py` | Redis Streams: publicación, grupo de consumidores, DLQ y estadísticas |
| Worker | `app/workers/stream_consumer.py` | Consumo, reintentos con `attempt`, reclamación de mensajes huérfanos y DLQ |

### Decisiones técnicas

- **`EMBEDDING_MAX_SEQ_LENGTH=256`.** El modelo MiniLM trunca a 128 tokens por defecto, y un chunk de 700
  caracteres en español ocupa ~175 (medido: 4,0 caracteres/token). Sin este ajuste, el último ~27 % de cada chunk
  no influía en la búsqueda. Se aplica igual en la ingesta y en la consulta.
- **Chunks por sección.** Un chunk nunca mezcla dos páginas ni dos secciones, así la cita es exacta.
  `tfm.match_chunks` devuelve ahora los metadatos (migración 07) y las citas muestran
  `[Fuente: MAN-BD-003, Escalamiento al DBA]` o `fragmento 2 (pág. 2)` en lugar de solo "fragmento N".
- **Cabeceras contextuales.** Se vectoriza "título · sección + contenido", pero se guarda y se muestra solo el
  contenido. Un fragmento como "Paso 3: relanzar desde el checkpoint" queda asociado a su documento.
- **Entrega *at-least-once* con idempotencia.** Redis Streams puede entregar un mensaje dos veces (worker caído
  antes del ACK); el pipeline borra y reescribe los chunks, así el resultado es el mismo.
- **Clasificación de errores.** Los errores de contenido (PDF escaneado, archivo corrupto, formato) quedan como
  `failed` sin reintento; los transitorios (Storage o PostgREST caídos) se reencolan hasta `WORKER_MAX_ATTEMPTS`
  y después van a la DLQ. Ningún documento queda en `processing` para siempre.
- **Duplicados por SHA-256** del contenido dentro de la misma área (HTTP 409).
- **Defensa en profundidad.** Además del gateway (Fase 4), el servicio exige la clave interna y solo deja subir
  documentos a editores (en su área) y administradores.

### Ejecutar en local (sin Docker)

El worker necesita Redis 7 (Streams). Sin Docker, se puede usar temporalmente un Redis en memoria:

```powershell
# Terminal 1 — Redis temporal (solo desarrollo)
.\.venv\Scripts\python.exe -c "from fakeredis import TcpFakeServer; TcpFakeServer(('127.0.0.1', 6379), server_type='redis').serve_forever()"

# Terminal 2 — ingest-service (API + worker)
cd services\ingest-service
$env:REDIS_URL = 'redis://127.0.0.1:6379/0'
..\..\.venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --port 8002

# Terminal 3 — cargar el corpus de ejemplo (PDF, DOCX y Markdown)
.\.venv\Scripts\python.exe scripts\make_sample_corpus.py     # genera samples\corpus
.\.venv\Scripts\python.exe scripts\seed_corpus.py            # sube y espera la indexación
```

Con Docker: `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d redis ingest-service`.

### Endpoints (cabecera `X-Internal-Api-Key`)

| Endpoint | Descripción |
|----------|-------------|
| `POST /v1/ingest` | Multipart `file`, `source_type`, `area`, `title?` → 202 con `document_id` |
| `POST /v1/ingest/{id}/reindex` | Reprocesar un documento (ingesta manual) |
| `GET /v1/ingest/{id}` | Estado, nº de chunks, error y métricas de ingesta |
| `GET /v1/ingest/queue/stats` | Longitud del stream, pendientes de ACK, DLQ y contadores del worker |
| `GET /health` · `GET /ready` | Liveness · readiness (Supabase, Redis, modelo, worker) |

### Tests

```powershell
cd services\ingest-service; ..\..\.venv\Scripts\python.exe -m pytest --cov=app   # 58 tests, 94 %
```

Usan PDF y DOCX reales generados en el propio test (reportlab, python-docx) y `fakeredis` para los Streams:
reintentos, DLQ, reclamación de mensajes de un worker caído e idempotencia.

Resultado de referencia (corpus de ejemplo): PDF de 3 páginas → 3 chunks en 2,2 s; DOCX → 5 chunks; Markdown →
4 chunks. La pregunta sobre el certificado del HSM, que en la Fase 2 se abstenía, ahora se responde con citas por página.

---

## Fase 2 — Librería compartida y rag-service

### Pipeline

```
pregunta ─► guardrails de entrada ─► embedding (MiniLM 384d) ─► tfm.match_chunks (pgvector, top-20)
         ─► reranking cross-encoder (top-5) ─► abstención si no hay evidencia
         ─► prompt + LLM (adapter) ─► guardrails de salida ─► tfm.queries ─► respuesta + fuentes
```

| Componente | Archivo | Responsabilidad |
|------------|---------|-----------------|
| Configuración | `services/shared/shared/config.py` | pydantic-settings; lee `.env` de la raíz |
| Logging | `shared/logging.py`, `shared/middleware.py` | structlog JSON + `X-Trace-Id` propagado entre servicios |
| Supabase | `shared/supabase_client.py` | PostgREST con service_role **o** con el JWT del usuario (RLS) |
| Cache | `shared/redis_client.py` | Redis opcional con *circuit breaker* (falla en < 1 s) |
| Auth | `shared/auth.py` | JWT de Supabase (ES256 vía JWKS y HS256) + clave interna |
| Embeddings | `shared/embeddings.py` | sentence-transformers, compartido con la ingesta |
| Adapters LLM | `rag-service/app/adapters/` | Ollama · Claude · OpenAI tras la interfaz `LLMAdapter` |
| Núcleo | `rag-service/app/core/` | retriever, reranker, generator, guardrails, prompts, rag_chain |

### Decisiones técnicas

- **Patrón Adapter para el LLM.** Cambiar de proveedor es cambiar `LLM_PROVIDER`, sin tocar el código de negocio.
- **PostgREST por `httpx` en lugar de `supabase-py`.** El cliente oficial guarda la sesión como estado global; aquí
  cada llamada elige service_role o el JWT del usuario, así RLS filtra por área sin crear un cliente por petición.
- **Cadena explícita en lugar de LangChain.** Cada etapa es una clase pequeña e inyectable, con latencia
  medida por separado (`timings` en la respuesta), lo que simplifica los tests y la evaluación.
- **Reranker multilingüe** (`mmarco-mMiniLMv2-L12-H384-v1`) en lugar de `ms-marco-MiniLM-L-6-v2`, que solo
  está entrenado en inglés. Medido sobre el corpus demo: 8/15 frente a 6/15 fragmentos relevantes en el top-5.
- **Guardrails deterministas.** Bloquean la inyección de prompts y la evasión de controles (también en formas
  conjugadas), enmascaran tarjetas (Luhn) y credenciales, y redactan secretos en la salida. Cada bloqueo es auditable.
- **Abstención en dos niveles:** sin contexto sobre el umbral de similitud (sin llamar al LLM) o cuando el modelo
  declara falta de evidencia. En ambos casos se devuelve la frase exacta del prompt de sistema.

### Instalación (Windows, sin Docker)

```powershell
cd C:\Frontend\TFM\soporte-bancario-rag
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cpu
.\.venv\Scripts\python.exe -m pip install -e "services\shared[ml,dev]" -e "services\rag-service[dev]"
```

### Tests

```powershell
cd services\shared;      ..\..\.venv\Scripts\python.exe -m pytest --cov=shared   # 53 tests, 99 %
cd ..\rag-service;       ..\..\.venv\Scripts\python.exe -m pytest --cov=app      # 76 tests, 96 %
```

### Prueba manual

```powershell
cd services\rag-service
..\..\.venv\Scripts\python.exe scripts\rag_cli.py health
..\..\.venv\Scripts\python.exe scripts\rag_cli.py seed-demo        # 3 documentos demo (idempotente)
..\..\.venv\Scripts\python.exe scripts\rag_cli.py ask "El batch de cierre quedó en RUNNING, ¿qué hago?"
..\..\.venv\Scripts\python.exe scripts\rag_cli.py clean-demo       # elimina el corpus demo

# Servicio HTTP + Swagger en http://localhost:8001/docs
..\..\.venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --port 8001
```

Llamada HTTP (cabecera obligatoria `X-Internal-Api-Key`, valor de `INTERNAL_API_KEY` en `.env`):

```bash
curl -X POST http://localhost:8001/v1/query -H "Content-Type: application/json" \
  -H "X-Internal-Api-Key: <INTERNAL_API_KEY>" -H "X-User-Id: <uuid del usuario>" \
  -d '{"question": "Varios cajeros rechazan retiros con código 91", "channel": "web"}'
```

| Endpoint | Descripción |
|----------|-------------|
| `POST /v1/query` | Respuesta con `sources`, `abstained`, `timings`, `usage`, `query_id`, `trace_id` |
| `POST /v1/feedback` | 👍/👎 sobre una consulta propia (upsert por usuario) |
| `GET /health` · `GET /ready` | Liveness · readiness (Supabase, LLM, cache, modelos) |

Resultados de referencia (corpus demo, `gemma4:31b-cloud`, CPU sin GPU): unos **2,2 s** por consulta
(retrieval ~0,2 s + rerank ~0,2 s + LLM ~1,8 s). Las preguntas fuera del corpus se abstienen y las inyecciones
se bloquean en ~1 ms.

---

## Fase 1 — Infraestructura y Supabase

### Requisitos

| Herramienta | Versión | Notas |
|-------------|---------|-------|
| Docker Desktop | 4.30+ (Compose v2) | En Windows con backend WSL2. Asigna ≥ 8 GB de RAM. |
| Git | 2.40+ | En Windows incluye **Git Bash** (bash, openssl, curl) |
| Espacio en disco | ~10 GB | Imágenes de Supabase (~3 GB) + modelo Qwen3 4B (~2.5 GB) |

> No se necesita la Supabase CLI ni Ollama instalados en el host: ambos corren en contenedores.

### Arranque rápido

**Windows (PowerShell):**

```powershell
cd soporte-bancario-rag
powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1
```

**Linux / macOS / Git Bash / WSL:**

```bash
cd soporte-bancario-rag
chmod +x scripts/bootstrap.sh
./scripts/bootstrap.sh          # o: make bootstrap
```

El bootstrap:

1. Crea `.env` desde `.env.example` y **genera los secretos vacíos**: `SUPABASE_JWT_SECRET`,
   `SUPABASE_ANON_KEY` y `SUPABASE_SERVICE_ROLE_KEY` (JWT HS256 firmados con ese secreto),
   `SECRET_KEY_BASE`, `PG_META_CRYPTO_KEY` e `INTERNAL_API_KEY`.
2. Levanta el stack con `docker-compose.yml` + `docker-compose.dev.yml`.
3. Espera a que BD, Auth, Storage, Redis y Ollama estén *healthy* y Kong responda.
4. Aplica las migraciones pendientes (registradas en `supabase_migrations.schema_migrations`,
   el mismo formato de la Supabase CLI).
5. Carga `supabase/seed.sql` (incidentes de ejemplo).
6. Crea el usuario admin de demostración (`DEMO_ADMIN_EMAIL` / `DEMO_ADMIN_PASSWORD`).
7. Descarga el modelo `OLLAMA_MODEL`.

Opciones:

| bash | PowerShell | Efecto |
|------|------------|--------|
| `--skip-model` | `-SkipModel` | No descarga el LLM |
| `--no-seed` | `-NoSeed` | No carga datos de ejemplo |
| `--with-tests` | `-WithTests` | Ejecuta los tests pgTAP al final |
| `--migrate-only` | `-MigrateOnly` | Solo migraciones (+ seed) con el stack ya levantado |
| `--test-only` | `-TestOnly` | Solo tests pgTAP |

### Servicios y puertos

| Servicio | URL en el host | Expuesto por |
|----------|----------------|--------------|
| Supabase API (Kong) | http://localhost:54321 | base — el navegador lo necesita para Auth/Realtime |
| Supabase Studio | http://localhost:54323 | base |
| PostgreSQL | `localhost:54322` | dev (solo 127.0.0.1) |
| Redis | `localhost:6379` | dev (solo 127.0.0.1) |
| Ollama | http://localhost:11434 | dev (solo 127.0.0.1) |
| Jaeger UI | http://localhost:16686 | dev + perfil `observability` |

Los microservicios (8000), el frontend (3000) y el bot (3978) se añaden al compose en sus fases.
Todos los contenedores comparten la red `soporte-net`; los volúmenes persistentes son
`supabase-db-data`, `supabase-storage-data`, `redis-data` y `ollama-data`.

### Verificación manual

Comandos en bash (Git Bash/WSL). En PowerShell usa `curl.exe` en lugar de `curl` y una sola línea
en lugar de las continuaciones `\`.

```bash
# 1. Estado de los contenedores (todos "running"/"healthy")
docker compose -f docker-compose.yml -f docker-compose.dev.yml ps

# 2. Studio -> abrir http://localhost:54323 (Table Editor: esquema tfm)

# 3. Tablas y función de búsqueda
docker compose exec supabase-db psql -h localhost -U postgres -c "\dt tfm.*" -c "\df tfm.match_chunks"

# 4. Ollama responde desde el host
Invoke-RestMethod http://localhost:11434/api/tags                     # PowerShell
curl http://localhost:11434/api/generate -d '{"model":"qwen3:4b-instruct","prompt":"Hola","stream":false}'   # bash

# 5. Login del admin demo contra Supabase Auth (devuelve access_token)
curl -X POST "http://localhost:54321/auth/v1/token?grant_type=password" \
  -H "apikey: <SUPABASE_ANON_KEY>" -H "Content-Type: application/json" \
  -d '{"email":"admin@soporte.local","password":"Admin123!"}'

# 6. Tests pgTAP
powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1 -TestOnly   # o: make test-db
```

### Supabase Cloud (proyecto `ResposTFM`)

El backend de desarrollo es el proyecto cloud `https://vcipniqjxhrptnruitco.supabase.co`.
Todas las tablas viven en el esquema **`tfm`**.

**Opción A — SQL Editor (sin instalar nada):** abre Dashboard → SQL Editor, pega el contenido de
[`supabase/deploy/tfm_schema.sql`](supabase/deploy/tfm_schema.sql) y pulsa *Run*.

**Opción B — script (idempotente, registra versiones):**

```powershell
# En .env: SUPABASE_DB_URL = cadena del "Session pooler" (Dashboard -> Connect)
py -m pip install "psycopg[binary]" python-dotenv
py scripts\apply_migrations.py --seed --test
```

**Después, en ambos casos:** Project Settings → Data API → *Exposed schemas* → añadir `tfm`
(necesario para `supabase.schema('tfm')` desde React y Python).

> La `service_role` key solo da acceso a la API REST (datos), no permite DDL. Crear esquemas y
> tablas requiere la conexión Postgres o el SQL Editor.

### Modelo de datos (esquema `tfm`)

```
auth.users ──1:1── tfm.profiles (role: viewer|editor|admin, area)

tfm.documents ──1:N── tfm.chunks (embedding vector(384), HNSW coseno)
      │  └──0:N── tfm.incidents
      └──0:N── tfm.golden_dataset
tfm.queries ──1:N── tfm.feedback
tfm.audit_events  ← triggers sobre documents, incidents, golden_dataset, profiles
tfm.match_chunks(query_embedding, match_threshold, match_count, filter_area)
```

Migraciones (`supabase/migrations/`):

| Archivo | Contenido |
|---------|-----------|
| `…01_init.sql` | `pgcrypto`, `pg_trgm` |
| `…02_pgvector.sql` | extensión `vector` |
| `…03_schemas.sql` | esquema `tfm`, privilegios por rol, trigger `set_updated_at()` |
| `…04_tables.sql` | tablas e índices (HNSW, trigram) |
| `…05_functions.sql` | `match_chunks`, helpers de autorización, alta de perfil, auditoría |
| `…06_rls_policies.sql` | políticas RLS, bucket `documents` en Storage, publicación Realtime |

### Seguridad: roles y RLS

| Recurso | viewer | editor | admin | service_role (microservicios) |
|---------|--------|--------|-------|-------------------------------|
| documents / chunks | lee su área + `general` | + crea/edita en su área | todo | bypass RLS |
| incidents | lee | + crea/edita | + borra | bypass RLS |
| queries / feedback | solo los propios | solo los propios | lee todo | bypass RLS |
| golden_dataset | lee | lee | escribe | bypass RLS |
| audit_events | — | — | lee | escribe (y triggers) |
| Storage `documents/{area}/…` | descarga su área + `general` | + sube en su área | todo | bypass |

- **Rol y área** viven en `tfm.profiles` y se toman de `app_metadata` del usuario, que solo puede
  escribir `service_role` (al crearlo y en cada actualización posterior, migración 09). Un usuario no puede autoasignarse privilegios: lo garantiza el trigger
  `tfm.protect_profile_privileges` (verificado en los tests).
- `match_chunks` es `SECURITY INVOKER`: con el JWT de un usuario aplica RLS; el `rag-service`
  (service_role) filtra por área explícitamente con `filter_area`.
- `anon` no tiene acceso a los esquemas de negocio.

Para cambiar el rol/área de un usuario (como admin en Studio o con service_role):

```sql
update tfm.profiles set role = 'editor', area = 'operaciones' where email = 'usuario@produbanco.com';
```

### SSO con Microsoft (Azure AD / Entra ID)

1. Azure Portal → *App registrations* → *New registration*.
2. Redirect URI (Web): `http://localhost:54321/auth/v1/callback`.
3. *Certificates & secrets* → nuevo client secret.
4. En `.env`: `AZURE_ENABLED=true`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`,
   `AZURE_URL=https://login.microsoftonline.com/<TENANT_ID>`.
5. `docker compose up -d supabase-auth` para aplicar.

### Problemas frecuentes

| Síntoma | Solución |
|---------|----------|
| `bash\r: No such file or directory` o errores raros en SQL de init | Archivos con CRLF. `.gitattributes` fuerza LF; si clonaste antes: `git rm --cached -r . && git reset --hard` |
| Errores de autenticación tras regenerar `SUPABASE_JWT_SECRET` | Los scripts de `supabase/docker/db` solo corren con el volumen vacío: `docker compose down -v` y repetir bootstrap |
| `supabase-storage` no llega a healthy | `docker compose logs supabase-storage`; normalmente espera a que la BD termine su init |
| Ollama lento | Sin GPU, Qwen3 4B responde en ~5–20 s. Con NVIDIA, descomenta el bloque `deploy` en `docker-compose.dev.yml` |
| El modelo `qwen3:4b-instruct` no existe | Revisa los tags en https://ollama.com/library/qwen3 y ajusta `OLLAMA_MODEL` |
| Puerto 54321-54323 ocupado | Hay otra instancia de Supabase (p. ej. `supabase start`): `supabase stop` |

Reinicio completo (**borra BD, documentos, cache y modelos**):

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile observability down -v
```

---

## Estructura del repositorio (Fase 1)

```
soporte-bancario-rag/
├── .env.example
├── docker-compose.yml          # Supabase + Redis + Ollama (+ Jaeger opcional)
├── docker-compose.dev.yml      # expone DB/Redis/Ollama/Jaeger en 127.0.0.1
├── Makefile
├── scripts/
│   ├── bootstrap.sh            # Linux/macOS/Git Bash/WSL
│   └── bootstrap.ps1           # Windows PowerShell
└── supabase/
    ├── docker/                 # config de Kong e init de la BD (self-hosted)
    ├── migrations/             # 6 migraciones versionadas
    ├── tests/database/         # tests pgTAP
    └── seed.sql
```
