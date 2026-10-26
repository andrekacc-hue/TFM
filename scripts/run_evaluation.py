"""Evaluación del asistente con RAGAs sobre el golden dataset (Fase 8).

    golden_dataset.json ─► tfm.golden_dataset (upsert)
                       ─► gateway POST /api/v1/query (include_contexts) × repeticiones
                       ─► clasificación de abstenciones + recuperación (hit@k, MRR)
                       ─► RAGAs: faithfulness, answer_relevancy, context_precision, context_recall
                       ─► reports/evaluation/<fecha>/{results.json, report.html, report.pdf}
                       ─► tfm.evaluation_runs (lo muestra el portal en /evaluacion)

Métricas RAGAs (juez = LLM vía API compatible con OpenAI; por defecto el Ollama local):
  - faithfulness / answer_relevancy: solo preguntas con respuesta en el corpus que el
    asistente respondió (una abstención no tiene afirmaciones que verificar).
  - context_precision / context_recall: todas las preguntas con respuesta en el corpus,
    también las que el modelo se abstuvo (miden la recuperación, no la generación).

Abstención (lo que RAGAs no mide):
  - falsa abstención LLM: se abstuvo aunque el contexto contenía la respuesta (documento
    esperado presente y, con RAGAs, context_recall >= 0,5).
  - falsa abstención por recuperación: el documento esperado no llegó al contexto, o llegó
    sin el fragmento con la respuesta (context_recall < 0,5).
  - abstención correcta / respuesta indebida en preguntas fuera de alcance.
  Con --repeat N cada pregunta se hace N veces para estimar la tasa (el LLM no es determinista).

Requiere el entorno aislado de evaluación (RAGAs fija versiones de LangChain incompatibles
con los microservicios):
    py -3.12 -m venv .venv-eval
    .venv-eval\\Scripts\\pip install -r scripts\\requirements-eval.txt

Uso:
    .venv-eval\\Scripts\\python scripts\\run_evaluation.py                  # 30 preguntas, RAGAs, sube resultados
    .venv-eval\\Scripts\\python scripts\\run_evaluation.py --repeat 3 --pdf
    .venv-eval\\Scripts\\python scripts\\run_evaluation.py --ids GD-01,GD-25 --no-ragas --no-upload
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from evaluation_report import render_html, render_pdf  # noqa: E402

GOLDEN_PATH = ROOT / "tests" / "golden_dataset.json"
REPORTS_DIR = ROOT / "reports" / "evaluation"
RAGAS_METRICS = ("faithfulness", "answer_relevancy", "context_precision", "context_recall")

# Resultado de cada intento
ANSWERED = "respondida"
FALSE_ABSTENTION_LLM = "falsa_abstencion_llm"
FALSE_ABSTENTION_RETRIEVAL = "falsa_abstencion_recuperacion"
CORRECT_ABSTENTION = "abstencion_correcta"
UNDUE_ANSWER = "respuesta_indebida"
ERROR = "error"


# ---------------------------------------------------------------------------
# Modelo de datos
# ---------------------------------------------------------------------------
@dataclass
class Attempt:
    """Una ejecución de una pregunta contra el asistente."""

    outcome: str
    answer: str = ""
    abstention_reason: str | None = None
    contexts: list[dict[str, str]] = field(default_factory=list)
    expected_rank: int | None = None  # posición (1..k) del documento esperado en el contexto
    latency_ms: float | None = None
    generation_ms: float | None = None
    llm_model: str | None = None
    error: str | None = None


@dataclass
class QuestionResult:
    id: str
    question: str
    expected_answer: str
    expected_behavior: str
    expected_document: str | None
    difficulty: str | None
    tags: list[str]
    attempts: list[Attempt] = field(default_factory=list)
    scores: dict[str, float | None] = field(default_factory=dict)
    score_errors: dict[str, str] = field(default_factory=dict)

    @property
    def scored_attempt(self) -> Attempt | None:
        """Intento que se puntúa con RAGAs: el primero respondido, o el primero sin error."""
        valid = [a for a in self.attempts if a.outcome != ERROR]
        answered = [a for a in valid if a.outcome == ANSWERED]
        return (answered or valid or [None])[0]


# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------
def env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name, default)
    return value.strip() if isinstance(value, str) else value


def load_golden(ids: set[str] | None) -> list[dict[str, Any]]:
    questions = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))["questions"]
    if ids:
        questions = [q for q in questions if q["id"] in ids]
    return questions


# ---------------------------------------------------------------------------
# Supabase (REST, service_role)
# ---------------------------------------------------------------------------
class Supabase:
    def __init__(self, url: str, key: str) -> None:
        self.client = httpx.Client(
            base_url=f"{url.rstrip('/')}/rest/v1",
            headers={"apikey": key, "Authorization": f"Bearer {key}",
                     "Accept-Profile": "tfm", "Content-Profile": "tfm"},
            timeout=30,
        )

    def sync_golden(self, questions: list[dict[str, Any]]) -> int:
        """Upsert por ``code``: el JSON del repo es la fuente de verdad."""
        docs = self.client.get("/documents", params={"select": "id,title", "status": "eq.indexed"})
        docs.raise_for_status()
        doc_ids = {d["title"]: d["id"] for d in docs.json()}
        missing = {q["expected_document"] for q in questions if q["expected_document"]} - doc_ids.keys()
        if missing:
            print(f"  ! Documentos esperados no indexados: {', '.join(sorted(missing))}")
        rows = [{
            "code": q["id"], "question": q["question"], "expected_answer": q["expected_answer"],
            "expected_document_id": doc_ids.get(q["expected_document"] or ""),
            "expected_behavior": q["expected_behavior"], "difficulty": q["difficulty"], "tags": q["tags"],
        } for q in questions]
        response = self.client.post("/golden_dataset", params={"on_conflict": "code"}, json=rows,
                                    headers={"Prefer": "resolution=merge-duplicates,return=minimal"})
        response.raise_for_status()
        return len(rows)

    def previous_runs(self, limit: int = 5) -> list[dict[str, Any]]:
        response = self.client.get("/evaluation_runs", params={
            "select": "id,created_at,label,llm_model,judge_model,questions,metrics",
            "order": "created_at.desc", "limit": str(limit)})
        response.raise_for_status()
        return response.json()

    def save_run(self, run: dict[str, Any]) -> str:
        response = self.client.post("/evaluation_runs", json=run, headers={"Prefer": "return=representation"})
        response.raise_for_status()
        return response.json()[0]["id"]


# ---------------------------------------------------------------------------
# Consultas al asistente
# ---------------------------------------------------------------------------
async def ask(client: httpx.AsyncClient, question: dict[str, Any]) -> Attempt:
    """Pregunta vía gateway como llamada de sistema; respeta el rate limit (429)."""
    for _ in range(5):
        try:
            response = await client.post("/api/v1/query", json={
                "question": question["question"], "channel": "api", "include_contexts": True})
        except httpx.HTTPError as exc:
            return Attempt(outcome=ERROR, error=f"{type(exc).__name__}: {exc}")
        if response.status_code == 429:
            wait = response.json().get("error", {}).get("details", {}).get("retry_after", 10)
            print(f"    · rate limit, esperando {wait}s")
            await asyncio.sleep(float(wait) + 1)
            continue
        if response.status_code >= 400:
            return Attempt(outcome=ERROR, error=f"HTTP {response.status_code}: {response.text[:200]}")
        return classify(question, response.json())
    return Attempt(outcome=ERROR, error="rate limit persistente")


def classify(question: dict[str, Any], body: dict[str, Any]) -> Attempt:
    contexts = [{"title": c["title"], "content": c["content"]} for c in body.get("contexts") or []]
    titles = [c["title"] for c in contexts]
    expected = question["expected_document"]
    rank = titles.index(expected) + 1 if expected in titles else None
    abstained = bool(body.get("abstained"))

    if question["expected_behavior"] == "abstain":
        outcome = CORRECT_ABSTENTION if abstained else UNDUE_ANSWER
    elif not abstained:
        outcome = ANSWERED
    else:
        outcome = FALSE_ABSTENTION_LLM if rank else FALSE_ABSTENTION_RETRIEVAL

    timings = body.get("timings") or {}
    return Attempt(
        outcome=outcome, answer=body.get("answer", ""), abstention_reason=body.get("abstention_reason"),
        contexts=contexts, expected_rank=rank, latency_ms=timings.get("total_ms"),
        generation_ms=timings.get("generation_ms"), llm_model=body.get("llm_model"),
    )


async def run_queries(results: list[QuestionResult], args: argparse.Namespace, key: str) -> None:
    async with httpx.AsyncClient(base_url=args.gateway, timeout=180,
                                 headers={"X-Internal-Api-Key": key}) as client:
        ready = await client.get("/ready")
        if ready.status_code != 200:
            sys.exit(f"El gateway no está listo ({ready.status_code}): {ready.text[:200]}")
        for round_ in range(1, args.repeat + 1):
            print(f"\n  Ronda {round_}/{args.repeat}")
            for result in results:
                attempt = await ask(client, asdict_question(result))
                result.attempts.append(attempt)
                latency = f"{attempt.latency_ms / 1000:.1f}s" if attempt.latency_ms else "-"
                print(f"    {result.id}  {attempt.outcome:<30} {latency:>6}  {attempt.error or ''}")


def asdict_question(result: QuestionResult) -> dict[str, Any]:
    return {"question": result.question, "expected_behavior": result.expected_behavior,
            "expected_document": result.expected_document}


# ---------------------------------------------------------------------------
# RAGAs
# ---------------------------------------------------------------------------
def build_ragas(args: argparse.Namespace):
    """Métricas RAGAs con un juez compatible con OpenAI (Ollama por defecto)."""
    import warnings

    warnings.filterwarnings("ignore", category=DeprecationWarning)
    from openai import AsyncOpenAI
    from ragas.embeddings import HuggingFaceEmbeddings
    from ragas.llms import llm_factory
    from ragas.metrics.collections import AnswerRelevancy, ContextPrecision, ContextRecall, Faithfulness

    client = AsyncOpenAI(base_url=args.judge_base_url, api_key=env(args.judge_api_key_env) or "ollama")
    llm = llm_factory(args.judge_model, provider="openai", client=client, temperature=0)
    embeddings = HuggingFaceEmbeddings(model=args.embedding_model)
    return {
        "faithfulness": Faithfulness(llm=llm),
        "answer_relevancy": AnswerRelevancy(llm=llm, embeddings=embeddings),
        "context_precision": ContextPrecision(llm=llm),
        "context_recall": ContextRecall(llm=llm),
    }


async def score_ragas(results: list[QuestionResult], args: argparse.Namespace) -> None:
    metrics = build_ragas(args)
    semaphore = asyncio.Semaphore(args.judge_concurrency)

    async def score(result: QuestionResult, name: str) -> None:
        attempt = result.scored_attempt
        if attempt is None or result.expected_behavior != "answer":
            return
        contexts = [c["content"] for c in attempt.contexts]
        if name in ("faithfulness", "answer_relevancy") and attempt.outcome != ANSWERED:
            return
        if name in ("context_precision", "context_recall") and not contexts:
            result.scores[name] = 0.0  # nada recuperado: precisión y recall nulos
            return
        kwargs = {
            "faithfulness": {"user_input": result.question, "response": attempt.answer, "retrieved_contexts": contexts},
            "answer_relevancy": {"user_input": result.question, "response": attempt.answer},
            "context_precision": {"user_input": result.question, "reference": result.expected_answer,
                                  "retrieved_contexts": contexts},
            "context_recall": {"user_input": result.question, "reference": result.expected_answer,
                               "retrieved_contexts": contexts},
        }[name]
        async with semaphore:
            for attempt_no in range(3):
                try:
                    value = (await metrics[name].ascore(**kwargs)).value
                    result.scores[name] = None if value is None else round(float(value), 4)
                    result.score_errors.pop(name, None)
                    return
                except Exception as exc:  # noqa: BLE001 - el juez puede devolver JSON inválido
                    result.score_errors[name] = f"{type(exc).__name__}: {str(exc)[:160]}"
                    await asyncio.sleep(2 * (attempt_no + 1))

    tasks = [score(r, name) for r in results for name in RAGAS_METRICS]
    done = 0
    for coro in asyncio.as_completed(tasks):
        await coro
        done += 1
        if done % 10 == 0 or done == len(tasks):
            print(f"    RAGAs {done}/{len(tasks)}")


def refine_abstentions(results: list[QuestionResult], min_recall: float = 0.5) -> int:
    """Que el documento esperado esté en el contexto no basta: puede haber llegado solo el
    fragmento del síntoma y no el de la acción. Si context_recall indica que el contexto no
    cubría la respuesta, la abstención fue correcta para el LLM y el fallo es de recuperación."""
    moved = 0
    for result in results:
        recall = result.scores.get("context_recall")
        if recall is None or recall >= min_recall:
            continue
        for attempt in result.attempts:
            if attempt.outcome == FALSE_ABSTENTION_LLM:
                attempt.outcome = FALSE_ABSTENTION_RETRIEVAL
                moved += 1
    return moved


# ---------------------------------------------------------------------------
# Agregados
# ---------------------------------------------------------------------------
def mean(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 4) if values else None


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    k = (len(ordered) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo), 1)


def rate(part: int, total: int) -> float | None:
    return round(part / total, 4) if total else None


def aggregate(results: list[QuestionResult]) -> dict[str, Any]:
    answerable = [r for r in results if r.expected_behavior == "answer"]
    out_of_scope = [r for r in results if r.expected_behavior == "abstain"]
    ans_attempts = [a for r in answerable for a in r.attempts if a.outcome != ERROR]
    oos_attempts = [a for r in out_of_scope for a in r.attempts if a.outcome != ERROR]
    all_attempts = [a for r in results for a in r.attempts]
    outcomes = Counter(a.outcome for a in all_attempts)

    # Recuperación: sobre el primer intento válido de cada pregunta con respuesta
    first = [r.scored_attempt for r in answerable if r.scored_attempt]
    ranks = [a.expected_rank for a in first]

    unstable = [r.id for r in results if len({a.outcome for a in r.attempts if a.outcome != ERROR}) > 1]
    latencies = [a.latency_ms for a in all_attempts if a.latency_ms is not None]
    generation = [a.generation_ms for a in all_attempts if a.generation_ms]

    ragas = {name: mean([r.scores[name] for r in results if r.scores.get(name) is not None])
             for name in RAGAS_METRICS}
    ragas_n = {name: sum(1 for r in results if r.scores.get(name) is not None) for name in RAGAS_METRICS}

    return {
        "ragas": ragas,
        "ragas_n": ragas_n,
        "answer_rate": rate(outcomes[ANSWERED], len(ans_attempts)),
        "false_abstention_rate": rate(outcomes[FALSE_ABSTENTION_LLM] + outcomes[FALSE_ABSTENTION_RETRIEVAL],
                                      len(ans_attempts)),
        "false_abstention_llm_rate": rate(outcomes[FALSE_ABSTENTION_LLM], len(ans_attempts)),
        "false_abstention_retrieval_rate": rate(outcomes[FALSE_ABSTENTION_RETRIEVAL], len(ans_attempts)),
        "correct_abstention_rate": rate(outcomes[CORRECT_ABSTENTION], len(oos_attempts)),
        "hit_rate": rate(sum(1 for k in ranks if k), len(ranks)),
        "mrr": round(statistics.fmean([1 / k if k else 0 for k in ranks]), 4) if ranks else None,
        "latency_ms": {"p50": percentile(latencies, 0.5), "p95": percentile(latencies, 0.95),
                       "mean": round(statistics.fmean(latencies), 1) if latencies else None},
        "generation_ms_p50": percentile(generation, 0.5),
        "outcomes": dict(outcomes),
        "attempts": len(all_attempts),
        "errors": outcomes[ERROR],
        "unstable_questions": unstable,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--gateway", default=env("EVAL_GATEWAY_URL", "http://localhost:8000"))
    parser.add_argument("--ids", help="Subconjunto de preguntas, p. ej. GD-01,GD-25")
    parser.add_argument("--repeat", type=int, default=1, help="Repeticiones por pregunta (estabilidad de la abstención)")
    parser.add_argument("--label", help="Etiqueta de la ejecución (p. ej. 'baseline gemma4')")
    parser.add_argument("--no-ragas", action="store_true", help="Solo métricas de abstención, recuperación y latencia")
    parser.add_argument("--no-upload", action="store_true", help="No sincroniza el golden dataset ni guarda la ejecución")
    parser.add_argument("--pdf", action="store_true", help="Genera también report.pdf (requiere Playwright)")
    parser.add_argument("--judge-model", default=env("EVAL_JUDGE_MODEL") or env("OLLAMA_MODEL", "gemma4:31b-cloud"))
    parser.add_argument("--judge-base-url", default=env("EVAL_JUDGE_BASE_URL", "http://localhost:11434/v1"),
                        help="API compatible con OpenAI del juez")
    parser.add_argument("--judge-api-key-env", default="EVAL_JUDGE_API_KEY",
                        help="Variable de entorno con la clave del juez (Ollama no la necesita)")
    parser.add_argument("--judge-concurrency", type=int, default=2)
    parser.add_argument("--embedding-model", default=env("EMBEDDING_MODEL",
                                                         "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"))
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("--repeat debe ser >= 1")
    return args


async def main() -> int:
    args = parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    key = env("INTERNAL_API_KEY")
    if not key:
        sys.exit("Define INTERNAL_API_KEY en .env")

    questions = load_golden(set(args.ids.split(",")) if args.ids else None)
    results = [QuestionResult(id=q["id"], question=q["question"], expected_answer=q["expected_answer"],
                              expected_behavior=q["expected_behavior"], expected_document=q["expected_document"],
                              difficulty=q.get("difficulty"), tags=q.get("tags", [])) for q in questions]
    print(f"Golden dataset: {len(results)} preguntas "
          f"({sum(r.expected_behavior == 'abstain' for r in results)} fuera de alcance) × {args.repeat}")

    supabase = None
    if not args.no_upload:
        supabase = Supabase(env("SUPABASE_URL") or "", env("SUPABASE_SERVICE_ROLE_KEY") or "")
        print(f"  tfm.golden_dataset sincronizado: {supabase.sync_golden(questions)} filas")

    started = time.perf_counter()
    await run_queries(results, args, key)

    if not args.no_ragas:
        print(f"\n  RAGAs con juez {args.judge_model} ({args.judge_base_url})")
        await score_ragas(results, args)
        if moved := refine_abstentions(results):
            print(f"    {moved} abstención(es) reclasificadas como fallo de recuperación (context_recall bajo)")

    metrics = aggregate(results)
    duration = round(time.perf_counter() - started, 1)
    llm_models = Counter(a.llm_model for r in results for a in r.attempts if a.llm_model)
    run = {
        "label": args.label,
        "llm_provider": env("LLM_PROVIDER"),
        "llm_model": llm_models.most_common(1)[0][0] if llm_models else None,
        "judge_model": None if args.no_ragas else args.judge_model,
        "questions": len(results),
        "metrics": metrics,
        "results": [asdict(r) for r in results],
        "config": {"repeat": args.repeat, "embedding_model": args.embedding_model, "ragas": not args.no_ragas,
                   "gateway": args.gateway},
        "duration_s": duration,
    }

    previous = supabase.previous_runs() if supabase else []
    if supabase:
        run["id"] = supabase.save_run(compact(run))
        print(f"\n  Ejecución guardada en tfm.evaluation_runs ({run['id']})")
    run["created_at"] = datetime.now(timezone.utc).isoformat()

    out_dir = REPORTS_DIR / datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path = out_dir / "report.html"
    html_path.write_text(render_html(run, previous), encoding="utf-8")
    if args.pdf:
        await render_pdf(html_path, out_dir / "report.pdf")

    print_summary(metrics)
    print(f"\n  Informe: {html_path}")
    return 1 if metrics["errors"] else 0


def compact(run: dict[str, Any]) -> dict[str, Any]:
    """Versión para tfm.evaluation_runs: de los contextos solo guarda el título (el texto
    completo queda en results.json); así el portal carga las ejecuciones rápido."""
    results = []
    for result in run["results"]:
        attempts = [{**a, "contexts": [c["title"] for c in a["contexts"]]} for a in result["attempts"]]
        results.append({**result, "attempts": attempts})
    return {**run, "results": results}


def print_summary(m: dict[str, Any]) -> None:
    def pct(value: float | None) -> str:
        return "  n/d" if value is None else f"{value * 100:5.1f}%"

    print("\n  ── Resultados ─────────────────────────────────────")
    for name in RAGAS_METRICS:
        value = m["ragas"][name]
        print(f"  {name:<36}{'  n/d' if value is None else f'{value:6.3f}'}  (n={m['ragas_n'][name]})")
    print(f"  {'tasa de respuesta (con evidencia)':<36}{pct(m['answer_rate'])}")
    print(f"  {'falsa abstención total':<36}{pct(m['false_abstention_rate'])}")
    print(f"  {'  · del LLM (contexto correcto)':<36}{pct(m['false_abstention_llm_rate'])}")
    print(f"  {'  · por recuperación':<36}{pct(m['false_abstention_retrieval_rate'])}")
    print(f"  {'abstención correcta (fuera alcance)':<36}{pct(m['correct_abstention_rate'])}")
    print(f"  {'hit rate@k / MRR':<36}{pct(m['hit_rate'])} / {m['mrr']}")
    print(f"  {'latencia p50 / p95':<36}{m['latency_ms']['p50']} / {m['latency_ms']['p95']} ms")
    if m["unstable_questions"]:
        print(f"  {'preguntas inestables':<36}{', '.join(m['unstable_questions'])}")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
