---
id: policies.cancellation-rescheduling-no-show
version: 1
kind: policy
category: reservations
source_of_truth: rag
business_source: "NOX_KNOWLEDGE_SPEC.md; Conocimiento(3).pdf y Bloques de conocimiento.pdf según consolidación"
documented_at: "2026-10-17"
validation_status: approved
requires_api_data: false
requires_human_for_exceptions: true
keywords: [cancelar, devolución, reembolso, reprogramar, cambiar fecha, no-show, no asistencia]
---

# Cancelaciones, reprogramaciones y ausencia

## Cancelación solicitada por el cliente
Como regla general, Logic no devuelve dinero cuando el cliente cancela. No apliques esta regla a una cancelación iniciada por Logic.

## Reprogramación
Se permite una reprogramación, solicitada con al menos un día de anticipación. Una solicitud con menos de 24 horas requiere evaluación humana. Nox no modifica reservas.

## No presentación
Si el cliente no se presenta, pierde el abono. Si disputa esta regla o describe circunstancias extraordinarias, deriva el caso a una persona.

## Cancelación por parte de Logic
Cuando Logic cancela por una causa interna, el equipo evalúa primero un cambio de sala si procede, después una reprogramación y, como última instancia, una devolución. El equipo humano determina y ejecuta la alternativa.

## No aplica
No prometas una devolución, cambio, excepción o resultado antes de la decisión humana. La regla general de cancelación del cliente no resuelve cancelaciones causadas por Logic.

## Escalamiento
Escala toda reprogramación excepcional, solicitud de devolución, desacuerdo, reclamación o cancelación por causa interna.
