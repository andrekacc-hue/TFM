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
| 4. IA | Ollama + Qwen3 4B Instruct · embeddings multilingual-MiniLM (384d) · reranker cross-encoder · adapters Claude/OpenAI |

## Estado por fases

| Fase | Contenido | Estado |
|------|-----------|--------|
| 1 | Infraestructura, Supabase, migraciones, bootstrap | ✅ |
| 2 | Librería compartida + rag-service | ⏳ |
| 3 | ingest-service + worker Redis Streams | ⏳ |
| 4 | api-gateway + analytics-service | ⏳ |
| 5 | Edge Functions de Supabase | ⏳ |
| 6 | Frontend React (Admin Portal) | ⏳ |
| 7 | Bot de Microsoft Teams | ⏳ |
| 8 | Evaluación RAGAs, observabilidad, documentación | ⏳ |

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
  escribir `service_role`. Un usuario no puede autoasignarse privilegios: lo garantiza el trigger
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
