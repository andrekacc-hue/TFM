"""Informe HTML/PDF de una ejecución de scripts/run_evaluation.py.

HTML autocontenido (sin dependencias externas): se abre en el navegador, se adjunta a la
memoria del TFM o se convierte a PDF con Playwright (Chromium headless).
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

METRIC_LABELS = {
    "faithfulness": ("Faithfulness", "Afirmaciones de la respuesta respaldadas por el contexto"),
    "answer_relevancy": ("Answer relevancy", "La respuesta atiende a lo que se preguntó"),
    "context_precision": ("Context precision", "Los fragmentos útiles aparecen primero"),
    "context_recall": ("Context recall", "El contexto cubre la respuesta de referencia"),
}
OUTCOME_LABELS = {
    "respondida": ("Respondida", "good"),
    "abstencion_correcta": ("Abstención correcta", "good"),
    "falsa_abstencion_llm": ("Falsa abstención (LLM)", "serious"),
    "falsa_abstencion_recuperacion": ("Falsa abstención (recuperación)", "warning"),
    "respuesta_indebida": ("Respuesta indebida", "critical"),
    "error": ("Error", "critical"),
}
# Objetivos de calidad del TFM (umbral "aceptable")
TARGETS = {"faithfulness": 0.85, "answer_relevancy": 0.80, "context_precision": 0.75, "context_recall": 0.80}

CSS = """
:root{color-scheme:light;--bg:#fcfcfb;--card:#ffffff;--ink:#0b0b0b;--ink2:#52514e;--muted:#8a8984;--line:#e6e5e0;
--grid:#efeee9;--series:#2a78d6;--good:#0ca30c;--warning:#fab219;--serious:#ec835a;--critical:#d03b3b}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--bg:#1a1a19;--card:#232322;
--ink:#f0efec;--ink2:#c3c2b7;--muted:#8f8e86;--line:#3a3a37;--grid:#2c2c2a;--series:#3987e5}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#1a1a19;--card:#232322;--ink:#f0efec;--ink2:#c3c2b7;--muted:#8f8e86;
--line:#3a3a37;--grid:#2c2c2a;--series:#3987e5}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:14px/1.5 "Segoe UI",system-ui,-apple-system,sans-serif}
main{max-width:1080px;margin:0 auto;padding:32px 16px 64px}
h1{font-size:24px;margin:0 0 4px}h2{font-size:17px;margin:36px 0 12px}
.sub{color:var(--ink2);margin:0}.muted{color:var(--muted)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-top:20px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.tile .v{font-size:26px;font-weight:600;font-variant-numeric:tabular-nums}
.tile .l{font-weight:600;font-size:13px}.tile .d{color:var(--muted);font-size:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--ink2);font-weight:600}td.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.badge{display:inline-flex;align-items:center;gap:5px;font-size:12px;white-space:nowrap}
.dot{width:9px;height:9px;border-radius:50%;flex:none}
.good{background:var(--good)}.warning{background:var(--warning)}.serious{background:var(--serious)}
.critical{background:var(--critical)}
.delta-up{color:var(--good)}.delta-down{color:var(--critical)}
details summary{cursor:pointer;color:var(--ink2)}
.ans{white-space:pre-wrap;color:var(--ink2);font-size:12px;margin:6px 0 0}
svg text{fill:var(--ink2);font-size:12px}
.legend{display:flex;flex-wrap:wrap;gap:14px;margin-top:10px;font-size:12px;color:var(--ink2)}
ul.notes{color:var(--ink2);padding-left:18px}
@media print{body{background:#fff}.card,.tile{break-inside:avoid}details{display:block}}
"""


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def pct(value: float | None, digits: int = 0) -> str:
    return "n/d" if value is None else f"{value * 100:.{digits}f} %"


def num(value: float | None) -> str:
    return "n/d" if value is None else f"{value:.3f}"


def status_of(name: str, value: float | None) -> str:
    if value is None:
        return "warning"
    target = TARGETS[name]
    return "good" if value >= target else "warning" if value >= target - 0.15 else "critical"


def ragas_chart(metrics: dict[str, Any]) -> str:
    """Barras horizontales 0..1 con marca del objetivo; una sola serie, sin leyenda."""
    row, left, width = 40, 150, 520
    height = row * len(METRIC_LABELS) + 30
    parts = [f'<svg viewBox="0 0 {left + width + 70} {height}" width="100%" role="img" '
             f'aria-label="Métricas RAGAs de 0 a 1 con su objetivo">']
    for tick in (0, 0.25, 0.5, 0.75, 1):
        x = left + tick * width
        parts.append(f'<line x1="{x}" y1="0" x2="{x}" y2="{height - 22}" stroke="var(--grid)"/>'
                     f'<text x="{x}" y="{height - 6}" text-anchor="middle">{tick:g}</text>')
    for i, (name, (label, _)) in enumerate(METRIC_LABELS.items()):
        value = metrics["ragas"].get(name)
        y = i * row + 8
        parts.append(f'<text x="{left - 10}" y="{y + 15}" text-anchor="end">{label}</text>')
        if value is not None:
            w = max(value * width, 4)
            parts.append(f'<rect x="{left}" y="{y + 4}" width="{w:.1f}" height="16" rx="4" fill="var(--series)">'
                         f'<title>{label}: {value:.3f} (objetivo {TARGETS[name]:.2f})</title></rect>'
                         f'<text x="{left + max(w, TARGETS[name] * width) + 8}" y="{y + 17}" style="fill:var(--ink)">{value:.2f}</text>')
        tx = left + TARGETS[name] * width
        parts.append(f'<line x1="{tx}" y1="{y}" x2="{tx}" y2="{y + 24}" stroke="var(--ink)" stroke-width="2" '
                     f'stroke-dasharray="3 2"><title>Objetivo {TARGETS[name]:.2f}</title></line>')
    parts.append("</svg>")
    return "".join(parts)


def outcome_bar(outcomes: dict[str, int]) -> str:
    """Barra apilada de resultados por intento (estado = icono de color + etiqueta)."""
    total = sum(outcomes.values()) or 1
    width, x, segs, legend = 1000, 0.0, [], []
    for key, (label, status) in OUTCOME_LABELS.items():
        count = outcomes.get(key, 0)
        if not count:
            continue
        w = count / total * width
        segs.append(f'<rect x="{x + 1:.1f}" y="0" width="{max(w - 2, 1):.1f}" height="22" rx="4" '
                    f'style="fill:var(--{status})"><title>{label}: {count} ({count / total:.0%})</title></rect>')
        legend.append(f'<span class="badge"><span class="dot {status}"></span>{label}: {count}</span>')
        x += w
    return (f'<svg viewBox="0 0 {width} 22" width="100%" preserveAspectRatio="none" role="img" '
            f'aria-label="Distribución de resultados">{"".join(segs)}</svg><div class="legend">{"".join(legend)}</div>')


def comparison_table(run: dict[str, Any], previous: list[dict[str, Any]]) -> str:
    if not previous:
        return '<p class="muted">Primera ejecución registrada: no hay ejecuciones anteriores con las que comparar.</p>'
    rows = [("Esta ejecución", run)] + [(p["created_at"][:16].replace("T", " "), p) for p in previous]
    cols = [(METRIC_LABELS[n][0], lambda m, n=n: (m.get("ragas") or {}).get(n), num) for n in METRIC_LABELS]
    cols += [("Falsa abstención", lambda m: m.get("false_abstention_rate"), pct),
             ("Abst. correcta", lambda m: m.get("correct_abstention_rate"), pct),
             ("Hit rate", lambda m: m.get("hit_rate"), pct),
             ("p50 (s)", lambda m: (m.get("latency_ms") or {}).get("p50"),
              lambda v: "n/d" if v is None else f"{v / 1000:.1f}")]
    head = "".join(f'<th class="n">{esc(c[0])}</th>' for c in cols)
    body = []
    base = run["metrics"]
    for i, (name, item) in enumerate(rows):
        m = item["metrics"]
        cells = []
        for title, getter, fmt in cols:
            value = getter(m)
            delta = ""
            if i > 0 and value is not None and getter(base) is not None and title != "p50 (s)":
                diff = getter(base) - value
                better = diff < 0 if title == "Falsa abstención" else diff > 0
                if abs(diff) >= 0.005:
                    delta = f' <span class="{"delta-up" if better else "delta-down"}">{"▲" if diff > 0 else "▼"}</span>'
            cells.append(f'<td class="n">{fmt(value)}{delta}</td>')
        label = esc(item.get("label") or "")
        model = esc(item.get("llm_model") or "")
        body.append(f'<tr><td><b>{esc(name)}</b><br><span class="muted">{model} {label}</span></td>{"".join(cells)}</tr>')
    return (f'<table><thead><tr><th>Ejecución</th>{head}</tr></thead><tbody>{"".join(body)}</tbody></table>'
            '<p class="muted">▲/▼: la ejecución actual mejora/empeora respecto a esa fila.</p>')


def question_rows(results: list[dict[str, Any]]) -> str:
    rows = []
    for r in results:
        attempts = r["attempts"]
        badges = "".join(
            f'<span class="badge" title="{esc(OUTCOME_LABELS.get(a["outcome"], (a["outcome"],))[0])}">'
            f'<span class="dot {OUTCOME_LABELS.get(a["outcome"], ("", "critical"))[1]}"></span></span>'
            for a in attempts)
        first = next((a for a in attempts if a["outcome"] == "respondida"), attempts[0] if attempts else None)
        main_outcome = OUTCOME_LABELS.get(first["outcome"], (first["outcome"],))[0] if first else "—"
        scores = "".join(f'<td class="n">{num(r["scores"].get(n))}</td>' for n in METRIC_LABELS)
        rank = first.get("expected_rank") if first else None
        detail = ""
        if first:
            detail = (f'<details><summary>{esc(main_outcome)}</summary>'
                      f'<p class="ans">{esc(first["answer"])}</p>'
                      f'<p class="ans"><b>Referencia:</b> {esc(r["expected_answer"])}</p>'
                      + (f'<p class="ans"><b>Errores del juez:</b> {esc(r["score_errors"])}</p>' if r["score_errors"] else "")
                      + '</details>')
        rows.append(
            f'<tr><td><b>{esc(r["id"])}</b></td><td>{esc(r["question"])}{detail}</td>'
            f'<td>{badges}</td><td class="n">{rank or "—"}</td>{scores}</tr>')
    head = "".join(f'<th class="n">{METRIC_LABELS[n][0]}</th>' for n in METRIC_LABELS)
    return (f'<table><thead><tr><th>Id</th><th>Pregunta</th><th>Intentos</th><th class="n">Rank doc.</th>{head}'
            f'</tr></thead><tbody>{"".join(rows)}</tbody></table>')


def render_html(run: dict[str, Any], previous: list[dict[str, Any]]) -> str:
    m = run["metrics"]
    tiles = []
    for name, (label, desc) in METRIC_LABELS.items():
        value = m["ragas"].get(name)
        tiles.append(f'<div class="tile"><span class="badge"><span class="dot {status_of(name, value)}"></span>'
                     f'<span class="l">{label}</span></span><div class="v">{num(value)}</div>'
                     f'<div class="d">{desc} · objetivo ≥ {TARGETS[name]:.2f} · n={m["ragas_n"].get(name, 0)}</div></div>')
    tiles += [
        f'<div class="tile"><span class="l">Falsa abstención</span><div class="v">{pct(m["false_abstention_rate"], 1)}</div>'
        f'<div class="d">LLM {pct(m["false_abstention_llm_rate"], 1)} · recuperación '
        f'{pct(m["false_abstention_retrieval_rate"], 1)}</div></div>',
        f'<div class="tile"><span class="l">Abstención correcta</span><div class="v">{pct(m["correct_abstention_rate"])}</div>'
        f'<div class="d">Preguntas fuera de alcance en las que no inventa</div></div>',
        f'<div class="tile"><span class="l">Recuperación</span><div class="v">{pct(m["hit_rate"])}</div>'
        f'<div class="d">Hit rate@k · MRR {num(m["mrr"])}</div></div>',
        f'<div class="tile"><span class="l">Latencia</span><div class="v">'
        f'{"n/d" if m["latency_ms"]["p50"] is None else f"{m["latency_ms"]["p50"] / 1000:.1f} s"}</div>'
        f'<div class="d">p50 · p95 {"n/d" if m["latency_ms"]["p95"] is None else f"{m["latency_ms"]["p95"] / 1000:.1f} s"}'
        f'</div></div>',
    ]
    config = run.get("config", {})
    unstable = ", ".join(m["unstable_questions"]) or "ninguna"
    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Evaluación RAGAs</title><style>{CSS}</style></head>
<body><main>
<h1>Evaluación del asistente de Soporte TI</h1>
<p class="sub">{esc(run.get("created_at", "")[:16].replace("T", " "))} UTC · {run["questions"]} preguntas ×
{config.get("repeat", 1)} · LLM <b>{esc(run.get("llm_model") or "n/d")}</b> · juez <b>{esc(run.get("judge_model") or "sin RAGAs")}</b>
· {m["attempts"]} consultas en {run.get("duration_s", 0):.0f} s{(" · " + esc(run["label"])) if run.get("label") else ""}</p>
<div class="tiles">{"".join(tiles)}</div>

<h2>Métricas RAGAs</h2>
<div class="card">{ragas_chart(m)}<p class="muted">Media 0–1. La línea discontinua marca el objetivo de calidad.
Faithfulness y answer relevancy se calculan sobre las respuestas emitidas; context precision y recall, sobre todas
las preguntas con respuesta en el corpus (miden la recuperación aunque el modelo se abstenga).</p></div>

<h2>Resultado de cada consulta</h2>
<div class="card">{outcome_bar(m["outcomes"])}
<p class="muted">Preguntas con resultado distinto entre repeticiones: {esc(unstable)}.</p></div>

<h2>Comparativa con ejecuciones anteriores</h2>
<div class="card">{comparison_table(run, previous)}</div>

<h2>Detalle por pregunta</h2>
<div class="card">{question_rows(run["results"])}</div>

<h2>Metodología</h2>
<ul class="notes">
<li>Golden dataset: <code>tests/golden_dataset.json</code> — {sum(r["expected_behavior"] == "answer" for r in run["results"])}
preguntas con respuesta en el corpus y {sum(r["expected_behavior"] == "abstain" for r in run["results"])} fuera de alcance.</li>
<li>Las consultas pasan por el api-gateway como llamada de sistema (sin RLS de área) con <code>include_contexts</code>, que
devuelve los fragmentos completos entregados al LLM, también cuando se abstiene.</li>
<li><b>Falsa abstención del LLM</b>: el modelo se abstuvo aunque el documento esperado estaba en su contexto.
<b>Por recuperación</b>: el documento esperado no llegó al contexto (fallo del retriever/reranker).</li>
<li>Juez RAGAs: {esc(run.get("judge_model") or "n/d")} con temperatura 0; embeddings
{esc(config.get("embedding_model", ""))}. Usar el mismo modelo como generador y juez introduce un sesgo de autoevaluación;
para resultados definitivos conviene un juez distinto (<code>--judge-model</code>, <code>--judge-base-url</code>).</li>
</ul>
</main></body></html>"""


async def render_pdf(html_path: Path, pdf_path: Path) -> None:
    """Convierte el informe a PDF con Chromium headless (Playwright)."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("  ! PDF omitido: instala playwright en .venv-eval (pip install playwright)")
        return
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.emulate_media(color_scheme="light")
        await page.goto(html_path.resolve().as_uri())
        await page.pdf(path=str(pdf_path), format="A4", print_background=True,
                       margin={"top": "12mm", "bottom": "12mm", "left": "10mm", "right": "10mm"})
        await browser.close()
    print(f"  PDF: {pdf_path}")
