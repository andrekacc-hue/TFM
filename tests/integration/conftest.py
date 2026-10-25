"""Fixtures de integración: stack levantado + usuarios reales temporales en Supabase Auth.

Requiere el stack en marcha (``docker compose up -d``) y el ``.env`` del proyecto. Si el
gateway no responde, los tests se omiten.

Cada ejecución crea usuarios ``e2e-<run>-<rol>@test.local`` con rol y área en
``app_metadata`` (el trigger crea su perfil), inicia sesión con contraseña para obtener JWT
reales y, al terminar, borra usuarios, consultas (por ``trace_id``) y documentos de prueba.
"""

from __future__ import annotations

import os
import secrets
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://127.0.0.1:8000")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")
RUN_ID = uuid.uuid4().hex[:8]
TRACE_PREFIX = f"e2e-{RUN_ID}"


@dataclass
class TestUser:
    id: str
    email: str
    role: str
    area: str
    token: str

    def headers(self, trace: str = "req") -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "X-Trace-Id": f"{TRACE_PREFIX}-{trace}"}


def _admin_headers() -> dict[str, str]:
    headers = {"apikey": SERVICE_KEY}
    if SERVICE_KEY.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {SERVICE_KEY}"
    return headers


def _rest_headers() -> dict[str, str]:
    return {**_admin_headers(), "Accept-Profile": "tfm", "Content-Profile": "tfm"}


@pytest.fixture(scope="session")
def gateway() -> Iterator[httpx.Client]:
    try:
        httpx.get(f"{GATEWAY_URL}/health", timeout=3).raise_for_status()
    except httpx.HTTPError:
        pytest.skip(f"Gateway no disponible en {GATEWAY_URL}: levanta el stack con docker compose up -d")
    with httpx.Client(base_url=GATEWAY_URL, timeout=180) as client:
        yield client


@pytest.fixture(scope="session")
def users(gateway: httpx.Client) -> Iterator[dict[str, TestUser]]:
    if not (SUPABASE_URL and SERVICE_KEY and ANON_KEY):
        pytest.skip("Faltan SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY / SUPABASE_ANON_KEY en .env")

    specs = {
        "viewer_ops": ("viewer", "operaciones"),
        "viewer_cred": ("viewer", "creditos"),
        "editor_ops": ("editor", "operaciones"),
        "admin": ("admin", "general"),
    }
    created: dict[str, TestUser] = {}
    with httpx.Client(base_url=SUPABASE_URL, timeout=30) as supabase:
        try:
            for name, (role, area) in specs.items():
                email = f"e2e-{RUN_ID}-{name.replace('_', '-')}@test.local"
                password = secrets.token_urlsafe(18)
                response = supabase.post(
                    "/auth/v1/admin/users",
                    headers=_admin_headers(),
                    json={"email": email, "password": password, "email_confirm": True,
                          "app_metadata": {"role": role, "area": area}},
                )
                response.raise_for_status()
                user_id = response.json()["id"]
                login = supabase.post(
                    "/auth/v1/token", params={"grant_type": "password"},
                    headers={"apikey": ANON_KEY}, json={"email": email, "password": password},
                )
                login.raise_for_status()
                created[name] = TestUser(user_id, email, role, area, login.json()["access_token"])
            yield created
        finally:
            # Limpieza: consultas de la ejecución (y su feedback en cascada), documentos y usuarios
            supabase.delete("/rest/v1/queries", headers=_rest_headers(), params={"trace_id": f"like.{TRACE_PREFIX}-*"})
            docs = supabase.get("/rest/v1/documents", headers=_rest_headers(),
                                params={"select": "id,storage_path", "title": f"like.E2E {RUN_ID}*"}).json()
            for doc in docs:
                supabase.delete("/rest/v1/documents", headers=_rest_headers(), params={"id": f"eq.{doc['id']}"})
                supabase.request("DELETE", "/storage/v1/object/documents", headers=_admin_headers(),
                                 json={"prefixes": [doc["storage_path"]]})
            for user in created.values():
                supabase.delete(f"/auth/v1/admin/users/{user.id}", headers=_admin_headers())


@pytest.fixture(scope="session")
def run_id() -> str:
    return RUN_ID


@pytest.fixture(scope="session")
def rest() -> Iterator[httpx.Client]:
    """Cliente de PostgREST con service_role para verificar lo que quedó en la base de datos."""
    with httpx.Client(base_url=f"{SUPABASE_URL}/rest/v1", headers=_rest_headers(), timeout=30) as client:
        yield client
