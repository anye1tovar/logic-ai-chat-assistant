---
id: operations.special-schedules
version: 1
kind: policy
category: operational_rule
source_of_truth: rag
business_source: "NOX_KNOWLEDGE_SPEC.md; documentación del negocio consolidada al 2026-10-17"
documented_at: "2026-10-17"
validation_status: approved
requires_api_data: true
requires_human_for_exceptions: true
keywords: [horario especial, abrir, fuera de horario, franja, festivo, disponibilidad]
---

# Horarios especiales

## Horario ordinario y disponibilidad
Consulta en la API el horario general y la disponibilidad de la fecha solicitada. Los horarios de apertura no garantizan que una franja esté disponible. No uses horarios o franjas de documentos históricos como disponibilidad vigente.

## Solicitud fuera de horario
Si el cliente pide una hora que no aparece en la disponibilidad consultada o fuera de los horarios publicados, no la presentes como disponible. Reúne la solicitud y pide al equipo humano que evalúe una apertura excepcional.

## No aplica
Que un día admita reserva previa no significa que Logic aceptará cualquier horario. No bloquees franjas ni infieras excepciones por festivos.

## Escalamiento
Escala solicitudes fuera de horarios publicados, datos API faltantes y conflictos entre horario y disponibilidad.
