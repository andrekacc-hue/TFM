"""Clientes HTTP compartidos.

Cada ``httpx.AsyncClient`` crea por defecto su propio contexto SSL cargando todos los
certificados raíz, lo que cuesta ~1 s en Windows y memoria en cada servicio. Todos los
clientes de los microservicios reutilizan el mismo contexto.
"""

from __future__ import annotations

import ssl
from functools import lru_cache

import httpx


@lru_cache(maxsize=1)
def shared_ssl_context() -> ssl.SSLContext:
    """Contexto SSL verificado (certificados del sistema/certifi), creado una sola vez."""
    return httpx.create_ssl_context()


def async_client(
    *,
    base_url: str = "",
    timeout: float = 30.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> httpx.AsyncClient:
    """``httpx.AsyncClient`` con el contexto SSL compartido."""
    return httpx.AsyncClient(base_url=base_url, timeout=timeout, transport=transport, verify=shared_ssl_context())
