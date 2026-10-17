# Environment Variables and Suggested Local Commands

## Environment variables

Suggested `.env` entries:

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

Optional future variable:

```env
LOGIC_API_TOKEN=
```

Do not use it until the Logic backend supports assistant authentication.

## Backend local workflow

Example:

```bash
cd backend
python -m venv .venv
```

After activation and dependency installation:

```bash
uvicorn app.main:app --reload
```

Tests:

```bash
pytest
```

## Frontend local workflow

```bash
cd frontend
npm install
npm run dev
```

## RAG ingestion

Target command:

```bash
python -m app.rag.ingest
```

## Evaluation

Target command:

```bash
python -m app.evaluation.run --dataset ../evaluation/cases.json
```

These are target conventions; Codex may adjust them if the final structure differs.
