"""Genera supabase/deploy/tfm_schema.sql: todas las migraciones + seed en un único script.

Sirve para instalar el esquema desde cero pegándolo en el SQL Editor de Supabase. Para un
proyecto que ya tiene migraciones aplicadas, usa ``scripts/apply_migrations.py`` (solo
aplica las pendientes).

Uso:
    python scripts/build_deploy_sql.py
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS = sorted((ROOT / "supabase" / "migrations").glob("*.sql"))
OUTPUT = ROOT / "supabase" / "deploy" / "tfm_schema.sql"


def build() -> str:
    parts = [
        "-- =====================================================================",
        "-- tfm_schema.sql — GENERADO por scripts/build_deploy_sql.py",
        "-- Instalación desde cero: pegar completo en Supabase -> SQL Editor -> Run.",
        "-- No editar a mano.",
        "-- =====================================================================",
        "begin;",
    ]
    for path in MIGRATIONS:
        parts += ["", f"-- >>> {path.name}", path.read_text(encoding="utf-8").strip()]

    parts += [
        "",
        "-- >>> registro de migraciones (compatible con Supabase CLI)",
        "create schema if not exists supabase_migrations;",
        "create table if not exists supabase_migrations.schema_migrations "
        "(version text primary key, statements text[], name text);",
    ]
    for path in MIGRATIONS:
        version, _, name = path.stem.partition("_")
        parts.append(
            f"insert into supabase_migrations.schema_migrations (version, name) values ('{version}', '{name}') on conflict do nothing;"
        )
    parts += ["", "-- >>> seed.sql", (ROOT / "supabase" / "seed.sql").read_text(encoding="utf-8").strip(),
              "", "notify pgrst, 'reload schema';", "commit;", ""]
    return "\n".join(parts)


if __name__ == "__main__":
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(build(), encoding="utf-8", newline="\n")
    print(f"{OUTPUT.relative_to(ROOT)}: {len(MIGRATIONS)} migraciones")
