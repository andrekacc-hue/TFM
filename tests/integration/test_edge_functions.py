"""Fase 5 de extremo a extremo: subida directa a Storage → Edge Functions → outbox → RAG.

    portal (JWT de usuario) ──► Storage (bucket documents, RLS por área)
        └─ trigger SQL ──pg_net──► on-document-upload ──► tfm.documents (pending)
    ingest-service outbox poller ──► Redis ──► worker ──► indexed ──► rag-service

Requiere: stack levantado, Edge Functions desplegadas (scripts/configure_edge_functions.py).
"""

from __future__ import annotations

import json
import time
import uuid

import httpx
import pytest

from tests.integration.conftest import ANON_KEY, SUPABASE_URL

pytestmark = pytest.mark.integration

FUNCTIONS_URL = f"{SUPABASE_URL}/functions/v1"


def _wait_for_document(rest: httpx.Client, document_id: str, statuses: set[str], timeout: float = 120) -> dict:
    deadline = time.monotonic() + timeout
    row: dict = {}
    while time.monotonic() < deadline:
        rows = rest.get("/documents", params={"id": f"eq.{document_id}",
                                              "select": "status,title,source_type,uploaded_by,chunk_count,metadata,error_message"}).json()
        if rows:
            row = rows[0]
            if row["status"] in statuses:
                return row
        time.sleep(1)
    pytest.fail(f"El documento {document_id} no llegó a {statuses} en {timeout}s (último: {row})")


def _storage_upload(token: str, path: str, content: bytes, metadata: dict) -> httpx.Response:
    """Subida como la hace supabase-js: multipart con el archivo y user_metadata."""
    return httpx.post(
        f"{SUPABASE_URL}/storage/v1/object/documents/{path}",
        headers={"apikey": ANON_KEY, "Authorization": f"Bearer {token}", "x-upsert": "false"},
        files={"": (path.rsplit("/", 1)[-1], content, "text/markdown")},
        data={"metadata": json.dumps(metadata)},
        timeout=60,
    )


@pytest.fixture(scope="module")
def uploaded(users, rest, run_id):
    """Un editor de 'operaciones' sube un documento directamente a Storage."""
    editor = users["editor_ops"]
    document_id = str(uuid.uuid4())
    code = f"EDGE-{run_id.upper()}"
    content = (
        f"# Procedimiento {code}\n\n## Síntoma\n\nEl monitor de colas muestra la alerta {code} cuando el "
        "servicio de notificaciones SMS acumula más de 500 mensajes sin enviar.\n\n"
        "## Acción\n\nVerificar el enlace con el proveedor de SMS y reiniciar el conector de notificaciones "
        "desde la consola de integración. Si persiste, escalar al proveedor."
    ).encode()
    response = _storage_upload(editor.token, f"operaciones/{document_id}/procedimiento-{run_id}.md", content,
                               {"title": f"E2E {run_id} Procedimiento {code}", "source_type": "procedimiento"})
    assert response.status_code in (200, 201), response.text
    return {"id": document_id, "code": code, "editor": editor}


def test_storage_upload_is_registered_by_edge_function(uploaded, rest):
    row = _wait_for_document(rest, uploaded["id"], {"pending", "processing", "indexed"}, timeout=60)
    assert row["title"].endswith(uploaded["code"])
    assert row["source_type"] == "procedimiento"
    assert row["uploaded_by"] == uploaded["editor"].id
    assert row["metadata"]["origin"] == "storage-trigger"


def test_outbox_indexes_the_document(uploaded, rest):
    row = _wait_for_document(rest, uploaded["id"], {"indexed", "failed"})
    assert row["status"] == "indexed", row["error_message"]
    assert row["chunk_count"] >= 1
    assert row["metadata"]["ingestion"]["format"] == "markdown"


def test_document_is_searchable_through_the_gateway(gateway, users, uploaded, rest):
    _wait_for_document(rest, uploaded["id"], {"indexed"})
    question = f"El monitor de colas muestra la alerta {uploaded['code']}, ¿qué acción debo tomar?"
    # Se comprueba lo que prueba este test (ingesta → búsqueda con RLS) con los fragmentos que
    # recibió el LLM, no con su respuesta: con esta formulación el modelo se abstiene a veces
    # aunque el documento esté en primera posición (3 de 4 en la medición de la Fase 8,
    # docs/evaluation.md). Esa falsa abstención es del LLM y se mide en la evaluación.
    body = gateway.post("/api/v1/query", json={"question": question, "include_contexts": True},
                        headers=users["viewer_ops"].headers("edge-query")).json()
    titles = [c["title"] for c in body["contexts"] or []]
    assert titles and uploaded["code"] in titles[0], (body.get("abstention_reason"), titles)
    if not body["abstained"]:
        assert any(uploaded["code"] in s["title"] for s in body["sources"])


def test_reindex_function_permissions_and_cycle(users, uploaded, rest):
    before = _wait_for_document(rest, uploaded["id"], {"indexed"})["metadata"]["ingestion"]["finished_at"]
    call = lambda user: httpx.post(  # noqa: E731
        f"{FUNCTIONS_URL}/reindex-document",
        headers={"Authorization": f"Bearer {user.token}", "apikey": ANON_KEY},
        json={"document_id": uploaded["id"]},
        timeout=30,
    )
    assert call(users["viewer_ops"]).status_code == 403
    assert call(users["viewer_cred"]).status_code == 403

    response = call(uploaded["editor"])
    assert response.status_code == 202, response.text
    assert response.json() == {"document_id": uploaded["id"], "status": "pending", "via": "outbox"}

    # El outbox lo vuelve a encolar y el worker lo reprocesa: debe haber una indexación NUEVA
    deadline = time.monotonic() + 120
    after = before
    while time.monotonic() < deadline and after == before:
        time.sleep(1)
        row = rest.get("/documents", params={"id": f"eq.{uploaded['id']}", "select": "status,metadata"}).json()[0]
        if row["status"] == "indexed":
            after = row["metadata"]["ingestion"]["finished_at"]
    assert after > before, "el documento no se reindexó"


def test_storage_rls_blocks_upload_to_foreign_area(users, run_id):
    response = _storage_upload(users["editor_ops"].token, f"creditos/{uuid.uuid4()}/x.md", b"# x",
                               {"title": f"E2E {run_id} intruso"})
    assert response.status_code in (400, 403), response.text
