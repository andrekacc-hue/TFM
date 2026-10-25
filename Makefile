# Comandos de uso frecuente (Linux/macOS/WSL/Git Bash con make).
# En PowerShell usa scripts\bootstrap.ps1 y docker compose directamente.

COMPOSE := docker compose -f docker-compose.yml -f docker-compose.dev.yml

.DEFAULT_GOAL := help
.PHONY: help bootstrap up down restart ps logs migrate seed test-db psql pull-model observability reset

help: ## Muestra esta ayuda
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

bootstrap: ## Setup completo: .env, stack, migraciones, seed, admin demo, modelo
	./scripts/bootstrap.sh

up: ## Levanta la infraestructura
	$(COMPOSE) up -d

down: ## Detiene la infraestructura (conserva volúmenes)
	$(COMPOSE) down

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

psql: ## Consola psql en la base de datos
	$(COMPOSE) exec supabase-db psql -h localhost -U postgres -d postgres

pull-model: ## Descarga el modelo configurado en OLLAMA_MODEL
	$(COMPOSE) exec ollama ollama pull $$(grep -E '^OLLAMA_MODEL=' .env | cut -d= -f2-)

observability: ## Levanta Jaeger (UI en http://localhost:16686)
	$(COMPOSE) --profile observability up -d jaeger

reset: ## DESTRUCTIVO: elimina contenedores y volúmenes (BD, Storage, Redis, modelos)
	$(COMPOSE) --profile observability down -v
