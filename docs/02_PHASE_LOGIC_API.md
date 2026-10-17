# Phase 2 — Logic API Adapter and Cache

## Goal

Integrate the existing Logic REST API as the structured source of truth.

This phase must work without the LLM.

## Base URL

Use:

`LOGIC_API_BASE_URL`

Never hardcode URLs.

All calls originate from the backend.

## Current API contract

### Reference rates

`GET /api/rates`

Optional:

`dayType=weekday|weekend`

Use for general/reference price information only.

The current public schema is tied to the database representation, so do not expose raw objects downstream.

### Final quote

`GET /api/bookings/quote?date=YYYY-MM-DD&attendees=N`

Use whenever the user asks for a concrete total for a date and attendee count.

Do not manually calculate a final total when this endpoint can calculate it.

### Rooms

`GET /api/rooms`

The route currently reflects the database schema.

Create an adapter that maps raw room data into an explicit assistant-safe model.

Candidate fields:

```text
name
description
videoUrl
minPlayers
maxPlayers
minimumAgeWithoutAdult
durationMinutes
difficulty
publicRoomId (only if actually present)
```

Do not invent missing fields.

### Opening hours

`GET /api/bookings/opening-hours`

Relevant fields include:

- `dayOfWeek`
- `openTime`
- `closeTime`
- `isOpen`
- `requiresAdvanceBooking`

JavaScript day numbering:

- Sunday = 0
- Monday = 1
- ...
- Saturday = 6

Specific-date closures must be resolved through availability.

### Availability

`GET /api/bookings/availability?date=YYYY-MM-DD`

Date is required.

Important response information:

- `date`
- `dayType`
- `isHoliday`
- `timezone`
- `serverNow`
- `minAdvanceMinutes`
- `rooms`
- `roomId`
- `name`
- `minPlayers`
- `maxPlayers`
- `durationMinutes`
- `difficulty`
- `slots`
- `start`
- `available`
- optional `reason`

Availability is a snapshot.

Fetch it live every time.

Never cache it.

Possible errors:

- `400`
- `DAY_CLOSED`
- `OPENING_HOURS_MISSING`

Possible slot reasons:

- `booked`
- `too_late`

## Forbidden assistant routes

Do not call:

- `GET /api/bookings`
- `GET /api/bookings/:id`
- `GET /api/bookings/consult/:code`

## Booking creation

`POST /api/bookings` exists but is outside the first MVP.

Do not implement a booking tool.

Reasons:

- personal data;
- transaction semantics;
- `409` conflicts;
- no documented idempotency key;
- uncertain retry after timeout.

## HTTP client

Create one typed Logic API client.

Suggested methods:

```python
get_rates(day_type: str | None)
get_quote(date: date, attendees: int)
get_rooms()
get_opening_hours()
get_availability(date: date)
```

The client must:

- set timeout;
- parse errors;
- return typed models;
- hide raw `httpx.Response` from business code.

## Cache

Cache:

- rooms;
- rates;
- opening hours.

Suggested default TTL:

12 hours via `LOGIC_REFERENCE_CACHE_TTL_SECONDS`.

Do not cache:

- quote;
- availability.

## Domain errors

Map to errors such as:

```text
LogicApiUnavailable
LogicInvalidRequest
LogicDayClosed
LogicOpeningHoursMissing
LogicNotFound
```

Do not leak raw backend errors to users.

## Security

Current routes have no server-to-server authentication.

For the prototype:

- backend-only access;
- no frontend Logic calls;
- request timeout;
- no raw response dumps.

Optional future config placeholder:

`LOGIC_API_TOKEN`

Do not assume the backend currently supports it.

## Tests

Mock HTTP responses and test:

- rates;
- quote;
- rooms;
- opening hours;
- availability;
- closed day;
- missing opening hours;
- invalid date;
- timeout;
- server error;
- cache hit for rooms/rates/opening hours;
- no cache for availability;
- no cache for quote.

## Definition of done

Application code can obtain all required structured Logic information through typed backend functions without LLM involvement.
