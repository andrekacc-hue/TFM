"""Configura y despliega las Edge Functions de la Fase 5 en Supabase Cloud.

Pasos:
  1. Genera (o reutiliza) TFM_WEBHOOK_SECRET y lo guarda en .env.
  2. Guarda en Supabase Vault la URL de las funciones y el secreto (los lee el trigger SQL
     de storage.objects; nunca se versionan).
  3. Define los secretos de las funciones (supabase secrets set, vía archivo temporal).
  4. Despliega on-document-upload y reindex-document (sin verificación JWT de plataforma).

Requisitos: haber iniciado sesión en la CLI una vez (``npx supabase login``) o tener
SUPABASE_ACCESS_TOKEN en el entorno; .env con SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
(sb_secret_...), SUPABASE_DB_URL e INTERNAL_API_KEY.

Uso:
    python scripts/configure_edge_functions.py              # todo
    python scripts/configure_edge_functions.py --skip-deploy
"""

from __future__ import annotations

import argparse
import os
import re
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path

import psycopg
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
FUNCTIONS = ["on-document-upload", "reindex-document"]


def npx() -> str:
    return "npx.cmd" if os.name == "nt" else "npx"


def set_env_value(key: str, value: str) -> None:
    text = ENV_PATH.read_text(encoding="utf-8")
    line = f"{key}={value}"
    text = re.sub(rf"(?m)^{key}=.*$", line, text) if re.search(rf"(?m)^{key}=", text) else text.rstrip("\n") + f"\n{line}\n"
    ENV_PATH.write_text(text, encoding="utf-8", newline="\n")


def upsert_vault_secret(conn: psycopg.Connection, name: str, value: str) -> None:
    row = conn.execute("select id from vault.secrets where name = %s", (name,)).fetchone()
    if row:
        conn.execute("select vault.update_secret(%s, %s)", (row[0], value))
    else:
        conn.execute("select vault.create_secret(%s, %s, %s)", (value, name, "Fase 5: trigger de Storage → Edge Functions"))


def supabase_cli(*args: str) -> None:
    result = subprocess.run([npx(), "--yes", "supabase@latest", *args], cwd=ROOT, text=True, capture_output=True,
                            encoding="utf-8", errors="replace")
    output = (result.stdout + result.stderr).strip()
    # Nunca imprimir valores de secretos: solo las últimas líneas informativas de la CLI
    for line in output.splitlines()[-6:]:
        print(f"    {line}")
    if result.returncode != 0:
        raise SystemExit(f"✖ supabase {' '.join(args[:2])} falló (¿hiciste 'npx supabase login'?)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--skip-deploy", action="store_true", help="Solo Vault y secretos")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

    env = dotenv_values(ENV_PATH)
    url = (env.get("SUPABASE_URL") or "").rstrip("/")
    secret_key = env.get("SUPABASE_SERVICE_ROLE_KEY") or ""
    match = re.match(r"https://([a-z0-9]+)\.supabase\.co", url)
    if not match:
        return print("✖ SUPABASE_URL debe ser https://<ref>.supabase.co", file=sys.stderr) or 1
    if not secret_key.startswith("sb_secret_"):
        return print("✖ SUPABASE_SERVICE_ROLE_KEY debe ser la clave sb_secret_…", file=sys.stderr) or 1
    project_ref = match.group(1)

    print("1. Secreto del webhook")
    webhook_secret = env.get("TFM_WEBHOOK_SECRET") or ""
    if len(webhook_secret) < 32:
        webhook_secret = secrets.token_urlsafe(32)
        set_env_value("TFM_WEBHOOK_SECRET", webhook_secret)
        print("   ✔ generado y guardado en .env")
    else:
        print("   ✔ reutilizado de .env")

    print("2. Supabase Vault (lo usa el trigger de storage.objects)")
    with psycopg.connect(env["SUPABASE_DB_URL"], autocommit=True) as conn:
        upsert_vault_secret(conn, "tfm_edge_functions_url", f"{url}/functions/v1")
        upsert_vault_secret(conn, "tfm_webhook_secret", webhook_secret)
    print("   ✔ tfm_edge_functions_url y tfm_webhook_secret")

    print("3. Secretos de las funciones")
    function_secrets = {"TFM_SECRET_KEY": secret_key, "TFM_WEBHOOK_SECRET": webhook_secret}
    if env.get("INGEST_PUBLIC_URL") and env.get("INTERNAL_API_KEY"):
        function_secrets |= {"TFM_INGEST_API_URL": env["INGEST_PUBLIC_URL"], "TFM_INTERNAL_API_KEY": env["INTERNAL_API_KEY"]}
        print("   · INGEST_PUBLIC_URL definida: las funciones avisarán al ingest-service al instante")
    else:
        print("   · sin INGEST_PUBLIC_URL: el outbox poller encola los documentos (≤ 15 s)")
    with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False, encoding="utf-8") as tmp:
        tmp.write("\n".join(f"{k}={v}" for k, v in function_secrets.items()))
        tmp_path = tmp.name
    try:
        supabase_cli("secrets", "set", "--project-ref", project_ref, "--env-file", tmp_path)
    finally:
        os.unlink(tmp_path)
    print(f"   ✔ {', '.join(function_secrets)}")

    if args.skip_deploy:
        return 0
    print("4. Despliegue")
    supabase_cli("functions", "deploy", *FUNCTIONS, "--project-ref", project_ref, "--no-verify-jwt", "--use-api")
    for name in FUNCTIONS:
        print(f"   ✔ {url}/functions/v1/{name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
