# Comandos de uso frecuente (Linux/macOS/WSL/Git Bash con make).
# En PowerShell usa scripts\bootstrap.ps1 y docker compose directamente.

# Modo cloud (por defecto): Supabase Cloud + Ollama nativo; el compose levanta Redis y los microservicios.
# Modo self-hosted: make up-local (añade Supabase y Ollama en contenedores).
COMPOSE := docker compose -f docker-compose.yml -f docker-compose.dev.yml
LOCAL_PROFILES := --profile supabase-local --profile ollama-local

.DEFAULT_GOAL := help
.PHONY: help bootstrap up up-local down restart ps logs migrate seed test test-db test-integration test-functions deploy-functions openapi psql pull-model observability reset

PY := .venv/Scripts/python.exe
SERVICES := shared rag-service ingest-service analytics-service api-gateway

test: ## Tests unitarios de los 5 paquetes con cobertura
	@for s in $(SERVICES); do cov=app; [ $$s = shared ] && cov=shared; \
	  echo "== $$s =="; (cd services/$$s && ../../$(PY) -m pytest -q --cov=$$cov) || exit 1; done

test-integration: ## Tests extremo a extremo contra el stack levantado (crea y borra usuarios temporales)
	$(PY) -m pytest tests/integration -v

openapi: ## Exporta las especificaciones OpenAPI a docs/api/
	$(PY) scripts/export_openapi.py

test-functions: ## Tests unitarios de las Edge Functions (Deno)
	cd supabase/functions && deno task test && deno task check

deploy-functions: ## Configura Vault y secretos y despliega las Edge Functions (requiere npx supabase login)
	$(PY) scripts/configure_edge_functions.py

help: ## Muestra esta ayuda
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

bootstrap: ## Setup completo: .env, stack, migraciones, seed, admin demo, modelo
	./scripts/bootstrap.sh

up: ## Levanta Redis y los microservicios (modo cloud)
	$(COMPOSE) up -d --build

up-local: ## Levanta todo, incluido Supabase y Ollama en contenedores (modo self-hosted)
	$(COMPOSE) $(LOCAL_PROFILES) up -d --build

down: ## Detiene todos los contenedores (conserva volúmenes)
	$(COMPOSE) $(LOCAL_PROFILES) --profile observability down

restart: down up ## Reinicia la infraestructura

ps: ## Estado de los contenedores
	$(COMPOSE) ps

logs: ## Logs en vivo (make logs s=supabase-auth)
	$(COMPOSE) logs -f --tail=100 $(s)

migrate: ## Aplica migraciones pendientes
	./scripts/bootstrap.sh --migrate-only --no-seed

seed: ## Aplica migraciones y carga datos de ejemplo
	./scripts/bootstrap.sh --migrate-only

test-db: ## Ejecuta los tests pgTAP de la base de datos
	./scripts/bootstrap.sh --test-only

psql: ## Consola psql en la base de datos (modo self-hosted)
	$(COMPOSE) $(LOCAL_PROFILES) exec supabase-db psql -h localhost -U postgres -d postgres

pull-model: ## Descarga el modelo configurado en OLLAMA_MODEL (modo self-hosted)
	$(COMPOSE) $(LOCAL_PROFILES) exec ollama ollama pull $$(grep -E '^OLLAMA_MODEL=' .env | cut -d= -f2-)

observability: ## Levanta Jaeger (UI en http://localhost:16686)
	$(COMPOSE) --profile observability up -d jaeger

reset: ## DESTRUCTIVO: elimina contenedores y volúmenes (BD, Storage, Redis, modelos)
	$(COMPOSE) $(LOCAL_PROFILES) --profile observability down -v
