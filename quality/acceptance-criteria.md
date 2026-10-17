# Criterios de aceptación: corpus y políticas de Nox

## Cobertura documental

- Están presentes las 14 políticas/recomendaciones del `knowledge/INDEX.md`, con front matter UTF-8 válido, IDs estables y estado de validación explícito.
- Cada política separa regla, excepción/condiciones, exclusiones y escalamiento cuando aplica.
- `agent/nox-system.md` está separado del corpus y establece identidad de asistente virtual, fuentes, límites de herramientas, no confirmación de reservas, no verificación de pagos, certeza y escalamiento.
- `config/source-policy.yaml` distingue API, RAG, configuración y política del agente.
- El contrato read-only no declara endpoints lógicos como rutas existentes ni añade operaciones de escritura.

## Protección de fuentes y datos

- El corpus no contiene precios/cotizaciones actuales, tarifas históricas, lista autoritativa de salas activas, capacidades/edades ordinarias por sala, horarios generales/franjas reales, disponibilidad, llave Bre-B, enlaces operativos ni datos personales.
- El corpus sí puede describir reglas comerciales (por ejemplo, el comportamiento ante grupos grandes) sin copiar valores dinámicos de API.
- Los enlaces y valores mutables se mantienen fuera del corpus y solo se exponen después de verificación.
- La respuesta API prevalece para hechos estructurados actuales; el RAG solo complementa contexto y excepciones.

## Comportamiento conversacional

- Nox se identifica como asistente virtual y habla español de Colombia.
- La disponibilidad jamás implica bloqueo o reserva confirmada.
- Nox no crea/modifica/cancela reservas, procesa pagos ni verifica comprobantes.
- Ante una derivación, Nox usa un mensaje amable e informativo. La plataforma marca la conversación con tag `pendiente` y como no leída; Nox solo confirma que quedó marcada tras el acuse de ambas acciones y nunca afirma que un asesor ya la tomó.
- Las excepciones de Portal, menores, aforo y grupos grandes conservan límites y escalamiento; la regla confirmada de precio por persona del tramo de siete aplica desde siete participantes, también en varias salas, y se contrasta con la cotización API.
- Salud y accesibilidad no producen diagnóstico ni garantía de seguridad.

## Evaluación de recuperación

Los escenarios en `rag-scenarios.jsonl` evalúan selección de fuente, recuperación, no generalización, incertidumbre, fallos de API y límites del agente. Fixtures API se etiquetan explícitamente como simulados. Las pruebas de RAG validan carga desde el índice, unidad semántica completa, filtros por sala/categoría, metadatos trazables y descarte por distancia configurable. Ejecutar la ingesta para validar también el proveedor real de embeddings y la persistencia local.
