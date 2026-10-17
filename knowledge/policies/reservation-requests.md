---
id: policies.reservation-requests
version: 1
kind: policy
category: reservations
source_of_truth: rag
business_source: "NOX_KNOWLEDGE_SPEC.md; decisiones de Logic consolidadas al 2026-10-17"
documented_at: "2026-10-17"
validation_status: approved
requires_api_data: true
requires_human_for_exceptions: true
keywords: [solicitud de reserva, reservar, varias salas, disponibilidad, confirmar]
---

# Solicitud de reserva y confirmación

## Regla general
Nox puede consultar disponibilidad vigente y reunir una solicitud para que el equipo humano gestione el registro. Nox no crea, bloquea, modifica ni confirma reservas. Solo el equipo de Logic confirma una reserva.

Si la API muestra una franja disponible, preséntala como disponible según la consulta y aclara que está sujeta a disponibilidad cuando el equipo confirme. No prometas que se conserva durante un periodo ni reproduzcas prioridades manuales de solicitudes sin pago.

## Datos de la solicitud
Cuando el cliente quiera continuar, recopila progresivamente:

- nombre y celular;
- sala o salas solicitadas;
- fecha y hora deseadas;
- cantidad de participantes.

Edades y observaciones especiales son opcionales, pero pregunta edades cuando hagan falta para validar acompañamiento o una recomendación. Las observaciones pueden describir cumpleaños, evento, team building u otra necesidad. Una solicitud puede incluir varias salas.

## Disponibilidad y horarios especiales
Consulta disponibilidad en Logic para la fecha y sala en el momento de la solicitud. No reutilices disponibilidad de turnos anteriores. Para una hora fuera de los horarios publicados por API, reúne la solicitud y pide revisión humana; no asegures que Logic abrirá.

## Continuación humana
Al terminar de reunir datos, solicita atención humana solo mediante una integración que registre efectivamente la solicitud. Nox puede decir que pidió la intervención únicamente tras recibir confirmación del sistema. No digas que la reserva está registrada, asignada o confirmada. Si no existe esa integración o falla, explica que no pudo registrar la solicitud.

## No aplica
Este procedimiento no autoriza a Nox a invocar endpoints de escritura, verificar pagos, bloquear franjas o confirmar reservas.

## Escalamiento
Solicita revisión humana para registrar la reserva, para horarios especiales y cuando no se pueda completar o registrar la solicitud de forma fiable.
