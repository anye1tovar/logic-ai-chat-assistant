# Phase 1 — Repository Bootstrap and Technical Skeleton

## Goal

Create a stable project structure without business logic.

## Deliverables

- backend project;
- frontend project;
- environment configuration;
- health endpoint;
- tests;
- logging baseline.

## Proposed structure

```text
/
  AGENTS.md
  README.md
  docs/
  backend/
    app/
      main.py
      api/
      core/
      logic_api/
      rag/
      assistant/
      evaluation/
    tests/
    pyproject.toml
  frontend/
    src/
    package.json
  knowledge/
  evaluation/
  .env.example
```

## Backend stack

Use:

- Python 3.12+
- FastAPI
- Pydantic / pydantic-settings
- httpx
- pytest

Add later:

- OpenAI SDK
- ChromaDB
- cachetools

## Frontend stack

Use:

- React
- Vite
- TypeScript

Only a placeholder page is needed in this phase.

## Environment variables

Prepare `.env.example`:

```env
APP_ENV=local
LOG_LEVEL=INFO

OPENAI_API_KEY=
OPENAI_MODEL=
OPENAI_EMBEDDING_MODEL=text-embedding-3-small

LOGIC_API_BASE_URL=
LOGIC_REFERENCE_CACHE_TTL_SECONDS=43200

CHROMA_PERSIST_DIRECTORY=.data/chroma
```

Never commit the real `.env`.

## Health endpoint

Implement:

`GET /health`

Expected response:

```json
{"status":"ok"}
```

## Configuration

All runtime configuration must live in one typed configuration module.

## Logging baseline

Do not log:

- API keys;
- tokens;
- full environment;
- personal data.

## Tests

At minimum:

- app starts;
- `/health` returns 200.

## Definition of done

- backend starts locally;
- frontend starts locally;
- tests pass;
- secrets excluded from git;
- clean module separation exists.

## Codex instruction

Do not implement Logic API integration, RAG or LLM calls yet.
