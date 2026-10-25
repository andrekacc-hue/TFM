"""E2E del Admin Portal con un navegador real (Playwright + Chromium).

    pip install playwright && python -m playwright install chromium
    pytest tests/e2e -v                      # PORTAL_URL=http://localhost:3000 por defecto

Crea usuarios temporales en Supabase Auth (admin y viewer de 'operaciones'), recorre el
portal como lo haría una persona y al final borra los usuarios y sus consultas.
"""

from __future__ import annotations

import os
import secrets
import time
from collections.abc import Iterator

import httpx
import pytest

from tests.integration.conftest import SERVICE_KEY, SUPABASE_URL, _admin_headers, _rest_headers

playwright = pytest.importorskip("playwright.sync_api")
expect = playwright.expect

pytestmark = pytest.mark.integration
PORTAL_URL = os.getenv("PORTAL_URL", "http://localhost:3000").rstrip("/")
RUN = secrets.token_hex(3)


@pytest.fixture(scope="module")
def accounts() -> Iterator[dict[str, tuple[str, str, str]]]:
    try:
        httpx.get(f"{PORTAL_URL}/", timeout=3).raise_for_status()
    except httpx.HTTPError:
        pytest.skip(f"Portal no disponible en {PORTAL_URL}")
    if not SERVICE_KEY:
        pytest.skip("Falta SUPABASE_SERVICE_ROLE_KEY")
    created: dict[str, tuple[str, str, str]] = {}
    try:
        for name, role, area in (("admin", "admin", "general"), ("viewer", "viewer", "operaciones")):
            email, password = f"e2e-ui-{RUN}-{name}@test.local", secrets.token_urlsafe(14)
            r = httpx.post(f"{SUPABASE_URL}/auth/v1/admin/users", headers=_admin_headers(), json={
                "email": email, "password": password, "email_confirm": True, "app_metadata": {"role": role, "area": area}})
            r.raise_for_status()
            created[name] = (r.json()["id"], email, password)
        yield created
    finally:
        for user_id, _, _ in created.values():
            httpx.delete(f"{SUPABASE_URL}/rest/v1/queries", headers=_rest_headers(), params={"user_id": f"eq.{user_id}"})
            httpx.delete(f"{SUPABASE_URL}/auth/v1/admin/users/{user_id}", headers=_admin_headers())


@pytest.fixture(scope="module")
def browser():
    with playwright.sync_playwright() as p:
        instance = p.chromium.launch()
        yield instance
        instance.close()


def _wait_path(page, suffix: str, timeout: float = 45) -> None:
    # wait_for_url no siempre detecta las navegaciones internas de la SPA: se sondea la URL
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if page.url.endswith(suffix):
            return
        page.wait_for_timeout(250)
    pytest.fail(f"No se llegó a {suffix} (URL actual: {page.url})")


def _login(browser, account, **context_args):
    context = browser.new_context(locale="es-EC", **context_args)
    page = context.new_page()
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(f"{PORTAL_URL}/login")
    page.get_by_label("Correo electrónico").fill(account[1])
    page.get_by_label("Contraseña").fill(account[2])
    page.get_by_role("button", name="Entrar").click()
    return context, page, errors


def test_login_rejects_bad_credentials(browser, accounts):
    context, page, _ = _login(browser, (None, accounts["viewer"][1], "contraseña-incorrecta"))
    expect(page.get_by_role("alert")).to_contain_text("incorrectos")
    context.close()


def test_admin_journey(browser, accounts):
    context, page, errors = _login(browser, accounts["admin"], viewport={"width": 1440, "height": 900})
    _wait_path(page, "/dashboard")
    expect(page.get_by_text("Tasa de abstención")).to_be_visible(timeout=20_000)
    nav = page.get_by_role("navigation", name="Navegación principal")
    for label in ("Dashboard", "Consulta IA", "Documentos", "Incidentes", "Evaluación", "Configuración"):
        expect(nav.get_by_role("link", name=label)).to_be_visible()

    # Consulta real al asistente: respuesta con fuentes y valoración
    page.goto(f"{PORTAL_URL}/consulta")
    page.get_by_label("Escribe tu consulta").fill("¿Cómo se renueva el certificado del HSM?")
    page.keyboard.press("Enter")
    answer = page.get_by_role("article", name="Respuesta del asistente")
    expect(answer.get_by_role("group", name="Valorar respuesta")).to_be_visible(timeout=90_000)
    expect(answer.get_by_role("region", name="Fuentes consultadas")).to_contain_text("PROC-SEG-021")
    answer.get_by_role("button", name="Respuesta útil").click()
    expect(answer.get_by_text("como útil")).to_be_visible()

    # Documentos con estado e incidentes
    page.goto(f"{PORTAL_URL}/documentos")
    expect(page.get_by_role("table")).to_contain_text("Indexado", timeout=20_000)
    page.goto(f"{PORTAL_URL}/incidentes")
    expect(page.get_by_role("table")).to_contain_text("INC-2026-0001", timeout=20_000)

    # Administración de usuarios visible solo para admin
    page.goto(f"{PORTAL_URL}/configuracion")
    expect(page.get_by_text("Usuarios y permisos")).to_be_visible(timeout=20_000)

    assert not errors, f"Errores en la consola del navegador: {errors}"
    context.close()


def test_viewer_on_mobile_has_limited_access(browser, accounts):
    context, page, errors = _login(browser, accounts["viewer"], viewport={"width": 390, "height": 844})
    _wait_path(page, "/consulta")  # un viewer aterriza en el chat, no en el dashboard
    page.get_by_role("button", name="Abrir menú").click()
    nav = page.get_by_role("navigation", name="Navegación principal")
    expect(nav.get_by_role("link", name="Consulta IA")).to_be_visible()
    expect(nav.get_by_role("link", name="Dashboard")).to_have_count(0)
    expect(nav.get_by_role("link", name="Evaluación")).to_have_count(0)
    page.keyboard.press("Escape")

    page.goto(f"{PORTAL_URL}/dashboard")
    expect(page.get_by_text("Acceso restringido")).to_be_visible()
    page.goto(f"{PORTAL_URL}/documentos")
    expect(page.get_by_text("Subir documento")).to_have_count(0)  # sin permiso de carga
    assert not errors, f"Errores en la consola del navegador: {errors}"
    context.close()
