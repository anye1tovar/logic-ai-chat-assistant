# Logic Escape Room — AI Conversational Assistant

Repository documentation for the PFM prototype.

## Development order

1. `docs/01_PHASE_BOOTSTRAP.md`
2. `docs/02_PHASE_LOGIC_API.md`
3. `docs/03_PHASE_RAG.md`
4. `docs/04_PHASE_ORCHESTRATION.md`
5. `docs/05_PHASE_FRONTEND.md`
6. `docs/06_PHASE_EVALUATION.md`
7. `docs/07_PHASE_HARDENING.md`

Read `AGENTS.md` before implementing anything.

## Architecture summary

- **Logic API**: source of truth for structured operational data.
- **RAG**: contextual policies, exceptions and non-structured knowledge.
- **LLM**: interpretation and natural-language generation.
- **Human fallback**: when evidence is insufficient.

### Cache

Cache with configurable TTL:

- rooms;
- rates;
- opening hours.

Do not cache:

- availability;
- specific quotes.

## MVP boundary

The first MVP does not create reservations.

See `docs/USER_SETUP_CHECKLIST.md` for the project-owner tasks.

## Conocimiento y políticas de Nox

El corpus documental, su índice y el pipeline de ingesta/búsqueda están en [`knowledge/`](knowledge/INDEX.md) y `backend/app/rag/`. El prompt del agente está separado en [`agent/nox-system.md`](agent/nox-system.md); la política de fuentes y la plantilla operativa no indexable están en `config/`. Los escenarios, criterios de aceptación y pendientes de integración están en `quality/`.

La Fase 3 usa OpenAI Embeddings y una colección persistente local de Chroma. Para sincronizar el corpus, configura `OPENAI_API_KEY` (o `LOGIC_OPENAI_API_KEY`) en el `.env` local y ejecuta desde `backend/`:

```bash
python -m app.rag.ingest
```

La búsqueda interna está disponible mediante `app.rag.retriever.search_business_knowledge`; sus resultados conservan ruta y metadatos de origen.

## Fase 1: inicio local

Requisitos: Python 3.12 o superior y Node.js 20 o superior.

### Backend

```bash
cd backend
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
uvicorn app.main:app --reload
```

La comprobación inicial está disponible en `GET http://127.0.0.1:8000/health`.
Para ejecutarla con pytest, desde `backend/`:

```bash
pytest
```

### Frontend

En otra terminal, desde `frontend/`:

```bash
npm install
npm run dev
```

Copia `.env.example` como `.env` en la raíz cuando vayas a configurar valores locales.
No agregues `.env` al repositorio.
