"""Aplica las migraciones de supabase/migrations a una base Postgres (Supabase Cloud o local).

Registra cada migración en ``supabase_migrations.schema_migrations`` (mismo formato que la
Supabase CLI), así que es idempotente: solo ejecuta las pendientes.

Uso:
    pip install "psycopg[binary]" python-dotenv
    python scripts/apply_migrations.py                 # usa SUPABASE_DB_URL de .env
    python scripts/apply_migrations.py --seed          # + supabase/seed.sql
    python scripts/apply_migrations.py --test          # + tests pgTAP (rollback, no deja datos)
    python scripts/apply_migrations.py --db-url "postgresql://..."

En Supabase Cloud usa la cadena del *Session pooler* (Dashboard -> Connect), ya que la
conexión directa db.<ref>.supabase.co solo tiene IPv6 en el plan gratuito.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
SUPABASE_DIR = ROOT_DIR / "supabase"
MIGRATIONS_DIR = SUPABASE_DIR / "migrations"

BOOKKEEPING_SQL = """
create schema if not exists supabase_migrations;
create table if not exists supabase_migrations.schema_migrations (
  version text primary key,
  statements text[],
  name text
);
"""


def apply_migrations(conn: psycopg.Connection) -> int:
    """Ejecuta las migraciones pendientes, cada una en su propia transacción.

    Args:
        conn: Conexión abierta en modo autocommit.

    Returns:
        Número de migraciones aplicadas.
    """
    conn.execute(BOOKKEEPING_SQL)
    applied = {
        row[0] for row in conn.execute("select version from supabase_migrations.schema_migrations")
    }

    count = 0
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        version, _, name = path.stem.partition("_")
        if version in applied:
            print(f"  · {path.stem} (ya aplicada)")
            continue
        print(f"  → {path.stem}")
        with conn.transaction():
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute(
                "insert into supabase_migrations.schema_migrations (version, name) values (%s, %s)",
                (version, name),
            )
        count += 1

    # PostgREST debe recargar el esquema para exponer los objetos nuevos
    conn.execute("notify pgrst, 'reload schema'")
    return count


def run_sql_file(conn: psycopg.Connection, path: Path) -> None:
    """Ejecuta un archivo SQL completo en una transacción."""
    print(f"  → {path.relative_to(ROOT_DIR)}")
    with conn.transaction():
        conn.execute(path.read_text(encoding="utf-8"))


def run_tests(db_url: str) -> bool:
    """Ejecuta los tests pgTAP y devuelve True si todos pasan.

    Los archivos de test abren y revierten su propia transacción.
    """
    ok = True
    for path in sorted((SUPABASE_DIR / "tests" / "database").glob("*.test.sql")):
        print(f"  → {path.name}")
        with psycopg.connect(db_url, autocommit=True) as conn:
            conn.add_notice_handler(lambda diag: print(f"    NOTICE {diag.message_primary}"))
            cur = conn.cursor()
            cur.execute(path.read_text(encoding="utf-8"))
            # Recorre todos los result sets: cada select de pgTAP devuelve filas "ok N - ..."
            while True:
                if cur.description is not None:
                    for (line, *_rest) in cur.fetchall():
                        print(f"    {line}")
                        if str(line).startswith("not ok"):
                            ok = False
                if not cur.nextset():
                    break
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db-url", help="Cadena de conexión Postgres (por defecto SUPABASE_DB_URL)")
    parser.add_argument("--seed", action="store_true", help="Cargar supabase/seed.sql")
    parser.add_argument("--test", action="store_true", help="Ejecutar los tests pgTAP")
    args = parser.parse_args()

    load_dotenv(ROOT_DIR / ".env")
    db_url = args.db_url or os.getenv("SUPABASE_DB_URL")
    if not db_url:
        print("✖ Define SUPABASE_DB_URL en .env o pasa --db-url", file=sys.stderr)
        return 1

    print("Aplicando migraciones...")
    with psycopg.connect(db_url, autocommit=True) as conn:
        count = apply_migrations(conn)
        print(f"✔ {count} migración(es) aplicada(s)")
        if args.seed:
            print("Cargando seed...")
            run_sql_file(conn, SUPABASE_DIR / "seed.sql")
            print("✔ Seed cargado")

    if args.test:
        print("Ejecutando tests pgTAP...")
        if not run_tests(db_url):
            print("✖ Hay tests fallidos", file=sys.stderr)
            return 1
        print("✔ Todos los tests pasaron")
    return 0


if __name__ == "__main__":
    sys.exit(main())
