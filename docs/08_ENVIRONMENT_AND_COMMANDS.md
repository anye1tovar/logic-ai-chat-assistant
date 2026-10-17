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
LOGIC_API_TIMEOUT_SECONDS=10
LOGIC_REFERENCE_CACHE_TTL_SECONDS=43200

CHROMA_PERSIST_DIRECTORY=.data/chroma
CHROMA_COLLECTION_NAME=logic_knowledge_v1
RAG_MAX_DISTANCE=0.55

# Mutable operational values. Leave blank until configured and verified.
LOGIC_BUSINESS_NAME=
LOGIC_BUSINESS_CITY=
LOGIC_BUSINESS_TIMEZONE=
LOGIC_BUSINESS_ADDRESS=
LOGIC_MAP_URL=
LOGIC_OFFICIAL_WEBSITE_URL=
LOGIC_ESCAPE_ROOM_EXPLAINER_URL=
LOGIC_CAFETERIA_MENU_URL=
LOGIC_PAYMENT_METHOD_FOR_DEPOSITS=
LOGIC_TYPICAL_DEPOSIT_PER_ROOM_COP=
LOGIC_BRE_B_KEY=
LOGIC_NEQUI_TO_BRE_B_TUTORIAL_URL=
LOGIC_BANCOLOMBIA_TO_BRE_B_TUTORIAL_URL=
LOGIC_HUMAN_ATTENTION_TIMEZONE=
LOGIC_HUMAN_ATTENTION_HOURS=
LOGIC_ALTERNATIVE_CONTACT_CHANNEL=
LOGIC_OPERATIONAL_VALUES_VERIFIED=false
```

Los valores de operación se cargan desde el entorno. `config/operational-links.example.yaml` solo documenta el mapeo y mantiene vacíos los valores; no se ingresa a RAG ni contiene secretos o enlaces reales. Exponer cada valor únicamente cuando esté configurado y verificado.

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
