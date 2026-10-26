# Evaluación del asistente con RAGAs

Golden dataset, métricas, cómo reproducir la evaluación y resultados de la línea base.

## 1. Golden dataset

[`tests/golden_dataset.json`](../tests/golden_dataset.json) es la fuente de verdad. Al ejecutar la evaluación
se sincroniza con `tfm.golden_dataset` (upsert por `code`), y el portal lo muestra en **Evaluación → Golden
dataset**.

| Grupo | Preguntas | Comportamiento esperado |
|-------|-----------|-------------------------|
| Con respuesta en el corpus | 24 (GD-01…GD-24): 4 por cada uno de los 6 documentos indexados | Responder con cita al documento esperado |
| Fuera de alcance | 6 (GD-25…GD-30), 2 de ellas trampa (GD-28, GD-29: temas vecinos a documentos reales) | Abstenerse |
| Síntoma + "¿qué acción debo tomar?" | 6 (GD-31…GD-36), añadidas tras el análisis de falsas abstenciones (§4) | Responder con el procedimiento |

Dificultad: 14 fáciles, 18 medias, 4 difíciles. Cada pregunta guarda su respuesta de referencia, que necesitan
*context precision* y *context recall*.

## 2. Métricas

| Métrica | Qué mide | Sobre qué preguntas |
|---------|----------|---------------------|
| **Faithfulness** (RAGAs) | Proporción de afirmaciones de la respuesta respaldadas por el contexto | Respondidas, con respuesta en el corpus |
| **Answer relevancy** (RAGAs) | Similitud entre la pregunta y las preguntas que el juez reconstruye a partir de la respuesta | Ídem |
| **Context precision** (RAGAs) | Si los fragmentos útiles aparecen en las primeras posiciones | Todas las que tienen respuesta, **también si el modelo se abstuvo** |
| **Context recall** (RAGAs) | Si el contexto contiene lo necesario para la respuesta de referencia | Ídem |
| Falsa abstención (LLM) | El modelo se abstuvo aunque el contexto contenía la respuesta (documento esperado presente y `context_recall` ≥ 0,5) | Con respuesta en el corpus, por intento |
| Falsa abstención (recuperación) | El documento esperado no llegó al contexto, o llegó sin el fragmento con la respuesta | Ídem |
| Abstención correcta | No inventa ante preguntas fuera de alcance | Fuera de alcance, por intento |
| Hit rate@k · MRR | Posición del documento esperado entre los fragmentos que recibe el LLM | Con respuesta en el corpus |
| Latencia p50 / p95 | Tiempo total de extremo a extremo medido por el rag-service | Todas |

Para separar los dos tipos de abstención, la petición lleva `include_contexts: true`. Con ese campo, el
rag-service devuelve el texto completo de los fragmentos que recibió el LLM, aunque se abstenga. En una consulta
normal, una abstención no devuelve fuentes.

## 3. Cómo ejecutarla

RAGAs 0.4 importa módulos de LangChain que `langchain-community` 0.4 ya no incluye. Esas versiones son
incompatibles con el entorno de los microservicios, así que la evaluación usa un entorno aislado:

```powershell
py -3.12 -m venv .venv-eval
.\.venv-eval\Scripts\pip install -r scripts\requirements-eval.txt

# stack levantado (gateway en :8000) y Ollama en el host
.\.venv-eval\Scripts\python scripts\run_evaluation.py --repeat 3 --pdf --label "baseline gemma4"
```

| Opción | Uso |
|--------|-----|
| `--repeat N` | Cada pregunta se hace N veces: estima la tasa de falsa abstención y detecta preguntas inestables |
| `--ids GD-01,GD-25` | Subconjunto |
| `--no-ragas` | Solo abstención, recuperación y latencia (sin juez LLM; ~1 min) |
| `--no-upload` | No toca Supabase |
| `--judge-model`, `--judge-base-url` | Juez distinto del generador (cualquier API compatible con OpenAI; clave en `EVAL_JUDGE_API_KEY`) |

Salida en `reports/evaluation/<fecha>/`: `results.json` (completo, con el texto de los contextos),
`report.html` y `report.pdf`. La ejecución se guarda en `tfm.evaluation_runs` sin el texto de los contextos.
El portal la muestra en **Evaluación**: la última ejecución, la evolución y las preguntas a revisar. El informe
incluye una tabla comparativa con las 5 ejecuciones anteriores.

## 4. Resultados de la línea base (25/10/2026)

LLM `gemma4:31b-cloud` (Ollama Cloud, plan gratuito); juez el mismo modelo a temperatura 0; embeddings
`paraphrase-multilingual-MiniLM-L12-v2`. 30 preguntas × 3 repeticiones = 90 consultas; 12,5 min en total.
Informe: [`docs/evaluation/baseline-gemma4.pdf`](evaluation/baseline-gemma4.pdf)
([HTML](evaluation/baseline-gemma4.html)).

| Métrica | Resultado | Objetivo |
|---------|-----------|----------|
| Faithfulness | **0,739** | ≥ 0,85 ⚠️ |
| Answer relevancy | **0,760** | ≥ 0,80 ⚠️ |
| Context precision | **0,958** | ≥ 0,75 ✅ |
| Context recall | **0,954** | ≥ 0,80 ✅ |
| Falsa abstención | **0 / 72 intentos (0 %)** | — |
| Abstención correcta (fuera de alcance) | **18 / 18 (100 %)** | — |
| Hit rate@k (k ≤ 5) · MRR | **100 % · 1,00** | — |
| Latencia p50 · p95 | **2,4 s · 5,2 s** | — |

### Análisis

**La recuperación no es el cuello de botella.** En las 24 preguntas, el documento correcto llegó en primera
posición (MRR 1,0) y precision y recall superan 0,95. El umbral de similitud (0,35) y el reranker multilingüe
separan bien lo que está en el corpus de lo que no. De las 6 preguntas fuera de alcance, 3 se abstienen en la
recuperación, sin llamar al LLM (≈0,15 s). Las otras 3 (Kafka y las dos trampa, GD-28 y GD-29) sí recuperan
fragmentos de temas cercanos, como el certificado del HSM o la base de datos del core. Es el LLM quien las
rechaza correctamente (`modelo_sin_evidencia`, ≈1,2 s) en las 9 repeticiones: las dos capas de abstención se
complementan.

**Faithfulness lo penaliza la plantilla de respuesta, no las alucinaciones.** El prompt de sistema exige cuatro
secciones: *problema técnico*, *procedimiento*, *fuente documental* e *incertidumbres o información faltante*.
RAGAs descompone la respuesta en afirmaciones y marca como no respaldadas las que no están en el contexto:

- la reformulación del problema ("Identificación del significado del código CIE-305…");
- la sección de incertidumbres ("No se dispone del procedimiento específico de depuración…"), que es
  justamente el comportamiento prudente que se busca.

En los casos de menor puntuación (GD-02: 0,40; GD-07: 0,50), el procedimiento citado coincide literalmente con
el documento. Es una limitación conocida de faithfulness con respuestas estructuradas. Hay dos formas de
mejorar la métrica sin perder trazabilidad: puntuar solo la sección *procedimiento*, o quitar del prompt la
reformulación del problema. Las dos cambian el formato que ven los usuarios, así que quedan como decisión de
producto.

**Answer relevancy** baja por el mismo motivo: las secciones de fuente e incertidumbres generan preguntas
reconstruidas que se alejan de la original (GD-01: 0,51; GD-04: 0,51).

**Falsa abstención: era un problema de chunking, no del LLM.** En el golden dataset fue del 0 % (72 intentos),
pero en la Fase 6 se había visto que, con un documento corto recién subido, el asistente se abstenía a menudo.
La investigación siguió tres pasos:

1. **Hipótesis inicial: la formulación.** Una sonda de 12 consultas sobre ese documento dio 3 abstenciones de
   4 con "El monitor de colas muestra la alerta X, ¿qué acción debo tomar?", y 0 de 8 con otras formulaciones.
   El documento esperado aparecía siempre en primera posición, lo que apuntaba al LLM.
2. **Descartada.** Se añadieron al golden dataset 6 preguntas con esa misma forma sobre el corpus estable
   (GD-31…GD-36): 0 abstenciones en 24 intentos.
3. **Causa real.** Se reprodujo el caso llamando al LLM con el contexto exacto que recibía (8/8 abstenciones) y
   se inspeccionó ese contexto. El documento tiene dos secciones muy cortas, *Síntoma* y *Acción*, y el
   chunker generaba **un fragmento por sección**. La pregunta, que menciona la alerta, recuperaba el fragmento
   del síntoma. El de la acción, que no la menciona, quedaba fuera del top 5. **El LLM se abstenía con razón:
   el procedimiento no estaba en su contexto.** La métrica lo había clasificado como falsa abstención del LLM
   porque solo comprobaba que el *documento* estuviera presente, no el *fragmento* con la respuesta.

**Corrección.** El chunker agrupa ahora las secciones cortas consecutivas de una misma página en un solo
fragmento, conservando sus encabezados, mientras quepan en 700 caracteres. Con el mismo documento y la misma
pregunta, las abstenciones bajan de **8/8 a 0/8**, sin tocar el prompt. La métrica también se corrigió: una
abstención con el documento presente pero `context_recall < 0,5` se clasifica como fallo de recuperación.

### Resultados tras la corrección (`chunking por secciones cortas`)

Corpus reindexado; golden dataset ampliado a 36 preguntas; 36 × 3 = 108 consultas. Informe:
[`docs/evaluation/chunking-secciones.pdf`](evaluation/chunking-secciones.pdf)
([HTML](evaluation/chunking-secciones.html)), con la comparativa contra la línea base.

| Sobre las mismas 24 preguntas con respuesta | Línea base | Tras la corrección |
|---------------------------------------------|------------|--------------------|
| Faithfulness | 0,739 | **0,758** |
| Answer relevancy | 0,760 | **0,766** |
| Context precision | 0,958 | **0,987** |
| Context recall | 0,954 | **0,963** |
| Latencia p50 | 2,6 s | **1,9 s** |

| Ejecución completa (36 preguntas × 3) | Resultado |
|---------------------------------------|-----------|
| Falsa abstención | 0 / 90 |
| Abstención correcta (fuera de alcance) | 18 / 18 |
| Hit rate · MRR | 100 % · 1,00 |
| Preguntas nuevas GD-31…GD-36 | 18/18 respondidas; context precision 0,79 y recall 0,83 |

Todas las métricas mejoran sobre las mismas preguntas. En MAN-BD-003 y FAQ-VPN-001, las secciones cortas
pasaron de 5 y 4 fragmentos a 2 cada uno. Así el LLM recibe procedimientos completos y menos fragmentos
irrelevantes, lo que explica la mejora de precisión y latencia. Las preguntas nuevas tienen menor precisión de
contexto porque su respuesta abarca más de un fragmento (p. ej. diagnóstico y escalamiento).

**Lección para la memoria:** una métrica a nivel de documento ocultó un fallo a nivel de fragmento. Reproducir el
caso con el contexto exacto que recibe el LLM permitió encontrar la causa, en lugar de ajustar el prompt a ciegas.

**Sesgo del juez.** El juez es el mismo modelo que genera, lo que puede inflar o desinflar las métricas por
autoevaluación. Para cifras definitivas en la memoria del TFM, conviene repetir con un juez distinto
(`--judge-model`/`--judge-base-url`, p. ej. Claude u OpenAI).

## 5. Prueba de carga

[`scripts/load_test.py`](../scripts/load_test.py) (Locust) simula operadores que consultan al asistente,
comprueban la salud del sistema y, con `LOAD_TEST_USER_EMAIL`, abren el dashboard. Las respuestas 429 del rate
limiting se cuentan aparte y no como fallos. Ver resultados y comandos en el
[README](../README.md#fase-8--evaluación-observabilidad-y-documentación).
