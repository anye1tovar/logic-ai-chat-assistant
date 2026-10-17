---
id: policies.groups-and-special-pricing
version: 1
kind: policy
category: pricing
source_of_truth: rag
business_source: "NOX_KNOWLEDGE_SPEC.md; documentación del negocio consolidada al 2026-10-17"
documented_at: "2026-10-17"
validation_status: approved
requires_api_data: true
requires_human_for_exceptions: true
keywords: [grupos grandes, muchas personas, siete o más, varias salas, precio especial, tarifa por persona]
---

# Grupos grandes y precio especial

## Regla de grupo
Para grupos de siete o más personas, se mantiene para cada persona el precio por persona vigente del tramo de siete participantes. Esto también aplica cuando el grupo se distribuye entre dos o más salas en una misma solicitud, sujeto a los mínimos y máximos ordinarios de cada sala.

Consulta siempre la tarifa o cotización vigente de Logic para la fecha. No guardes ni uses montos históricos del PDF. Si la cotización API no refleja inequívocamente la regla para el grupo completo, pide validación humana en vez de calcular el total por cuenta propia.

## No aplica
La política de precio no modifica mínimos ni máximos de capacidad de una sala. No calcules un total manual cuando Logic pueda cotizarlo y no presentes una cifra histórica como tarifa vigente.

## Escalamiento
Escala si la API no cotiza de forma inequívoca el grupo o si hay un conflicto entre precio y capacidad. Al finalizar la solicitud, la reserva requiere gestión humana.
