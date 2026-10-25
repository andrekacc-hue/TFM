# Guía de despliegue

Tres modos, de menos a más autónomo. Todos usan el mismo `docker-compose.yml`; los perfiles deciden qué se
levanta.

| Modo | Supabase | LLM | Uso |
|------|----------|-----|-----|
| **Cloud** (por defecto) | Supabase Cloud | Ollama nativo en el host (modelos `*-cloud`) | Desarrollo y demo del TFM |
| **Self-hosted** | Contenedores (`--profile supabase-local`) | Ollama en contenedor (`--profile ollama-local`) | Sin dependencias externas, datos en local |
| **Producción** | Supabase Cloud (plan Pro) o self-hosted gestionado | Ollama con GPU, Claude u OpenAI | Despliegue en el banco |

## 1. Requisitos

- Docker Desktop (Windows con WSL2) o Docker Engine 24+ con Compose v2. Mínimo 8 GB de RAM para los
  contenedores; 16 GB en modo self-hosted.
- Python 3.12 (scripts, migraciones y evaluación) y Node 20+ (solo para desarrollar el portal).
- Ollama 0.40+ con sesión iniciada (`ollama signin`) para los modelos Cloud, o una GPU para modelos locales.
- Supabase CLI (`npx supabase`) para desplegar las Edge Functions.

## 2. Modo cloud (paso a paso)

```powershell
git clone https://github.com/andrekacc-hue/TFM.git soporte-bancario-rag; cd soporte-bancario-rag
Copy-Item .env.example .env        # y completar los valores (ver tabla)
py -3.12 -m venv .venv; .\.venv\Scripts\pip install "psycopg[binary]" python-dotenv httpx

# 1. Base de datos: migraciones 01–11 + datos de ejemplo + 64 tests pgTAP
.\.venv\Scripts\python scripts\apply_migrations.py --seed --test

# 2. Edge Functions + secretos de Vault (requiere: npx supabase login)
make deploy-functions              # o: python scripts\configure_edge_functions.py

# 3. Modelo
ollama pull gemma4:31b-cloud

# 4. Servicios + portal + bot
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
Invoke-RestMethod http://localhost:8000/ready     # status ok y 4 checks

# 5. Corpus de ejemplo y evaluación
.\.venv\Scripts\python scripts\seed_corpus.py --api http://127.0.0.1:8002
```

Portal en http://localhost:3000, API en http://localhost:8000/docs y bot en http://localhost:3978/api/messages.

### Variables clave de `.env`

| Variable | Valor |
|----------|-------|
| `SUPABASE_URL` | `https://<ref>.supabase.co` |
| `SUPABASE_ANON_KEY` · `VITE_SUPABASE_ANON_KEY` | Clave **publishable** (`sb_publishable_…`) |
| `SUPABASE_SERVICE_ROLE_KEY` | Clave **secret** (`sb_secret_…`); nunca en el frontend |
| `SUPABASE_DB_URL` | Cadena del *Session pooler*, con la contraseña codificada para URL |
| `INTERNAL_API_KEY` | Aleatoria, ≥ 32 caracteres (`python -c "import secrets;print(secrets.token_urlsafe(32))"`) |
| `TFM_WEBHOOK_SECRET` | Aleatoria; la copia `configure_edge_functions.py` a Vault y a la función |
| `LLM_PROVIDER` · `OLLAMA_MODEL` | `ollama` · `gemma4:31b-cloud` (o `anthropic`/`openai` con su clave) |
| `CORS_ORIGINS` | URL pública del portal |
| `MICROSOFT_APP_ID/PASSWORD/TENANT_ID` | Azure Bot (vacías = modo anónimo); ver [`teams-bot.md`](teams-bot.md) |
| `ENABLE_TRACING` | `true` solo con Jaeger levantado (`make observability`) |

## 3. Modo self-hosted

```powershell
.\scripts\bootstrap.ps1            # Linux/macOS: ./scripts/bootstrap.sh
```

El script genera los secretos de `.env` y levanta Supabase (Postgres, Auth, REST, Realtime, Storage, Kong,
Studio), Redis, Ollama y los microservicios. Después aplica las migraciones y los datos de ejemplo, crea el
admin de demostración y descarga el modelo. Studio queda en http://localhost:54323.

## 4. Producción: lista de verificación

**Red y TLS**
- [ ] Un proxy inverso (nginx, Traefik o Azure Front Door) termina TLS delante del portal (`:3000`), el gateway
      (`:8000`) y el bot (`:3978`). No publicar `docker-compose.dev.yml`: solo expone puertos internos en
      `127.0.0.1` para depurar.
- [ ] `CORS_ORIGINS` limitado al dominio del portal; `SITE_URL` y `ADDITIONAL_REDIRECT_URLS` en Supabase Auth.
- [ ] Messaging endpoint del Azure Bot apuntando al dominio definitivo (no ngrok).

**Secretos**
- [ ] `.env` fuera del repositorio (ya está en `.gitignore`); en servidores, un gestor de secretos (Azure Key
      Vault, Docker secrets).
- [ ] Rotar `INTERNAL_API_KEY`, `TFM_WEBHOOK_SECRET`, la clave `sb_secret_` y `MICROSOFT_APP_PASSWORD`; las
      claves JWT legacy de Supabase deben seguir **desactivadas**.
- [ ] `DISABLE_SIGNUP=true`: los usuarios los crea un administrador o entran por SSO de Azure AD.

**Datos**
- [ ] Copias de seguridad de Postgres (PITR en Supabase Pro) y del bucket `documents`.
- [ ] Revisar periódicamente `tfm.audit_events` y la DLQ de ingesta (`GET /api/v1/documents/queue/stats`).

**Capacidad**
- [ ] Gateway y rag-service escalan horizontalmente (`docker compose up --scale rag-service=3`, o réplicas
      en Kubernetes). El rate limit ya se comparte entre réplicas vía Redis.
- [ ] El LLM marca la latencia (≈2 s de 2,4 s de p50). En producción conviene Ollama con GPU dedicada o un
      proveedor gestionado. Fijar `RATE_LIMIT_QUERY` según su capacidad.
- [ ] Redis ya tiene persistencia AOF y `maxmemory` en el compose: ajustar el límite al volumen real.

**Observabilidad**
- [ ] Recolectar los logs JSON (Loki, Elastic o Azure Monitor) y alertar sobre los 5xx del gateway, la DLQ
      con elementos y la tasa de abstención.
- [ ] `ENABLE_TRACING=true` con un colector OTLP (Jaeger, Tempo o Azure Monitor).

**Calidad**
- [ ] Ejecutar `scripts/run_evaluation.py --repeat 3` después de cada cambio de modelo, prompt, chunking o
      umbrales, y comparar con la ejecución anterior en el portal (Evaluación).

## 5. Verificación del despliegue

```powershell
Invoke-RestMethod https://<gateway>/ready                       # 4 checks en ok
make test-integration                                          # 16 tests contra el stack real
.\.venv\Scripts\python -m pytest tests\e2e                      # 3 E2E del portal (Playwright)
.\.venv-eval\Scripts\python scripts\run_evaluation.py --no-ragas   # abstención, recuperación y latencia (~2 min)
.\.venv-eval\Scripts\locust -f scripts\load_test.py --host https://<gateway> --headless -u 50 -r 2 -t 90s
```

## 6. Actualización

```powershell
git pull
.\.venv\Scripts\python scripts\apply_migrations.py --test       # solo aplica las pendientes
docker compose -f docker-compose.yml up -d --build              # recrea solo lo que cambió
make deploy-functions                                          # si cambiaron las Edge Functions
```
