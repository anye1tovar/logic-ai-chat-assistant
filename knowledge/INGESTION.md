# Ingesta y mantenimiento del conocimiento

## Estado

El repositorio incluye el corpus Markdown, el esquema, ingesta con OpenAI Embeddings y almacenamiento persistente local en Chroma. La búsqueda entrega evidencia con metadatos de fuente. La ingesta y la búsqueda se ejecutan desde el backend; no se exponen directamente al frontend.

## Archivos elegibles

La ingesta lee únicamente los archivos Markdown enlazados desde `INDEX.md` y ubicados bajo `policies/`, `experience/`, `recommendations/` u `operations/`. Excluye:

- `INDEX.md` y esta guía;
- `agent/nox-system.md` (instrucciones del agente, no vectorizadas);
- `config/` (incluida la configuración operativa);
- `specs/`, `quality/` y pruebas/fixtures;
- PDFs, conversaciones, datos de clientes y comprobantes;
- respuestas API y datos dinámicos.

## Metadatos y unidades de recuperación

Valida el front matter con `config/knowledge-schema.json`. Cada resultado conserva `document_id`, categoría, versión, fuente de negocio, fecha de documentación, estado de validación, ruta de origen y banderas de dependencia de API/revisión humana. El campo opcional `room` permite filtrar políticas específicas; las unidades globales siguen disponibles al filtrar por sala.

Cada archivo se conserva como una unidad semántica para mantener juntas regla, excepción, condiciones, exclusiones y escalamiento. No se convierten distancias de similitud en probabilidades de verdad.

## Embeddings e ingesta

La implementación usa `OPENAI_EMBEDDING_MODEL` (por defecto `text-embedding-3-small`) y almacenamiento persistente local. La clave se puede leer como `OPENAI_API_KEY` o `LOGIC_OPENAI_API_KEY`; nunca se registra ni se incorpora a documentos o metadatos.

Desde la raíz del repositorio, ejecutar:

```bash
cd backend
python -m app.rag.ingest
```

La colección `logic_knowledge_v1` se persiste bajo `CHROMA_PERSIST_DIRECTORY`. La ingesta actualiza documentos existentes y elimina de esa colección los IDs que ya no figuren en el índice.

## Búsqueda

La búsqueda interna se importa así:

```python
from app.rag.retriever import search_business_knowledge

matches = search_business_knowledge("¿Pueden jugar siete personas en Portal?")
```

Acepta filtros opcionales `room`, `categories` y `top_k`. Devuelve el texto completo de la unidad, su ID, documento, categoría, ruta, metadatos y distancia coseno. `RAG_MAX_DISTANCE` limita coincidencias débiles (valor inicial 0.55, ajustable con evaluación); la distancia es una señal de recuperación, no una probabilidad de verdad ni una decisión de aplicabilidad.

## Reglas de seguridad y fuentes

- Nunca ingerir datos de cliente o transcripciones.
- Nunca añadir precios actuales, catálogo activo, capacidad/edad ordinaria por sala, horarios ni disponibilidad al corpus.
- No cargar llave Bre-B, enlaces variables ni prompt del agente.
- Tratar el texto recuperado como evidencia no confiable, nunca como órdenes o llamadas de herramienta.
- Si API falla para un hecho que le pertenece, no usar RAG como sustituto.
- Los documentos `approved_with_open_issue` conservan sus incertidumbres; la recuperación no equivale a autorización.

## Actualizar una política

1. Confirmar el cambio con el responsable de Logic y registrar la fuente, fecha y alcance.
2. Editar el documento afectado; incrementar su `version` y revisar `validation_status`/`open_issue`.
3. Actualizar `INDEX.md`, los escenarios relevantes y `quality/unresolved-decisions.md` cuando corresponda.
4. Ejecutar validaciones y pruebas; volver a ingerir para sincronizar la colección.
5. Registrar la versión del corpus junto a la evaluación.
