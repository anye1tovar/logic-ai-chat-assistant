# Consolidación de la matriz diligenciada

La consolidación se calculó a partir de las valoraciones humanas de `evaluation/review/matriz_evaluacion_manual.csv`. No se modificó la matriz importada ni se reescribió el capítulo 4.

## Resultados agregados

| Medida | Resultado | n |
|---|---:|---:|
| Fidelidad media (0–2) | 1,475 | 40 |
| Fidelidad 0 / 1 / 2 | 20 % / 12,5 % / 67,5 % | 40 |
| Relevancia media (0–2) | 1,50 | 40 |
| Relevancia 0 / 1 / 2 | 22,5 % / 5 % / 72,5 % | 40 |
| Exactitud comercial marcada `Sí` | 72,5 % | 40 |
| Exactitud comercial marcada `No` | 27,5 % | 40 |
| Presencia de afirmaciones no sustentadas marcada `No` | 100 % | 40 |
| Manejo de excepciones/incertidumbre | Sin valoración | 0 |

El 100 % en la fila de afirmaciones refleja únicamente que las 40 celdas fueron diligenciadas como `No` por el evaluador. No es una medición automática independiente. Las celdas vacías de manejo de excepciones se excluyeron del cálculo; no se trataron como cero.

## Promedios por categoría

| Categoría | Casos | Fidelidad media | Relevancia media | Exactitud comercial `Sí` |
|---|---:|---:|---:|---:|
| `general_structured` | 10 | 1,50 | 1,40 | 70 % |
| `room_price_conditions` | 10 | 1,50 | 1,50 | 70 % |
| `availability_quote` | 10 | 1,70 | 1,80 | 80 % |
| `ambiguous_unsupported_exception` | 10 | 1,20 | 1,30 | 70 % |

## Procedencia y limitaciones

La matriz adjunta contiene 40 respuestas no vacías y puntuaciones humanas. Sin embargo, todas las celdas de `Ruta observada` dicen `Sin selección` y todas las de `Fuente o fuentes consultadas` dicen `Ninguna: falló antes de consultar herramientas`, que corresponden a la corrida fallida anterior. Esas columnas no describen la ejecución manual y no se usaron para calcular resultados. Para que la matriz sirva como registro completo de esa corrida, deben actualizarse con las rutas y fuentes realmente observadas, o marcarse como no registradas.

Los promedios y porcentajes son descriptivos de los 40 casos de este conjunto. No son resultados de participantes ni evidencia de satisfacción de clientes. Las gráficas SVG y tablas CSV se generan desde la misma matriz con `evaluation/consolidate.py`.
