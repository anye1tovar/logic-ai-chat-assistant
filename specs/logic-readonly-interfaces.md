# Contrato lógico de lectura y atención humana

Este documento distingue lo implementado/documentado de las necesidades futuras. Los nombres `getRooms`, `getQuote`, `getOpeningHours`, `getAvailability` y `requestHumanAttention` son operaciones lógicas; no son endpoints nuevos.

## Lecturas de Logic documentadas

| Operación lógica | Operación HTTP documentada | Parámetros | Uso |
|---|---|---|---|
| `getRooms()` | `GET /api/rooms` | ninguno | Catálogo y atributos estructurados. La respuesta actual refleja `SELECT *`; el backend del asistente debe aplicar allowlist. |
| `getRates(dayType?)` | `GET /api/rates` | `dayType` opcional: `weekday` o `weekend` | Referencia de tarifas; no sustituye una cotización concreta. |
| `getQuote(date, attendees)` | `GET /api/bookings/quote` | `date=YYYY-MM-DD`, `attendees=N` | Total concreto según fecha y participantes totales. El endpoint no recibe distribución por sala; validar el aforo de cada sala por separado. |
| `getOpeningHours()` | `GET /api/bookings/opening-hours` | ninguno | Horario general por día de semana. No confirma disponibilidad de una fecha. |
| `getAvailability(date)` | `GET /api/bookings/availability` | `date=YYYY-MM-DD` | Consulta nueva de todas las salas/franjas para esa fecha. Filtrar por `roomId` en el asistente si hace falta. |

La base URL viene de `LOGIC_API_BASE_URL`; usar timeout. Caché configurable solo para salas, tarifas y horario general. Cotizaciones y disponibilidad no se cachean. La fecha se interpreta en `America/Bogota`. El cliente implementado en `backend/app/logic_api/client.py` cubre estas operaciones de lectura.

## Verificación del despliegue

El responsable confirmó el 2026-10-17 que el host de producción informado es público y no requiere autorización. Se hicieron consultas GET sin credenciales a las cinco operaciones anteriores; todas respondieron satisfactoriamente y sus campos principales coincidieron con estos modelos:

- Salas: `id`, `name`, `description`, `theme`, `min_players`, `max_players`, `min_age`, `duration_minutes`, `difficulty`, `active`, `cover_image`, `video_url`. El adaptador conserva solo los campos seguros permitidos.
- Tarifas: `id`, `day_type`, `day_label`, `day_range`, `players`, `price_per_person`, `currency`.
- Horarios: `dayOfWeek`, `openTime`, `closeTime`, `isOpen`, `requiresAdvanceBooking`.
- Cotización: `date`, `dayType`, `isHoliday`, `players`, `currency`, `pricePerPerson`, `total`.
- Disponibilidad: encabezado `date`, `dayType`, `isHoliday`, `rates`, `timezone`, `serverNow`, `minAdvanceMinutes`, `rooms`; cada sala incluye `roomId`, nombre, capacidades, duración, dificultad y `slots`.

No se guardó la URL de producción en archivos ni en `.env.example`: cada entorno debe suministrar `LOGIC_API_BASE_URL`. La verificación confirma el contrato observado en esa fecha; los registros de salas y tarifas siguen siendo datos dinámicos y el esquema público no está versionado.

La regla de negocio confirmada establece que grupos de siete o más personas usan el precio por persona del tramo de siete, incluso al distribuir el grupo entre varias salas. El código fuente de Logic revisado para este proyecto selecciona tarifa exacta por cantidad o, si no existe, el mayor tramo inferior; para cantidades superiores al tramo máximo esto corresponde al tramo de siete. La respuesta total aún debe obtenerse de `getQuote` para la fecha y el total de participantes, sin cálculo manual. No se ha verificado una llamada al API desplegado; confirmar que el despliegue coincide con ese código antes de producción. Si la cotización real no refleja la política, pedir revisión humana.

## Errores y verificación

- HTTP `400`: solicitud inválida; códigos `DAY_CLOSED` y `OPENING_HOURS_MISSING` son casos funcionales diferenciados cuando la API los devuelve.
- HTTP `409`: conflicto, no disponibilidad; no traducirlo como reserva creada.
- HTTP `5xx` o timeout: API no verificable; no usar valores estáticos RAG para completar el dato.
- `GET /api/rooms` y `GET /api/rates` no tienen DTO versionado. Validar respuestas contra el contrato disponible y no reenviar objetos arbitrarios al modelo.

## Operaciones prohibidas en este MVP

No invocar `POST /api/bookings`, `GET /api/bookings`, `GET /api/bookings/:id` ni `GET /api/bookings/consult/:code`. La autorización de lectura no autoriza escritura.

## Solicitud de atención humana — comportamiento acordado, integración pendiente

Necesidad lógica propuesta:

```text
requestHumanAttention(conversationId, reasonCode, summary, reservationRequestDraft?)
  -> { registered: boolean, pendingTagApplied: boolean, unread: boolean, requestId?: string }
```

Esta interfaz no corresponde a una ruta conocida ni a una herramienta implementada en este repositorio. El flujo acordado informa amablemente que el caso se pasará a un asesor y debe marcar la conversación con el tag `pendiente` y dejarla como no leída. Antes de integrarla, identificar el sistema de conversaciones real, su autenticación, contrato y acuse de ambas acciones. Nox solo confirma que quedó marcado después del acuse; no declara asignación/toma sin acuse independiente. Si no hay integración o falla, informa que no pudo dejar el caso marcado para atención.

Los estados sugeridos `bot_active`, `pending_human_attention`, `human_active` y `closed` son conceptos, no estados implementados.
