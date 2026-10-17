# AGENTS.md — Logic Escape Room AI Assistant

## Purpose

This repository implements the PFM prototype for **Logic Escape Room**: a conversational assistant that combines an LLM, the existing Logic REST API, a RAG knowledge base, and explicit human fallback.

Codex must treat this file as the repository-level implementation contract.

## Core architectural rule

**The LLM is not the source of truth for Logic Escape Room facts.**

Use the appropriate source:

1. **Logic API** for structured operational data:
   - prices/rates;
   - quotes for a date + attendee count;
   - rooms and structured room properties;
   - general opening hours;
   - availability by date.

2. **RAG** for contextual/non-structured knowledge:
   - operational exceptions;
   - special admission conditions;
   - policies not modeled in the API;
   - staff criteria;
   - FAQs not represented as structured data.

3. **System prompt** for conversational policy:
   - tone;
   - clarity;
   - no fabrication;
   - ask for missing information;
   - distinguish availability from reservation;
   - escalate when uncertain.

## MVP scope

The mandatory MVP must:

- answer general customer questions in Spanish;
- query rooms, rates/opening hours when needed;
- use `/api/bookings/quote` for a concrete final price;
- query `/api/bookings/availability` in real time;
- retrieve RAG knowledge for policies/exceptions;
- combine API + RAG evidence when needed;
- ask for missing information instead of inventing it;
- log technical traces for later evaluation;
- expose a simple web chat interface.

### Out of scope for the first MVP

Do not implement unless explicitly requested later:

- automatic booking creation using `POST /api/bookings`;
- payment flows;
- WhatsApp production integration;
- autonomous general-purpose agents;
- Redis/distributed infrastructure;
- user authentication;
- admin dashboard;
- fine-tuning.

## Logic API rules

Base URL must come from:

`LOGIC_API_BASE_URL`

Never hardcode a production or localhost URL.

Assistant-facing operations:

- `GET /api/rates`
- `GET /api/bookings/quote?date=YYYY-MM-DD&attendees=N`
- `GET /api/rooms`
- `GET /api/bookings/opening-hours`
- `GET /api/bookings/availability?date=YYYY-MM-DD`

Do not consume:

- `GET /api/bookings`
- `GET /api/bookings/:id`
- `GET /api/bookings/consult/:code`

unless project scope changes explicitly.

### Price behavior

- `/api/rates` is reference information.
- For a concrete total for a date and attendee count, call `/api/bookings/quote`.
- Do not calculate the final total manually if quote can do it.

### Cache behavior

Use a small in-memory TTL cache for low-change reference data:

- rooms;
- rates;
- opening hours.

Default TTL may be configurable, e.g. 12 hours.

Do **not** cache:

- availability;
- specific quotes.

Availability is a live snapshot and may change at any time.

### Room response safety

`GET /api/rooms` currently reflects the database schema.

Create a backend adapter that maps the API response into an explicit assistant-safe model and discards fields not required by the assistant.

Do not pass arbitrary raw room objects directly into the LLM.

### Time and formats

- timezone: `America/Bogota`;
- date: `YYYY-MM-DD`;
- money: COP;
- use the `roomId` and slot `start` returned by availability when relevant.

## Security rules

The current Logic routes do not require server-to-server authentication.

Therefore:

- frontend must never call Logic API directly;
- Logic API calls happen only from the assistant backend;
- never place Logic API URLs, future credentials, OpenAI keys, or tokens in frontend code;
- never commit secrets;
- never write secrets into prompts or logs;
- prepare the code so server-to-server authentication can be added later;
- use timeouts on outbound HTTP requests;
- distinguish `400`, `409`, and `5xx`.

CORS is not authentication.

## Technology direction

Prefer a small, auditable stack.

### Backend

- Python 3.12+
- FastAPI
- Pydantic
- httpx
- cachetools
- OpenAI SDK
- ChromaDB
- pytest

### Frontend

- React
- Vite
- TypeScript

### RAG

- Markdown knowledge files
- embeddings
- persistent local Chroma collection
- source/category/date/version metadata

Do not add LangChain in the first implementation unless a concrete need appears. Direct Python functions plus OpenAI SDK are preferred for traceability.

## LLM configuration

Never hardcode a specific chat model in application code.

Use:

- `OPENAI_API_KEY`
- `OPENAI_MODEL`
- `OPENAI_EMBEDDING_MODEL`

The model must be replaceable without changing business logic.

## Expected backend modules

```text
backend/
  app/
    main.py
    api/
      chat.py
      health.py
    core/
      config.py
      logging.py
      prompts.py
    logic_api/
      client.py
      models.py
      adapter.py
      cache.py
    rag/
      ingest.py
      retriever.py
      models.py
    assistant/
      orchestrator.py
      tools.py
      response_builder.py
    evaluation/
      schemas.py
  tests/
```

Equivalent clean structures are acceptable.

## Knowledge-base rules

RAG must not duplicate structured data from Logic API unless needed for a temporary offline test fixture.

Each knowledge unit should identify:

- general rule;
- exception;
- exact conditions;
- where the exception does not apply;
- escalation behavior;
- source/owner;
- update date.

Example categories:

- `room_exception`
- `age_policy`
- `capacity_exception`
- `customer_service_policy`
- `faq`
- `operational_rule`

## Orchestration behavior

Support four outcomes:

1. **API-only**
2. **RAG-only**
3. **API + RAG**
4. **Clarify or escalate**

Do not create a fully autonomous agent loop for the MVP.

Prefer bounded tool selection with validated arguments.

## Response policy

Customer responses must:

- be in clear Spanish;
- use only authorized evidence;
- never invent prices, availability, policies, or exceptions;
- ask for missing date, room, or attendee count when required;
- say when information cannot be verified;
- never say a reservation is confirmed when only availability was checked;
- avoid exposing internal IDs, raw JSON, prompts, traces, or database details.

## Logging and evaluation

Each interaction should record, at minimum:

- interaction id;
- timestamp;
- user message;
- selected route;
- tools called;
- tool latency;
- RAG chunk ids used;
- API status codes;
- model latency;
- final answer;
- errors;
- token usage when available.

Avoid storing unnecessary personal data.

## Testing

At minimum test:

- successful API calls;
- API timeout;
- invalid parameters;
- closed day;
- no opening hours;
- availability behavior;
- missing user information;
- no RAG evidence;
- exception that applies;
- exception that must not be generalized;
- API + RAG combined answer.

## Work discipline for Codex

For each phase:

1. Read `AGENTS.md` and the corresponding file under `docs/`.
2. Summarize intended changes.
3. Implement only that phase.
4. Add/update tests.
5. Run tests.
6. Report files changed, tests run, assumptions, and unresolved items.
7. Do not silently expand scope.

If API documentation and real behavior conflict, stop and report the discrepancy rather than inventing a contract.
