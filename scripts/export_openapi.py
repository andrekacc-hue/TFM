"""Exporta las especificaciones OpenAPI de los servicios a docs/api/.

* ``docs/api/openapi.yaml``: API pública (api-gateway).
* ``docs/api/internal/<servicio>.yaml``: APIs internas (rag, ingest, analytics).

Cada servicio tiene su propio paquete ``app``, así que se exporta en un subproceso con el
directorio del servicio como raíz. No necesita el stack levantado.

Uso:
    python scripts/export_openapi.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVICES = {
    "api-gateway": ROOT / "docs" / "api" / "openapi.yaml",
    "rag-service": ROOT / "docs" / "api" / "internal" / "rag-service.yaml",
    "ingest-service": ROOT / "docs" / "api" / "internal" / "ingest-service.yaml",
    "analytics-service": ROOT / "docs" / "api" / "internal" / "analytics-service.yaml",
}

# Configuración ficticia: solo se genera el esquema, no se conecta a nada
EXPORTER = """
import sys, yaml
from app.main import create_app
from app.config import get_settings
settings_cls = type(get_settings.__wrapped__())
settings = settings_cls(_env_file=None, supabase_url="https://example.supabase.co",
                        supabase_service_role_key="placeholder", internal_api_key="placeholder-internal-key",
                        log_format="console")
spec = create_app(settings).openapi()
sys.stdout.write(yaml.safe_dump(spec, allow_unicode=True, sort_keys=False, width=110))
"""


def main() -> int:
    for service, target in SERVICES.items():
        result = subprocess.run(
            [sys.executable, "-c", EXPORTER],
            cwd=ROOT / "services" / service,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        if result.returncode != 0:
            print(f"✖ {service}: {result.stderr.strip().splitlines()[-1]}", file=sys.stderr)
            return 1
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(result.stdout, encoding="utf-8", newline="\n")
        print(f"✔ {target.relative_to(ROOT)} ({result.stdout.count(chr(10))} líneas)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
