# Environment Variables and Suggested Local Commands

## Environment variables

Suggested `.env` entries:

```env
APP_ENV=local
LOG_LEVEL=INFO

OPENAI_API_KEY=
OPENAI_MODEL=
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
OPENAI_CHAT_MAX_OUTPUT_TOKENS=400

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

El backend expone `POST /api/chat` con un cuerpo `{ "message": "..." }` y responde `{ "answer": "..." }`. El endpoint requiere `OPENAI_API_KEY` (también acepta `LOGIC_OPENAI_API_KEY`) y `OPENAI_MODEL`. Las consultas estructuradas requieren además `LOGIC_API_BASE_URL`. El selector del modelo solo puede escoger una ruta de lectura permitida; el backend valida los argumentos y ejecuta API/RAG. No se crean reservas.

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

```bash
python -m app.rag.ingest
```

## Chat API

Desde `backend/`, inicia el servidor con `uvicorn app.main:app --reload` y envía un `POST` a `http://127.0.0.1:8000/api/chat`:

```json
{"message":"¿Qué salas tienen?"}
```

`OPENAI_MODEL` no tiene un valor predeterminado intencional: configúralo en `.env` para el modelo de chat habilitado en tu cuenta.

## Evaluation

Target command:

```bash
python -m app.evaluation.run --dataset ../evaluation/cases.json
```

These are target conventions; Codex may adjust them if the final structure differs.
