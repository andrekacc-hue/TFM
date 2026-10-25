"""Prueba de carga del api-gateway con Locust (Fase 8).

Simula el uso del portal: consultas al asistente (preguntas del golden dataset), sondas de
salud y, si se indica un usuario editor/admin, el dashboard de analítica.

    .venv-eval\\Scripts\\pip install locust
    # interfaz web en http://localhost:8089
    .venv-eval\\Scripts\\locust -f scripts\\load_test.py --host http://localhost:8000
    # sin interfaz: 20 usuarios, 2 nuevos/s, 3 minutos, informe HTML
    .venv-eval\\Scripts\\locust -f scripts\\load_test.py --host http://localhost:8000 --headless \\
        -u 20 -r 2 -t 3m --html reports\\load\\locust.html

Variables (.env o entorno):
    INTERNAL_API_KEY        llamadas de sistema al gateway (obligatoria)
    LOAD_TEST_USER_EMAIL    correo de un editor/admin: añade las peticiones de analítica y
                            reparte el rate limit por usuario en lugar de "service"
    LOAD_TEST_QUERY_WEIGHT  peso de las consultas al LLM (por defecto 1; 0 = solo lectura)

Interpretación: las respuestas 429 son el rate limiting del gateway funcionando
(RATE_LIMIT_QUERY, 20/min por identidad) y se cuentan aparte, no como fallos. La latencia
de /api/v1/query está dominada por el LLM (Ollama Cloud): para medir solo la plataforma usa
LOAD_TEST_QUERY_WEIGHT=0.
"""

from __future__ import annotations

import json
import os
import random
from pathlib import Path

from dotenv import load_dotenv
from locust import HttpUser, between, events, task

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

INTERNAL_KEY = os.getenv("INTERNAL_API_KEY", "")
USER_EMAIL = os.getenv("LOAD_TEST_USER_EMAIL", "").strip()
QUERY_WEIGHT = int(os.getenv("LOAD_TEST_QUERY_WEIGHT", "1"))
QUESTIONS = [q["question"] for q in json.loads((ROOT / "tests" / "golden_dataset.json").read_text(encoding="utf-8"))["questions"]]
RATE_LIMITED = {"count": 0}


@events.test_start.add_listener
def check_config(environment, **_kwargs):
    if not INTERNAL_KEY:
        raise SystemExit("Define INTERNAL_API_KEY en .env")
    mode = f"usuario {USER_EMAIL}" if USER_EMAIL else "llamada de sistema (sin analítica)"
    print(f"Prueba de carga contra {environment.host} · {mode} · peso consultas {QUERY_WEIGHT}")


@events.test_stop.add_listener
def report_rate_limit(**_kwargs):
    print(f"Respuestas 429 (rate limiting, no cuentan como fallo): {RATE_LIMITED['count']}")


class PortalUser(HttpUser):
    """Un operador que consulta al asistente y revisa el estado del sistema."""

    wait_time = between(2, 6)

    def on_start(self) -> None:
        self.client.headers["X-Internal-Api-Key"] = INTERNAL_KEY
        if USER_EMAIL:
            self.client.headers["X-User-Email"] = USER_EMAIL

    def _accept_429(self, response) -> None:
        if response.status_code == 429:
            RATE_LIMITED["count"] += 1
            response.success()

    @task(QUERY_WEIGHT)
    def ask_assistant(self) -> None:
        with self.client.post("/api/v1/query", json={"question": random.choice(QUESTIONS), "channel": "api"},
                              name="/api/v1/query", catch_response=True, timeout=120) as response:
            if response.status_code == 429:
                self._accept_429(response)
            elif response.status_code != 200:
                response.failure(f"HTTP {response.status_code}")
            elif "answer" not in response.json():
                response.failure("respuesta sin 'answer'")

    @task(3)
    def health(self) -> None:
        self.client.get("/health", name="/health")

    @task(2)
    def ready(self) -> None:
        self.client.get("/ready", name="/ready")

    @task(4 if USER_EMAIL else 0)
    def dashboard(self) -> None:
        for metric in ("summary", "timeseries", "top-documents"):
            with self.client.get(f"/api/v1/analytics/{metric}",
                                 name="/api/v1/analytics/[metric]", catch_response=True) as response:
                self._accept_429(response)
