# Intento de corrida actual: `a9c222c3ee31470590ce25a0904a907c`

Este intento contiene 40 registros, pero no es una corrida válida para evaluar respuestas sustantivas. Las 40 llamadas de selección de ruta fallaron con `APIConnectionError`; Nox devolvió el mensaje de contingencia y no llegó a consultar la Logic API ni el índice RAG. No hubo mocks. Por eso la exactitud automatizada 0 % / 2,5 % del resumen describe fallos de instrumentación/selección en este intento y no calidad conversacional ni selección real de fuentes.

## Comparación con la evidencia histórica

| Elemento | Histórica (`dd5fca9e…`) | Intento actual (`a9c222c3…`) |
|---|---|---|
| Revisión Git reportada | `32832660c8ab415d0c62f2e9210d772ae2ebb732` | mismo `HEAD`, árbol local modificado |
| Modelo | `gpt-6-luna` | `gpt-6-luna` |
| Prompt SHA-256 | `4ff142c94fbbc23f1fc56230c6fe637a88e8de8c9b52ecd2fa5dc2adc51281a8` | `dfb60c8ffa73748faf92934b5a61519d8479ee04e00ab463746d21552cda9de0` |
| Dataset SHA-256 | `c87f9835ec3d3812be02935425cd29980fec0a0a98de8446b73480c428df4885` | igual |
| Conocimiento Markdown SHA-256 | `f77facc1a30d8f386d9f17a56e1fbbdad29d116b6d713bc720dcafb6919a33b0` | igual |
| Resultados | 40 casos; 0 errores registrados | 40 casos; 40 fallos de conexión del proveedor LLM |
| Herramientas | evidencias históricas anteriores | 0 llamadas; ni API ni RAG consultados |

El mismo `HEAD` no implica mismo código evaluado: la corrida histórica no capturó diff ni archivos no confirmados, y la corrida actual se hizo con el árbol de trabajo sucio. `run_manifest.json` y `reproduction_source_snapshot.zip` identifican el estado y los archivos relevantes empaquetados. No se sobrescribió la corrida histórica.

El intento y su matriz se conservan para trazabilidad. Las celdas de valoración están vacías. Para revisar calidad conversacional hay que repetir los 40 casos con acceso aprobado al proveedor configurado y Logic API, en un directorio de salida diferente; esta repetición requiere autorización explícita para enviar preguntas del dataset y solicitudes de recuperación al proveedor externo identificado en el manifiesto.
