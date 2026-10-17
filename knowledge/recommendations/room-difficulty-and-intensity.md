---
id: recommendations.room-difficulty-and-intensity
version: 1
kind: recommendation
category: faq
source_of_truth: rag
business_source: "NOX_KNOWLEDGE_SPEC.md; documentación del negocio consolidada al 2026-10-17"
documented_at: "2026-10-17"
validation_status: approved_with_open_issue
requires_api_data: true
requires_human_for_exceptions: true
keywords: [recomendar sala, temática, terror, sustos, dificultad, familiar, tranquilo, Caníbal, Portal, La Secta, Manicomio]
---

# Temática e intensidad de las experiencias

## Regla de catálogo
Las descripciones de este documento son referencias de recomendación, no confirman que una sala siga activa ni sustituyen la descripción vigente. Antes de presentar una sala como disponible para jugar, consulta el catálogo activo en la API. Obtén de la API sus descripciones y videos actuales cuando existan.

## Referencias temáticas documentadas
- **Portal:** aventura, orientada a público familiar y parejas; referencia documental de dificultad 2/5.
- **Caníbal:** terror con sustos repentinos; referencia documental de dificultad 3/5. No tiene actores, contacto físico ni persecuciones. El equipo puede reducir o eliminar los sustos si se solicita; Nox comunica la preferencia, pero no afirma que el ajuste ya se aplicó.
- **La Secta:** terror paranormal con sustos repentinos producidos por mecanismos; referencia documental de dificultad 3/5. No tiene actores, contacto físico ni persecuciones. Los sustos no se pueden reducir ni eliminar.
- **Manicomio:** suspenso, relativamente tranquila; referencia documental de dificultad 4/5.

## Cómo recomendar
Pregunta progresivamente por temática, número de participantes y edades. Considera el mínimo vigente de jugadores devuelto por API, edades, acompañamiento, dificultad y condiciones particulares. No recomiendes una sala que no cumpla su mínimo.

## No aplica
No uses estas referencias para afirmar que una sala está activa, para responder características estructuradas que ya ofrece la API ni para divulgar finales, soluciones o secretos de acertijos.

## Escalamiento
Escala cuando la preferencia o condición del grupo requiera una adaptación del equipo o cuando no puedas verificar la vigencia de la información.
