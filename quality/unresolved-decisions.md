# Decisiones pendientes de integración y validación

Mantener estos pendientes explícitos; no completar vacíos por inferencia.

| ID | Pendiente | Comportamiento provisional |
|---|---|---|
No colocar llaves ni enlaces reales en el corpus o en fixtures. Los datos operativos proporcionados se guardan solo en el `.env` local ignorado por Git; no se copian al corpus ni a fixtures.

## Decisiones resueltas por el responsable del proyecto — 2026-10-17

| ID | Decisión confirmada | Reflejo documental |
|---|---|---|
| P-02 | El responsable confirmó que el API desplegado es público y no requiere autorización. El 2026-10-17 se probaron con GET, sin credenciales, las cinco operaciones de lectura documentadas: salas, tarifas, horarios de apertura, cotización y disponibilidad. | `specs/logic-readonly-interfaces.md`; `backend/app/logic_api/client.py`. |
| P-01 | Desde siete participantes se usa el precio por persona vigente del tramo de siete, incluso si ocho o más personas se distribuyen entre varias salas. Aplicar capacidades de cada sala y consultar la cotización/tarifa vigente. | `knowledge/policies/groups-and-special-pricing.md`; escenarios T05–T06. |
| P-04 | Logic no ofrece servicio de torta. El cliente puede llevar su propia torta de cumpleaños sin costo. | `knowledge/experience/birthdays-and-cafeteria.md`; escenario T17. |
| P-05 | El uso de cafetería es libre y no existe tiempo de antelación establecido. | `knowledge/experience/birthdays-and-cafeteria.md`; escenario T34. |
| P-06 | Siempre que se envíe un archivo de comprobante, solicitar verificación humana. Nox nunca verifica el pago. | `knowledge/policies/deposits-and-payments.md`; escenario T13. |
| P-07 | Contar al adulto dentro del total de la excepción de Portal y pedir confirmación humana cuando se use el máximo excepcional. | `knowledge/policies/minors-and-room-limits.md`; escenario T08. |
| P-03 | Al solicitar atención humana, responder de forma amable e informativa que el caso se pasará a un asesor; marcar la conversación con el tag `pendiente` y dejarla como no leída para revisión humana. No afirmar que el asesor ya la tomó o respondió. | `knowledge/operations/human-attention.md`; `agent/nox-system.md`; escenarios T31–T32. La conexión con la plataforma de conversaciones sigue pendiente. |
| P-08 | Mantener vacíos en la plantilla los datos operativos mutables y secretos, y obtenerlos desde variables de entorno. El responsable proporcionó el abono por sala, dirección, enlaces operativos, horario humano de chat (08:00–20:00, America/Bogota) y llave Bre-B. | `config/operational-links.example.yaml`; `.env.example`; `docs/08_ENVIRONMENT_AND_COMMANDS.md`; `.env` local ignorado por Git. |

La decisión de flujo P-03 está resuelta; la integración técnica del inbox, el tag y el estado de lectura sigue pendiente de identificar y conectar la plataforma de conversaciones. Hasta que exista, no afirmar que se aplicaron esos cambios.

