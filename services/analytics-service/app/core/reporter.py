"""Exportación del registro de consultas (CSV / JSON) para análisis y la memoria del TFM."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import AsyncIterator
from typing import Any

from app.core.aggregator import DateRange
from shared.supabase_client import SupabaseRepository

EXPORT_COLUMNS = [
    "id",
    "created_at",
    "channel",
    "user_id",
    "question",
    "abstained",
    "abstention_reason",
    "latency_ms",
    "retrieval_ms",
    "rerank_ms",
    "generation_ms",
    "tokens_input",
    "tokens_output",
    "llm_provider",
    "llm_model",
    "sources",
    "feedback_rating",
    "feedback_comment",
    "trace_id",
]


def flatten(row: dict[str, Any]) -> dict[str, Any]:
    """Aplana una fila de ``tfm.queries`` (con ``feedback`` embebido) a columnas planas."""
    timings = row.get("timings") or {}
    feedback = (row.get("feedback") or [{}])[0] if row.get("feedback") else {}
    sources = row.get("sources") or []
    return {
        **{column: row.get(column) for column in EXPORT_COLUMNS if column in row},
        "retrieval_ms": timings.get("retrieval_ms"),
        "rerank_ms": timings.get("rerank_ms"),
        "generation_ms": timings.get("generation_ms"),
        "sources": " | ".join(f"{s.get('title')} ({s.get('section') or 'fragmento ' + str(s.get('chunk_index', 0) + 1)})"
                              for s in sources),
        "feedback_rating": feedback.get("rating"),
        "feedback_comment": feedback.get("comment"),
    }


class QueryReporter:
    """Lee ``tfm.queries`` por páginas y la serializa.

    Args:
        repository: Acceso a PostgREST con service_role.
        page_size: Filas por petición.
        max_rows: Límite duro de filas exportadas.
    """

    def __init__(self, repository: SupabaseRepository, *, page_size: int = 1000, max_rows: int = 10_000) -> None:
        self.repository = repository
        self.page_size = page_size
        self.max_rows = max_rows

    async def rows(self, period: DateRange, channel: str | None = None) -> AsyncIterator[dict[str, Any]]:
        """Filas aplanadas del periodo, de la más reciente a la más antigua."""
        offset = 0
        while offset < self.max_rows:
            params = {
                "select": "id,created_at,channel,user_id,question,abstained,abstention_reason,latency_ms,"
                "timings,tokens_input,tokens_output,llm_provider,llm_model,sources,trace_id,feedback(rating,comment)",
                "and": f"(created_at.gte.{period.start.isoformat()},created_at.lt.{period.end.isoformat()})",
                "order": "created_at.desc",
                "limit": str(min(self.page_size, self.max_rows - offset)),
                "offset": str(offset),
            }
            if channel:
                params["channel"] = f"eq.{channel}"
            page = await self.repository.select("queries", params)
            for row in page:
                yield flatten(row)
            if len(page) < self.page_size:
                return
            offset += len(page)

    async def to_csv(self, period: DateRange, channel: str | None = None) -> str:
        """CSV con BOM UTF-8 (Excel lo abre con acentos correctos) y separador ``;``."""
        buffer = io.StringIO()
        buffer.write("﻿")
        writer = csv.DictWriter(buffer, fieldnames=EXPORT_COLUMNS, delimiter=";", extrasaction="ignore")
        writer.writeheader()
        async for row in self.rows(period, channel):
            writer.writerow(row)
        return buffer.getvalue()

    async def to_json(self, period: DateRange, channel: str | None = None) -> str:
        rows = [row async for row in self.rows(period, channel)]
        return json.dumps(
            {"from": period.start.isoformat(), "to": period.end.isoformat(), "count": len(rows), "rows": rows},
            ensure_ascii=False,
            default=str,
        )
