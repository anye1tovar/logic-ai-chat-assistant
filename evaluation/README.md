# Evaluación de Nox

## Dataset

`cases.json` contiene 40 casos versionados: diez por cada categoría. Cada caso registra la ruta y fuente esperadas, el comportamiento y los criterios para la calificación humana. Las respuestas no tienen una cadena exacta esperada porque el asistente consulta datos actuales.

## Ejecutar

Desde `backend/`, con `.env` configurado, el backend de conocimiento ingerido y acceso a OpenAI y a la API de Logic:

```powershell
python -m app.evaluation.run --dataset ../evaluation/cases.json
```

Para una comprobación de menos casos:

```powershell
python -m app.evaluation.run --dataset ../evaluation/cases.json --limit 3
```

El runner hace llamadas reales al modelo y a los servicios habilitados. Cada ejecución recibe un `run_id`; sus registros se agregan a `results/raw_runs.jsonl` y `results/summary.json` se reemplaza con el resumen de la última ejecución. No usar conversaciones ni datos personales de clientes reales en el dataset.

## Resultados y calificación

Los registros incluyen ruta esperada/seleccionada, fuentes y documentos RAG, herramientas y latencias, respuesta, errores y campos manuales vacíos. El resumen calcula precisión de ruta, fallos y latencias media, mediana y p95. No puntúa automáticamente fidelidad, relevancia, alucinaciones ni abstención: una persona debe revisar cada respuesta contra `reference_answer_or_criteria` y completar `manual_review` en `raw_runs.jsonl` antes de reportar esas métricas. El runner no cuenta participantes ni respuestas de percepción.

`LogicApiClient` no expone el estado HTTP de respuestas exitosas y el modelo actual no conserva el uso de tokens; por eso `api_status_codes` queda vacío en respuestas exitosas y `token_usage` es `null`. Los códigos tipados de errores upstream sí se registran. El campo `api_result_category` refleja el resultado funcional de la herramienta, no un estado HTTP.

## Congelar una corrida oficial

Conservar el `run_id` y los hashes de código, prompt, dataset y conocimiento que registra el resumen. Anotar también el modelo configurado y no mezclar corridas después de cambiar el código, el prompt o los documentos; cada cambio inicia una nueva iteración.

## Cuestionario de percepción

Aplicar por separado a cada participante, al finalizar las tareas. Escala: 1 = totalmente en desacuerdo, 5 = totalmente de acuerdo. No completar datos de participantes antes de reclutarlos.

1. Las respuestas fueron claras.
2. Las respuestas me resultaron útiles.
3. Las respuestas fueron pertinentes a mis preguntas.
4. Confío en la información que entrega el asistente.
5. El asistente respondió con rapidez.
6. Fue fácil conversar con el asistente.
7. Estoy satisfecho/a con la experiencia.
8. Volvería a usar este asistente.

Registrar respuestas anonimizadas y el número real de participantes fuera de los logs técnicos.

## Release evidence and limits

`results/release_manifest.json` identifies the latest preserved run, relates its `run_id` to the 40 corresponding rows in `raw_runs.jsonl`, and records artifact hashes. It also documents that the historical run's prompt hash does not match the current prompt, the runner did not capture the working-tree diff, and no manual answer-quality review was completed. Treat that run as historical evidence, not certification of the current working tree.

`raw_runs.jsonl` contains multiple iterations. Filter by `run_id`; `summary.json` describes only the latest run and is replaced by each execution. The runner records the Git `HEAD` commit but not modified or untracked file contents. Run an official evaluation from a clean working tree and preserve its commit and artifact hashes.
