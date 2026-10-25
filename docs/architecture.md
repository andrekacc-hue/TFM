# Arquitectura

Asistente de soporte técnico para TI Producción de Produbanco: responde preguntas operativas en lenguaje
natural con **RAG** (Retrieval-Augmented Generation) sobre manuales, procedimientos, FAQ e incidentes. Cada
respuesta cita sus fuentes verificables, y el asistente se abstiene cuando la documentación no tiene la
respuesta.

Diagramas (Mermaid; GitHub y VS Code los renderizan):

| Diagrama | Archivo |
|----------|---------|
| C4 nivel 1 — contexto | [`diagrams/c4-context.mmd`](diagrams/c4-context.mmd) |
| C4 nivel 2 — contenedores | [`diagrams/c4-container.mmd`](diagrams/c4-container.mmd) |
| Secuencia de una consulta RAG | [`diagrams/sequence-rag.mmd`](diagrams/sequence-rag.mmd) |

## 1. Capas

| Capa | Componentes | Responsabilidad |
|------|-------------|-----------------|
| 1. Presentación | Portal React (`frontend/`), bot de Teams (`teams-bot/`) | Consulta, gestión documental, dashboard, evaluación; canal conversacional |
| 2. Middleware | `api-gateway`, `rag-service`, `ingest-service`, `analytics-service` (FastAPI) + Redis | Autenticación y autorización, pipeline RAG, ingesta asíncrona, métricas |
| 3. Datos | Supabase: Postgres 15 + pgvector, Auth, Storage, Realtime, Edge Functions | Persistencia, búsqueda vectorial, RLS, eventos |
| 4. IA | Ollama (`gemma4:31b-cloud`) o Claude/OpenAI; sentence-transformers | Generación, embeddings (384 d), reranking |

## 2. Contenedores

| Contenedor | Puerto | Función |
|------------|--------|---------|
| `frontend` | 3000 | SPA servida por nginx. Habla con Supabase (login, Storage, Realtime) y con el gateway (todo lo demás) |
| `teams-bot` | 3978 | Microsoft 365 Agents SDK. Actúa en nombre del usuario de Teams (`X-User-Email`) |
| `api-gateway` | 8000 | Único punto de entrada público: JWT de Supabase (ES256 vía JWKS), rol y área desde `tfm.profiles`, rate limiting, proxy, OpenAPI |
| `rag-service` | 8001 | Guardrails → embedding → `match_chunks` → reranking → LLM → guardrails de salida → `tfm.queries` |
| `ingest-service` | 8002 | API de subida + worker de Redis Streams: carga, chunking, embeddings, reintentos, DLQ, outbox |
| `analytics-service` | 8003 | Métricas (`tfm.metrics_*` en SQL) y exportación CSV/JSON |
| `redis` | 6379 | Stream de ingesta, caché de embeddings, contadores del rate limit |
| `jaeger` | 16686 | Trazas OpenTelemetry (perfil `observability`, opcional) |

Los servicios internos solo aceptan peticiones con `X-Internal-Api-Key` y en producción no se publican: solo se
exponen el gateway, el portal y el bot.

## 3. Flujos principales

### Consulta (ver [`sequence-rag.mmd`](diagrams/sequence-rag.mmd))

1. El portal envía la pregunta con el JWT del usuario. El gateway lo verifica, carga el rol y el área (con
   caché de 60 s) y aplica el límite de 20 consultas por minuto.
2. El rag-service aplica los guardrails de entrada: inyección de prompts y datos sensibles como tarjetas,
   cédulas o credenciales.
3. Genera el embedding (MiniLM multilingüe, 384 d, con caché en Redis) y llama a `tfm.match_chunks` **con el
   JWT del usuario**: Postgres aplica RLS y solo devuelve documentos de su área y de `general`.
4. Si ningún fragmento supera el umbral de similitud (0,35), se abstiene sin llamar al LLM.
5. Un cross-encoder multilingüe (`mmarco-mMiniLMv2`) reordena los 20 candidatos y se queda con 5.
6. El LLM responde con un prompt que le exige citar `[Fuente: documento, sección]` o usar la frase exacta de
   abstención. Los guardrails de salida enmascaran datos sensibles y normalizan la abstención.
7. La consulta se registra en `tfm.queries` con las latencias por etapa, las fuentes, los tokens y el motivo
   de abstención. Esas filas alimentan el dashboard.

### Ingesta

1. Un editor sube el archivo desde el portal directamente a Supabase Storage. RLS valida que la ruta
   corresponde a su área.
2. Un trigger de Postgres (`pg_net`) invoca la Edge Function `on-document-upload`, que registra el documento en
   `tfm.documents` con estado `pending`.
3. El `ingest-service` lee la tabla como un buzón (**patrón outbox**, `tfm.claim_pending_documents` con
   `SKIP LOCKED`) y publica en el Redis Stream. Las Edge Functions corren en la nube de Supabase y no alcanzan
   Redis.
4. El worker descarga el archivo, lo convierte (PDF, DOCX, Markdown, HTML), lo trocea (700 caracteres con
   solape de 120 y encabezado de sección), calcula los embeddings y escribe `tfm.chunks`. Tras 3 fallos, el
   documento va a la DLQ.
5. El portal recibe el cambio de estado por **Realtime**.

## 4. Modelo de datos (schema `tfm`)

| Tabla | Contenido |
|-------|-----------|
| `profiles` | Rol (`viewer`/`editor`/`admin`) y área de cada usuario; se sincroniza desde `auth.users` |
| `documents` | Metadatos, estado de indexación, hash de contenido (deduplicación), área |
| `chunks` | Texto, `embedding vector(384)` con índice HNSW, metadatos (sección, página) |
| `incidents` | Histórico de incidentes (síntoma, diagnóstico, resolución) |
| `queries` · `feedback` | Registro de consultas con latencias y valoraciones 👍/👎 |
| `golden_dataset` · `evaluation_runs` | Preguntas de referencia y resultados de RAGAs |
| `audit_events` | Auditoría automática (triggers) de cambios en documentos, incidentes, perfiles y golden dataset |

Migraciones en [`supabase/migrations/`](../supabase/migrations/) (01–11). Tests de base de datos con pgTAP en
[`supabase/tests/database/`](../supabase/tests/database/).

## 5. Seguridad

- **Autenticación:** Supabase Auth (correo y contraseña; SSO con Azure AD opcional). El gateway verifica la
  firma ES256 con el JWKS del proyecto, con 30 s de tolerancia de reloj.
- **Autorización en dos niveles:** el gateway exige el rol mínimo por endpoint, y Postgres aplica **RLS** por
  rol y área en todas las tablas. La búsqueda vectorial también respeta RLS: un usuario nunca recupera
  fragmentos de otra área, aunque manipule la petición.
- **Rol vivo:** el rol y el área se leen de `tfm.profiles`, no de los claims del JWT. Si se degrada a un
  usuario, el cambio se aplica en menos de un minuto.
- **Servicio a servicio:** clave interna compartida. El bot añade `X-User-Email`, que el gateway compara de
  forma exacta (sin `ilike`, que permitiría comodines).
- **Guardrails** de entrada (inyección de prompts, datos sensibles) y de salida (enmascarado, abstención).
- **Secretos** solo en `.env`, fuera de git, y en Supabase Vault (para el trigger → Edge Function). Se usan las
  claves `sb_secret_`/`sb_publishable_`; las claves JWT legacy están desactivadas.
- **Rate limiting** por usuario con ventana deslizante y contadores en Redis. Si Redis falla, deja pasar la
  petición (*fail-open*).

## 6. Decisiones de diseño

| Decisión | Alternativa descartada | Motivo |
|----------|------------------------|--------|
| Pipeline RAG explícito (clases pequeñas) | Cadenas de LangChain | Latencia medible por etapa, tests sin red, menos dependencias |
| Reranker multilingüe `mmarco-mMiniLMv2` | `ms-marco-MiniLM` (spec) | Corpus en español: mejor orden en la comparación realizada |
| Abstención en dos capas (umbral + LLM) | Solo el prompt | Lo fuera de alcance no gasta LLM (≈0,15 s); los temas vecinos los rechaza el modelo |
| Adapters de LLM intercambiables | Un proveedor fijo | Ollama local/Cloud, Claude u OpenAI con `LLM_PROVIDER` |
| Outbox en Postgres para la ingesta | Edge Function → Redis directo | Las Edge Functions no alcanzan Redis; además, reencola lo atascado |
| Métricas agregadas en SQL | Agregar en Python | Percentiles y tasas sin transferir filas |
| Microsoft 365 Agents SDK | Bot Framework SDK (spec) | El SDK de Python se archivó en enero de 2026 |
| Entorno aislado para RAGAs | Mismo `.venv` | RAGAs 0.4 fija versiones de LangChain incompatibles |

## 7. Observabilidad

- **Logs JSON** (structlog) con `trace_id` propagado por la cabecera `x-trace-id` del gateway a los servicios.
- **Métricas de negocio** en el dashboard: volumen, latencia por etapa (p50–p99), satisfacción, abstenciones,
  documentos más citados y preguntas sin respuesta.
- **Trazas distribuidas** (opcional): con `ENABLE_TRACING=true` y `make observability`, cada servicio exporta
  spans OTLP a Jaeger (http://localhost:16686). Instrumenta FastAPI y httpx (incluye Supabase y Ollama) y añade
  spans `rag.guardrails`, `rag.retrieval`, `rag.rerank` y `rag.generation` dentro de cada consulta.
- **Calidad:** evaluación con RAGAs y golden dataset ([`evaluation.md`](evaluation.md)).

## 8. Calidad y pruebas

| Suite | Herramienta | Tests |
|-------|-------------|-------|
| Unitarios Python (shared, rag, ingest, analytics, gateway) | pytest | 57 · 77 · 62 · 12 · 26 |
| Bot de Teams | pytest + Teams simulado | 19 |
| Portal | Vitest | 39 |
| Edge Functions | Deno test | 16 |
| Base de datos (RLS, funciones, triggers) | pgTAP | 64 |
| Integración extremo a extremo (stack real) | pytest | 16 |
| E2E del portal | Playwright | 3 |
| Calidad de respuestas | RAGAs + golden dataset | 30 preguntas |
| Carga | Locust | [`scripts/load_test.py`](../scripts/load_test.py) |
