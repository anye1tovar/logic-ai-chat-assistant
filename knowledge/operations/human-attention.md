---
id: operations.human-attention
version: 1
kind: policy
category: customer_service_policy
source_of_truth: rag
business_source: "NOX_KNOWLEDGE_SPEC.md; decisiones de Logic consolidadas al 2026-10-17"
documented_at: "2026-10-17"
validation_status: approved_with_open_issue
requires_api_data: false
requires_human_for_exceptions: true
keywords: [asesor, persona, agente humano, hablar con alguien, queja, accidente, revisión humana, escalar]
---

# Atención y escalamiento humano

## Cuándo pedir atención
Solicita intervención humana cuando el cliente la pida, al terminar una solicitud de reserva, ante comprobantes o dudas de pago, excepciones de aforo/horario/precio, cancelaciones y reprogramaciones excepcionales, reclamaciones, incidentes, eventos personalizados, casos de salud/accesibilidad, fallos de API o información contradictoria.

## Registro y estados
Cuando el cliente pida atención humana o el caso requiera revisión, responde de forma amable e informativa que se pasará el caso a un asesor. El flujo esperado debe marcar la conversación con el tag `pendiente` y dejarla como no leída para revisión humana. Esto señala que el caso espera atención; no significa que un asesor ya esté asignado, haya tomado la conversación o haya respondido.

La integración con la plataforma de conversaciones debe confirmar que el tag y el estado no leído se aplicaron antes de afirmar que el caso quedó encaminado. En la fase actual esa plataforma no está conectada en este repositorio. Mientras no exista, informa la intención de pasar el caso a un asesor, pero no afirmes que se actualizó el tag o el estado de lectura.

No afirmes que una solicitud quedó asignada, tomada o respondida sin confirmación específica del sistema. Los estados `bot_active`, `pending_human_attention`, `human_active` y `closed` son nombres lógicos sugeridos, no funciones implementadas por este documento.

## Horario de atención
Consulta el horario humano desde la configuración operativa. No lo confundas con los horarios de apertura del escape room ni prometas un tiempo de respuesta. Fuera del horario, informa la ventana configurada sin prometer respuesta inmediata.

## Si no se puede registrar
Si la herramienta falta o falla, explica con amabilidad que no pudiste dejar el caso marcado para atención del asesor. Ofrece un canal alternativo únicamente si está configurado y verificado. No finjas que se aplicaron el tag o el estado no leído.

## No aplica
Este documento establece una política y un requisito de integración; no crea un inbox, un panel de operadores, asignación de conversaciones ni canal de contacto.

## Escalamiento
Este documento define cuándo debe solicitarse la atención humana y el resultado esperado del flujo. La aplicación efectiva del tag `pendiente` y del estado no leído depende de una integración real con acuse.
