#!/usr/bin/env bash
# =====================================================================
#  bootstrap.sh — Setup inicial completo del entorno local
#
#  1. Crea .env desde .env.example y genera los secretos vacíos
#     (JWT secret, anon/service_role keys, claves internas).
#  2. Levanta Supabase, Redis y Ollama con Docker Compose.
#  3. Espera a que los servicios estén healthy.
#  4. Aplica las migraciones pendientes (supabase/migrations/*.sql).
#  5. Carga datos de ejemplo (supabase/seed.sql).
#  6. Crea el usuario administrador de demostración.
#  7. Descarga el modelo de Ollama.
#
#  Uso:
#    ./scripts/bootstrap.sh                 # todo
#    ./scripts/bootstrap.sh --skip-model    # sin descargar el LLM (~2.5 GB)
#    ./scripts/bootstrap.sh --no-seed       # sin datos de ejemplo
#    ./scripts/bootstrap.sh --with-tests    # todo + tests pgTAP
#    ./scripts/bootstrap.sh --migrate-only  # solo migraciones (stack levantado)
#    ./scripts/bootstrap.sh --test-only     # solo tests pgTAP (stack levantado)
#
#  Funciona en Linux, macOS y Windows (Git Bash / WSL).
# =====================================================================
set -euo pipefail

# Git Bash convierte rutas tipo /workspace/... a rutas Windows: desactivarlo
export MSYS_NO_PATHCONV=1

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ENV_FILE=".env"
# Modo self-hosted: Supabase y Ollama en contenedores (perfiles del compose)
COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile supabase-local --profile ollama-local)
CONTAINER_SUPABASE_DIR="/workspace/supabase"

SKIP_MODEL=false
NO_SEED=false
WITH_TESTS=false
MIGRATE_ONLY=false
TEST_ONLY=false

# ---------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------
log()  { printf '\033[1;34m[bootstrap]\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m[bootstrap] ✔\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[bootstrap] ⚠\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[bootstrap] ✖\033[0m %s\n' "$*" >&2; exit 1; }

usage() { sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'; }

for arg in "$@"; do
  case "$arg" in
    --skip-model)   SKIP_MODEL=true ;;
    --no-seed)      NO_SEED=true ;;
    --with-tests)   WITH_TESTS=true ;;
    --migrate-only) MIGRATE_ONLY=true ;;
    --test-only)    TEST_ONLY=true ;;
    -h|--help)      usage; exit 0 ;;
    *)              die "Opción desconocida: $arg (usa --help)" ;;
  esac
done

require_cmd() { command -v "$1" >/dev/null 2>&1 || die "Falta '$1'. $2"; }

get_env() {
  # Último valor de KEY en .env (permite '=' dentro del valor)
  grep -E "^$1=" "$ENV_FILE" 2>/dev/null | tail -n1 | cut -d= -f2- | tr -d '\r' || true
}

set_env() {
  local key="$1" value="$2"
  if grep -qE "^${key}=" "$ENV_FILE"; then
    sed -i.bak "s|^${key}=.*|${key}=${value}|" "$ENV_FILE" && rm -f "${ENV_FILE}.bak"
  else
    printf '%s=%s\n' "$key" "$value" >> "$ENV_FILE"
  fi
}

b64url() { openssl base64 -A | tr '+/' '-_' | tr -d '='; }

make_jwt() {
  # JWT HS256 compatible con Supabase (role = anon | service_role), 10 años
  local role="$1" secret="$2" iat exp header payload signature
  iat=$(date +%s)
  exp=$((iat + 10 * 365 * 24 * 3600))
  header=$(printf '{"alg":"HS256","typ":"JWT"}' | b64url)
  payload=$(printf '{"role":"%s","iss":"supabase","iat":%d,"exp":%d}' "$role" "$iat" "$exp" | b64url)
  signature=$(printf '%s.%s' "$header" "$payload" | openssl dgst -sha256 -hmac "$secret" -binary | b64url)
  printf '%s.%s.%s' "$header" "$payload" "$signature"
}

psql_exec() {
  "${COMPOSE[@]}" exec -T supabase-db \
    psql -h localhost -U postgres -d postgres -v ON_ERROR_STOP=1 -q "$@"
}

wait_healthy() {
  local service="$1" timeout="${2:-240}" elapsed=0 cid status
  cid=$("${COMPOSE[@]}" ps -q "$service")
  [[ -n "$cid" ]] || die "El servicio $service no está creado"
  while true; do
    status=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$cid")
    [[ "$status" == "healthy" ]] && { ok "$service healthy"; return 0; }
    (( elapsed >= timeout )) && die "$service no alcanzó estado healthy en ${timeout}s (estado: $status). Revisa: docker compose logs $service"
    sleep 3
    elapsed=$((elapsed + 3))
  done
}

wait_http() {
  local url="$1" name="$2" timeout="${3:-120}" elapsed=0
  shift 3
  until curl -fsS -o /dev/null "$@" "$url"; do
    (( elapsed >= timeout )) && die "$name no responde en $url"
    sleep 3
    elapsed=$((elapsed + 3))
  done
  ok "$name responde"
}

# ---------------------------------------------------------------------
# Pasos
# ---------------------------------------------------------------------
check_prerequisites() {
  require_cmd docker "Instala Docker Desktop: https://docs.docker.com/get-docker/"
  docker compose version >/dev/null 2>&1 || die "Se requiere Docker Compose v2 ('docker compose')."
  docker info >/dev/null 2>&1 || die "El daemon de Docker no está corriendo. Inicia Docker Desktop."
  require_cmd openssl "Viene con Git Bash; en Linux instala el paquete openssl."
  require_cmd curl "Instala curl."
}

prepare_env() {
  if [[ ! -f "$ENV_FILE" ]]; then
    cp .env.example "$ENV_FILE"
    ok ".env creado desde .env.example"
  fi

  local jwt_secret anon_key service_key
  jwt_secret=$(get_env SUPABASE_JWT_SECRET)

  if [[ -z "$jwt_secret" ]]; then
    if docker volume inspect soporte-bancario-rag_supabase-db-data >/dev/null 2>&1; then
      warn "Se generará un nuevo JWT secret pero ya existe el volumen de la BD."
      warn "Si algo falla con la autenticación: docker compose down -v && ./scripts/bootstrap.sh"
    fi
    jwt_secret=$(openssl rand -hex 32)
    set_env SUPABASE_JWT_SECRET "$jwt_secret"
    set_env SUPABASE_ANON_KEY ""
    set_env SUPABASE_SERVICE_ROLE_KEY ""
    ok "SUPABASE_JWT_SECRET generado"
  fi

  anon_key=$(get_env SUPABASE_ANON_KEY)
  service_key=$(get_env SUPABASE_SERVICE_ROLE_KEY)
  if [[ -z "$anon_key" ]]; then
    anon_key=$(make_jwt anon "$jwt_secret")
    set_env SUPABASE_ANON_KEY "$anon_key"
    ok "SUPABASE_ANON_KEY generada"
  fi
  if [[ -z "$service_key" ]]; then
    service_key=$(make_jwt service_role "$jwt_secret")
    set_env SUPABASE_SERVICE_ROLE_KEY "$service_key"
    ok "SUPABASE_SERVICE_ROLE_KEY generada"
  fi
  set_env VITE_SUPABASE_ANON_KEY "$anon_key"

  [[ -n "$(get_env SECRET_KEY_BASE)" ]]    || set_env SECRET_KEY_BASE "$(openssl rand -hex 32)"
  [[ -n "$(get_env PG_META_CRYPTO_KEY)" ]] || set_env PG_META_CRYPTO_KEY "$(openssl rand -hex 16)"

  local internal_key
  internal_key=$(get_env INTERNAL_API_KEY)
  if [[ -z "$internal_key" || "$internal_key" == "cambiar-en-produccion" ]]; then
    set_env INTERNAL_API_KEY "$(openssl rand -hex 24)"
    ok "INTERNAL_API_KEY generada"
  fi

  # Mantener SUPABASE_DB_URL coherente con POSTGRES_PASSWORD
  local pg_pass
  pg_pass=$(get_env POSTGRES_PASSWORD)
  set_env SUPABASE_DB_URL "postgresql://postgres:${pg_pass}@localhost:54322/postgres"
  [[ "$pg_pass" == "postgres" ]] && warn "POSTGRES_PASSWORD usa el valor por defecto (aceptable solo en desarrollo)."
  return 0
}

start_stack() {
  log "Descargando imágenes y levantando la infraestructura (la primera vez tarda varios minutos)..."
  "${COMPOSE[@]}" up -d
  wait_healthy supabase-db
  wait_healthy supabase-auth
  wait_healthy supabase-storage
  wait_healthy redis
  wait_healthy ollama
  wait_http "http://localhost:54321/auth/v1/health" "Supabase API (Kong)" 120 \
    -H "apikey: $(get_env SUPABASE_ANON_KEY)"
}

apply_migrations() {
  log "Aplicando migraciones..."
  psql_exec -c "create schema if not exists supabase_migrations;
                create table if not exists supabase_migrations.schema_migrations (
                  version text primary key, statements text[], name text);"

  local file name version applied
  for file in supabase/migrations/*.sql; do
    name=$(basename "$file" .sql)
    version=${name%%_*}
    applied=$(psql_exec -tA -c "select 1 from supabase_migrations.schema_migrations where version = '${version}'" | tr -d '[:space:]')
    if [[ "$applied" == "1" ]]; then
      log "· ${name} (ya aplicada)"
      continue
    fi
    log "→ ${name}"
    # Migración + registro en una única transacción
    psql_exec --single-transaction \
      -f "${CONTAINER_SUPABASE_DIR}/migrations/${name}.sql" \
      -c "insert into supabase_migrations.schema_migrations (version, name) values ('${version}', '${name#*_}')"
  done
  # PostgREST debe recargar el esquema para exponer las tablas nuevas
  psql_exec -c "notify pgrst, 'reload schema';"
  ok "Migraciones al día"
}

seed_database() {
  log "Cargando seed.sql..."
  psql_exec -f "${CONTAINER_SUPABASE_DIR}/seed.sql"
  ok "Datos de ejemplo cargados"
}

create_demo_admin() {
  local email password service_key response code
  email=$(get_env DEMO_ADMIN_EMAIL)
  password=$(get_env DEMO_ADMIN_PASSWORD)
  service_key=$(get_env SUPABASE_SERVICE_ROLE_KEY)
  [[ -n "$email" && -n "$password" ]] || { warn "DEMO_ADMIN_EMAIL/PASSWORD vacíos: se omite el usuario demo"; return 0; }

  log "Creando usuario administrador de demostración ($email)..."
  response=$(mktemp)
  code=$(curl -sS -o "$response" -w '%{http_code}' -X POST "http://localhost:54321/auth/v1/admin/users" \
    -H "apikey: ${service_key}" \
    -H "Authorization: Bearer ${service_key}" \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"${email}\",\"password\":\"${password}\",\"email_confirm\":true,\"app_metadata\":{\"role\":\"admin\",\"area\":\"general\"},\"user_metadata\":{\"full_name\":\"Administrador Demo\"}}")
  case "$code" in
    200|201) ok "Usuario demo creado" ;;
    422)     log "· El usuario demo ya existe" ;;
    *)       warn "No se pudo crear el usuario demo (HTTP $code): $(cat "$response")" ;;
  esac
  rm -f "$response"

  # Garantiza rol admin aunque el usuario ya existiera
  psql_exec -c "update public.profiles set role = 'admin', area = 'general' where email = '${email}';"
}

pull_model() {
  local model
  model=$(get_env OLLAMA_MODEL)
  model=${model:-qwen3:4b-instruct}
  log "Descargando modelo Ollama '${model}' (puede tardar varios minutos)..."
  "${COMPOSE[@]}" exec -T ollama ollama pull "$model"
  ok "Modelo ${model} disponible"
}

run_tests() {
  log "Ejecutando tests pgTAP de la base de datos..."
  local output failed=0 file
  for file in supabase/tests/database/*.test.sql; do
    output=$(psql_exec -tA -f "${CONTAINER_SUPABASE_DIR}/tests/database/$(basename "$file")") || failed=1
    printf '%s\n' "$output"
    if grep -q '^not ok' <<<"$output"; then failed=1; fi
  done
  (( failed == 0 )) || die "Hay tests fallidos"
  ok "Todos los tests pasaron"
}

print_summary() {
  cat <<EOF

$(printf '\033[1;32m')=====================================================================
  Entorno listo
=====================================================================$(printf '\033[0m')
  Supabase Studio   http://localhost:54323
  Supabase API      http://localhost:54321
  PostgreSQL        postgresql://postgres:****@localhost:54322/postgres
  Redis             redis://localhost:6379
  Ollama            http://localhost:11434
  Admin demo        $(get_env DEMO_ADMIN_EMAIL) / (ver DEMO_ADMIN_PASSWORD en .env)

  Verificación rápida:
    curl http://localhost:11434/api/tags
    ./scripts/bootstrap.sh --test-only
EOF
}

# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------
check_prerequisites

if $TEST_ONLY; then
  run_tests
  exit 0
fi

if $MIGRATE_ONLY; then
  apply_migrations
  $NO_SEED || seed_database
  exit 0
fi

prepare_env
start_stack
apply_migrations
$NO_SEED || seed_database
create_demo_admin
$SKIP_MODEL || pull_model
if $WITH_TESTS; then run_tests; fi
print_summary
