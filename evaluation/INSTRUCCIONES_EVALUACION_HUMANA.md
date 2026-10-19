# Evaluación humana de respuestas de Nox

## Cómo diligenciar la matriz

Abra el CSV de `review/` en una hoja de cálculo y conserve una copia del original. Revise cada respuesta completa junto con la pregunta, la ruta observada y las fuentes registradas. Las fuentes son pistas para comprobar la respuesta; que coincidan con la ruta esperada no demuestra que el contenido sea correcto.

- **Fidelidad:** 2 = todas las afirmaciones están sustentadas por la evidencia consultada; 1 = soporte parcial o una omisión relevante; 0 = afirmación central no sustentada o contradicha.
- **Relevancia:** 2 = responde directamente y con suficiencia; 1 = responde parcialmente; 0 = no responde a lo pedido.
- **Exactitud comercial:** escriba `Sí`, `Parcial`, `No` o `No aplica`. Compruebe cifras, moneda, sala, capacidad, horarios, fecha y condiciones comerciales contra su fuente de verdad.
- **Excepciones o incertidumbre:** use `Sí`, `Parcial`, `No` o `No aplica`. Valore si aplica la condición concreta, si evita generalizar una excepción y si aclara o escala cuando falta evidencia.
- **Afirmaciones no sustentadas:** use `Sí` si encuentra una o más, `No` si no encuentra ninguna y `No aplica` solo si no hay afirmaciones factuales que revisar. `Parcial` puede indicar una respuesta con afirmaciones sustentadas y otras sin soporte.
- **Observaciones:** registre brevemente la frase que motiva una puntuación distinta de 2, el dato que falta o la evidencia usada. No cambie la respuesta generada.

Deje en blanco lo que no pueda evaluar; no lo cuente como cero. No infiera satisfacción de clientes a partir de esta revisión. La matriz corresponde a una única revisión por caso y no representa acuerdo entre evaluadores.

## Consolidar cuando termine la revisión

Desde la raíz del repositorio ejecute:

```powershell
python evaluation/consolidate.py evaluation/results/current-tree-20261018-01/review/matriz_evaluacion.csv
```

El procedimiento valida valores, omite celdas sin diligenciar y crea `review/consolidated/` con JSON, CSV por categoría y gráficas SVG de fidelidad y relevancia. Los promedios usan solamente puntuaciones disponibles. Los conteos y porcentajes categóricos usan como denominador las respuestas diligenciadas para ese criterio; `No aplica` se informa por separado y no se convierte en éxito o fallo.

## Actualizar el capítulo 4 después

Transfiera al capítulo solo resultados del `consolidated_summary.json` y la evidencia automatizada de esta corrida. Indique versión/manifest, número de casos realmente puntuados por métrica, resultados por categoría, rúbrica y limitaciones. Mantenga separados los casos sin valorar; describa esta revisión como evaluación humana del contenido, no como encuesta de clientes. No sobrescriba `evaluation/results/` histórico ni mezcle corridas de versiones distintas. El capítulo 4 permanece sin cambios hasta que se revisen y acepten los resultados.
