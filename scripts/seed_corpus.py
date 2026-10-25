"""Carga los documentos de samples/corpus a través de la API del ingest-service.

Sube cada archivo de ``manifest.json`` (``POST /v1/ingest``) y espera a que el worker lo
indexe, mostrando el estado final. Los duplicados (mismo contenido en la misma área) se
reportan y se omiten.

Uso:
    python scripts/seed_corpus.py                       # ingest-service en http://127.0.0.1:8002
    python scripts/seed_corpus.py --api http://ingest-service:8002 --timeout 300
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "samples" / "corpus"


def internal_key() -> str:
    key = os.getenv("INTERNAL_API_KEY")
    if not key:
        for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
            if line.startswith("INTERNAL_API_KEY="):
                key = line.split("=", 1)[1].strip()
    if not key:
        sys.exit("Define INTERNAL_API_KEY (entorno o .env)")
    return key


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default="http://127.0.0.1:8002", help="URL del ingest-service")
    parser.add_argument("--timeout", type=int, default=300, help="Segundos máximos de espera por documento")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

    manifest = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
    headers = {"X-Internal-Api-Key": internal_key()}
    pending: dict[str, str] = {}

    with httpx.Client(base_url=args.api, headers=headers, timeout=60) as client:
        for item in manifest:
            path = CORPUS / item["file"]
            mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            response = client.post(
                "/v1/ingest",
                files={"file": (path.name, path.read_bytes(), mime)},
                data={"title": item["title"], "source_type": item["source_type"], "area": item["area"]},
            )
            if response.status_code == 409:
                print(f"  · {item['title']}: ya existe ({response.json()['error']['details']['document_id']})")
                continue
            response.raise_for_status()
            document_id = response.json()["document_id"]
            pending[document_id] = item["title"]
            print(f"  ↑ {item['title']}  → {document_id} (encolado)")

        deadline = time.monotonic() + args.timeout
        failures = 0
        while pending and time.monotonic() < deadline:
            for document_id in list(pending):
                status = client.get(f"/v1/ingest/{document_id}").json()
                if status["status"] in ("indexed", "failed"):
                    title = pending.pop(document_id)
                    info = status.get("ingestion") or {}
                    if status["status"] == "indexed":
                        print(f"  ✔ {title}: {status['chunk_count']} chunks · {info.get('format')} · "
                              f"{info.get('chars')} caracteres · {info.get('duration_ms')} ms")
                    else:
                        failures += 1
                        print(f"  ✖ {title}: {status['error_message']}")
            time.sleep(1)

    for document_id, title in pending.items():
        failures += 1
        print(f"  ⏱ {title}: sin terminar tras {args.timeout} s ({document_id})")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
