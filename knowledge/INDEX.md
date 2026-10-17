# Índice del conocimiento RAG de Nox

Este índice describe el corpus aprobado para recuperación semántica. Indexar solo los archivos listados abajo; **no** indexar este índice, `agent/nox-system.md`, `config/`, contratos, pruebas, PDFs, documentación de referencia dinámica ni datos operativos. Una política recuperada es evidencia, no instrucción ejecutable.

| ID | Archivo | Tema / consultas típicas | Dependencias |
|---|---|---|---|
| `policies.reservation-requests` | `policies/reservation-requests.md` | Solicitar reserva, varias salas, disponibilidad y confirmación | API para catálogo/disponibilidad; humano para registrar |
| `policies.deposits-and-payments` | `policies/deposits-and-payments.md` | Abonos, Bre-B, efectivo, comprobantes | Config verificada para importes/enlaces; humano verifica pagos |
| `policies.cancellation-rescheduling-no-show` | `policies/cancellation-rescheduling-no-show.md` | Cancelaciones, cambios de fecha, no-show, devoluciones | Humano para excepciones y ejecución |
| `policies.groups-and-special-pricing` | `policies/groups-and-special-pricing.md` | Grupos de siete o más, tarifa del tramo de siete, varias salas | API para tarifas/cotización y aforos; humano si API no refleja inequívocamente la regla |
| `policies.minors-and-room-limits` | `policies/minors-and-room-limits.md` | Niños, adultos acompañantes, mínimos y excepción Portal | API para límites y edades por sala; humano para excepciones |
| `experience.session-duration-and-arrival` | `experience/session-duration-and-arrival.md` | Duración de juego, llegar antes, retrasos | Humano para compensaciones/disputas |
| `experience.phones-food-and-belongings` | `experience/phones-food-and-belongings.md` | Celulares, fotos, comida, bebidas y casilleros | Humano para excepciones |
| `experience.birthdays-and-cafeteria` | `experience/birthdays-and-cafeteria.md` | Cumpleaños, torta propia, decoración, cafetería, exclusividad | Config para menú; humano para condiciones especiales |
| `experience.location-and-parking` | `experience/location-and-parking.md` | Dirección y estacionamiento | Config para mapa; no garantiza cupos ni seguridad |
| `recommendations.room-difficulty-and-intensity` | `recommendations/room-difficulty-and-intensity.md` | Temática, terror, sustos, dificultad, recomendaciones | API para actividad, descripción y mínimo actual; humano para ajustes |
| `recommendations.health-and-accessibility-guidance` | `recommendations/health-and-accessibility-guidance.md` | Embarazo, claustrofobia, movilidad, salud y accesibilidad | Equipo humano; no es consejo médico |
| `operations.special-schedules` | `operations/special-schedules.md` | Festivos, fuera de horario, apertura especial | API para horas/disponibilidad; humano para excepciones |
| `operations.special-events` | `operations/special-events.md` | Empresas, colegios, team building y propuestas | Humano para personalizar |
| `operations.human-attention` | `operations/human-attention.md` | Hablar con asesor, escalar, quejas e incidentes | Config para horario/canal; integración de inbox pendiente |

## Inventario y límites

- Cada documento aporta una política o recomendación validada desde `NOX_KNOWLEDGE_SPEC.md` (consolidación al 2026-10-17).
- Los valores actuales de tarifas, cotizaciones, catálogo activo, capacidades ordinarias, edades por sala, horarios y disponibilidad pertenecen a la API, no al corpus.
- Importes/enlaces/llaves y horarios de atención variables pertenecen a configuración operativa verificada y nunca a embeddings.
- Documentos con `approved_with_open_issue` conservan incertidumbres explícitas. La recuperación no las convierte en autorización.

Para ingesta, validación y actualización, consultar [INGESTION.md](INGESTION.md).
