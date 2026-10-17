---
id: policies.minors-and-room-limits
version: 1
kind: policy
category: age_policy
source_of_truth: rag
business_source: "NOX_KNOWLEDGE_SPEC.md; decisiones de Logic consolidadas al 2026-10-17"
documented_at: "2026-10-17"
validation_status: approved
requires_api_data: true
requires_human_for_exceptions: true
room: portal
keywords: [niños, menores, edad, acompañante, adulto responsable, aforo, capacidad, Portal, mínimo de jugadores]
---

# Menores, acompañantes y límites por sala

## Regla de edades
La política transversal documentada permite el ingreso de niños desde los nueve años con un adulto responsable. Para decidir si el adulto es obligatorio en una sala específica, consulta en la API la edad mínima vigente para ingresar sin adulto. No copies edades por sala desde documentos históricos.

Los adultos acompañantes cuentan como participantes y pagan entrada. Si solicitan un tratamiento excepcional, deriva la solicitud al equipo.

## Mínimo y máximo ordinarios
Consulta el mínimo y máximo ordinarios de cada sala en la API. Si el grupo no alcanza el mínimo, no indiques que puede jugar esa sala pagando entradas faltantes. Busca otra sala que cumpla el mínimo vigente, si los datos disponibles permiten hacerlo.

## Excepción de capacidad de Portal
Logic documenta una excepción para grupos con menores de doce años que permite hasta siete participantes en total, contando al adulto acompañante. Si el grupo supera el máximo ordinario informado por API, explica que existe una excepción condicionada y pide validación/confirmación humana. Cuando se use el máximo excepcional, no garantices unilateralmente el cupo.

## Recomendaciones para grupos de menores
Considera edades, afinidad temática y necesidad de acompañamiento; no recomiendes basándote únicamente en el precio. Si falta la edad o no puede verificarse la regla correspondiente en API, pregunta o escala.

## No aplica
Esta política no sustituye datos de capacidad ni de edad por sala devueltos por API y no autoriza excederlos unilateralmente. La excepción de Portal no se generaliza a otras salas.

## Escalamiento
Escala la excepción de Portal, solicitudes de tratamiento especial para acompañantes y cualquier situación de menores que no esté cubierta claramente por la política y los datos actuales de API.
