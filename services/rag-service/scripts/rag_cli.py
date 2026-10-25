"""CLI de prueba del rag-service (sin pasar por HTTP).

Uso (desde services/rag-service, con el .venv activo):
    python scripts/rag_cli.py health
    python scripts/rag_cli.py seed-demo
    python scripts/rag_cli.py ask "El batch de cierre quedó en RUNNING, ¿qué hago?"
    python scripts/rag_cli.py ask "¿Qué significa el código 91 en ATM?" --area operaciones --json
    python scripts/rag_cli.py clean-demo
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for stream in (sys.stdout, sys.stderr):
    stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

from app.config import get_settings  # noqa: E402
from app.dependencies import build_container  # noqa: E402
from scripts.demo_corpus import DEMO_DOCUMENTS  # noqa: E402
from shared.logging import bind_trace_id, configure_logging, new_trace_id  # noqa: E402
from shared.schemas import QueryRequest  # noqa: E402

DEMO_IDS = ",".join(doc["id"] for doc in DEMO_DOCUMENTS)


async def cmd_health(container) -> int:
    supabase_ok, llm_ok = await asyncio.gather(container.repository.health(), container.llm.health())
    print(f"Supabase ({container.settings.supabase_schema}): {'OK' if supabase_ok else 'ERROR'}")
    print(f"LLM {container.llm.provider}:{container.llm.model}: {'OK' if llm_ok else 'ERROR'}")
    return 0 if supabase_ok and llm_ok else 1


async def cmd_seed_demo(container) -> int:
    repo, embedder = container.repository, container.embedder
    print(f"Cargando modelo de embeddings ({embedder.model_name})...")
    for doc in DEMO_DOCUMENTS:
        await repo.insert(
            "documents",
            {
                "id": doc["id"],
                "title": doc["title"],
                "source_type": doc["source_type"],
                "area": doc["area"],
                "storage_path": f"{doc['area']}/{doc['id']}/demo.md",
                "status": "processing",
                "metadata": {"demo": True},
            },
            upsert_on="id",
            returning=False,
        )
        await repo.delete("chunks", {"document_id": f"eq.{doc['id']}"})
        vectors = await embedder.embed_documents(doc["paragraphs"])
        await repo.insert(
            "chunks",
            [
                {
                    "document_id": doc["id"],
                    "chunk_index": i,
                    "content": text,
                    "embedding": vector,
                    "token_count": len(text.split()),
                    "metadata": {"demo": True},
                }
                for i, (text, vector) in enumerate(zip(doc["paragraphs"], vectors, strict=True))
            ],
            returning=False,
        )
        await repo.update(
            "documents", {"id": f"eq.{doc['id']}"}, {"status": "indexed", "chunk_count": len(doc["paragraphs"])}
        )
        print(f"  ✔ {doc['title']}  ({len(doc['paragraphs'])} fragmentos, área {doc['area']})")
    return 0


async def cmd_clean_demo(container) -> int:
    await container.repository.delete("documents", {"id": f"in.({DEMO_IDS})"})
    print("Documentos demo eliminados (los chunks se borran en cascada).")
    return 0


async def cmd_ask(container, question: str, area: str | None, top_k: int | None, as_json: bool) -> int:
    trace_id = new_trace_id()
    bind_trace_id(trace_id)
    response = await container.chain.run(QueryRequest(question=question, channel="api", area=area, top_k=top_k))

    if as_json:
        print(response.model_dump_json(indent=2))
        return 0

    width = 100
    print("=" * width)
    print(f"PREGUNTA: {question}")
    print("=" * width)
    print(response.answer)
    print("-" * width)
    if response.sources:
        print("FUENTES:")
        for s in response.sources:
            score = f"rerank={s.rerank_score:.3f}" if s.rerank_score is not None else ""
            where = s.section or f"fragmento {s.chunk_index + 1}"
            if s.page:
                where += f", pág. {s.page}"
            print(f"  [{s.index}] {s.title} · {s.source_type} · {where} "
                  f"(similitud={s.similarity:.3f} {score})")
            print(textwrap.indent(textwrap.fill(s.excerpt, width - 8), "      "))
    t = response.timings
    print("-" * width)
    print(f"abstención: {response.abstained}" + (f" ({response.abstention_reason})" if response.abstention_reason else ""))
    print(f"LLM: {response.llm_provider}:{response.llm_model} · tokens {response.usage.tokens_input}/{response.usage.tokens_output}")
    print(f"latencia: total {t.total_ms:.0f} ms = retrieval {t.retrieval_ms:.0f} + rerank {t.rerank_ms:.0f} "
          f"+ LLM {t.generation_ms:.0f}")
    print(f"query_id: {response.query_id} · trace_id: {response.trace_id}")
    if response.warnings:
        print(f"avisos: {', '.join(response.warnings)}")
    return 0


async def main() -> int:
    parser = argparse.ArgumentParser(description="CLI de prueba del rag-service")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("health", help="Comprueba Supabase y el LLM")
    sub.add_parser("seed-demo", help="Carga 3 documentos demo con embeddings reales")
    sub.add_parser("clean-demo", help="Elimina los documentos demo")
    ask = sub.add_parser("ask", help="Hace una consulta RAG")
    ask.add_argument("question")
    ask.add_argument("--area", default=None)
    ask.add_argument("--top-k", type=int, default=None)
    ask.add_argument("--json", action="store_true", help="Salida JSON completa")
    parser.add_argument("--verbose", action="store_true", help="Muestra los logs estructurados")
    args = parser.parse_args()

    settings = get_settings()
    configure_logging("rag-cli", "INFO" if args.verbose else "WARNING", "console")
    container = build_container(settings)
    try:
        if args.command == "health":
            return await cmd_health(container)
        if args.command == "seed-demo":
            return await cmd_seed_demo(container)
        if args.command == "clean-demo":
            return await cmd_clean_demo(container)
        return await cmd_ask(container, args.question, args.area, args.top_k, args.json)
    finally:
        await container.aclose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
