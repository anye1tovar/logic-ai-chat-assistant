# Environment Variables and Suggested Local Commands

## Environment variables

Suggested `.env` entries:

```env
APP_ENV=local
LOG_LEVEL=INFO

OPENAI_API_KEY=
OPENAI_MODEL=
# Set to "none" for GPT-6 Luna function calls through Chat Completions.
OPENAI_REASONING_EFFORT=none
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

El backend expone `POST /api/chat` con un cuerpo `{ "message": "..." }` y responde `{ "answer": "..." }`. El endpoint requiere `OPENAI_API_KEY` (también acepta `LOGIC_OPENAI_API_KEY`) y `OPENAI_MODEL`. Para GPT-6 Luna en el selector de rutas, configura `OPENAI_REASONING_EFFORT=none`; otros modelos pueden requerir un esfuerzo distinto o no admitir ese parámetro. Las consultas estructuradas requieren además `LOGIC_API_BASE_URL`. El selector del modelo solo puede escoger una ruta de lectura permitida; el backend valida los argumentos y ejecuta API/RAG. No se crean reservas.

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

Inicia primero el backend con `uvicorn app.main:app --reload` desde `backend/`. En desarrollo, Vite reenvía `/api/*` a `http://127.0.0.1:8000`; puedes cambiar ese destino con `VITE_BACKEND_PROXY_TARGET` en `frontend/.env.local`. En despliegue, configura el servidor web para reenviar `/api/*` al backend. El navegador solo solicita `/api/chat`; no necesita la URL de Logic ni credenciales.

El chat mantiene el transcript en memoria durante la sesión y envía hasta ocho mensajes anteriores como contexto conversacional. El backend usa ese historial para resolver referencias, pero no como evidencia para datos del negocio.

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

## Security and privacy before deployment

The browser sends the current message and up to eight previous transcript messages to the assistant backend. The backend may send this context to the configured model provider. Reservation conversations can contain names and phone numbers; use synthetic data during evaluation and define consent, retention, deletion and privacy notice procedures before real customer use.

The prototype has no user authentication or request rate limiting, and the Logic API has no server-to-server authentication. Keep it behind appropriate access controls and traffic limits until those protections exist. CORS is not authentication. The backend keeps secrets in environment configuration; the frontend only needs the same-origin `/api/chat` route. See `docs/07_PHASE_HARDENING.md` for the completed review and detailed production gaps.
