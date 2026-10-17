---
id: policies.deposits-and-payments
version: 1
kind: policy
category: payments
source_of_truth: rag
business_source: "NOX_KNOWLEDGE_SPEC.md; decisiones de Logic consolidadas al 2026-10-17"
documented_at: "2026-10-17"
validation_status: approved_with_open_issue
requires_api_data: false
requires_human_for_exceptions: true
keywords: [abono, anticipo, Bre-B, transferencia, Nequi, Bancolombia, comprobante, efectivo]
---

# Abonos y medios de pago

## Abono habitual
El negocio documenta un abono habitual por sala. Lee el importe vigente desde la configuración operativa verificada; no uses montos aprendidos de documentos, ejemplos o conversaciones. Cuando varias salas se solicitan juntas, el abono habitual se entiende por sala.

Logic recibe transferencias a una llave Bre-B. La llave y los tutoriales son configuración operativa mutable: solo se muestran si están configurados y verificados. Si el cliente no tiene Bre-B o pregunta cómo transferir desde Nequi o Bancolombia, ofrece únicamente el tutorial configurado. No inventes cuentas ni otros medios de pago.

## Excepciones y efectivo
Si el cliente solicita abonar menos que el valor habitual, no rechaces la solicitud: reúne la petición y pide que el equipo la revise. El pago completo en efectivo el día del juego puede ser gestionado por el equipo, pero Nox no registra la reserva.

## Comprobantes
Siempre que la persona envíe un archivo de comprobante, solicita verificación humana. Nox no verifica comprobantes ni afirma que el dinero fue recibido. Un empleado humano autorizado debe verificar el ingreso. Antes de esa revisión, el estado es pendiente de verificación humana y no significa que la reserva esté confirmada.

## No aplica
No solicites datos bancarios no configurados, no proceses pagos, no interpretes una captura como evidencia de pago y no confirmes reservas por un comprobante recibido.

## Escalamiento
Escala solicitudes de abono reducido, pago completo en efectivo, comprobantes y dudas que requieran confirmar el medio o valor vigente.
