"""Validate, embed, and persist the approved Markdown knowledge corpus."""

import json
import re
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker

from app.core.config import Settings, get_settings
from app.rag.embeddings import OpenAIEmbedder
from app.rag.models import KnowledgeDocument

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
KNOWLEDGE_ROOT = REPOSITORY_ROOT / "knowledge"
SCHEMA_PATH = REPOSITORY_ROOT / "config" / "knowledge-schema.json"
INDEXED_PATH_PATTERN = re.compile(
    r"^\|\s*`[^`]+`\s*\|\s*`([^`]+\.md)`\s*\|",
    re.MULTILINE,
)
REQUIRED_METADATA = {
    "id",
    "version",
    "kind",
    "category",
    "source_of_truth",
    "business_source",
    "documented_at",
    "validation_status",
    "requires_api_data",
    "requires_human_for_exceptions",
    "keywords",
}
ALLOWED_KNOWLEDGE_DIRECTORIES = {"policies", "experience", "recommendations", "operations"}


def _parse_markdown(path: Path) -> tuple[dict[str, Any], str]:
    content = path.read_text(encoding="utf-8")
    if not content.startswith("---\n"):
        raise ValueError(f"Knowledge document is missing YAML front matter: {path}")
    try:
        _opening, raw_metadata, body = content.split("---", maxsplit=2)
    except ValueError as exc:
        raise ValueError(f"Knowledge document has incomplete front matter: {path}") from exc
    metadata = yaml.safe_load(raw_metadata)
    if not isinstance(metadata, dict):
        raise ValueError(f"Knowledge front matter must be a YAML mapping: {path}")
    return metadata, body.strip()


def load_knowledge_documents(
    knowledge_root: Path = KNOWLEDGE_ROOT,
    schema_path: Path = SCHEMA_PATH,
) -> list[KnowledgeDocument]:
    """Load exactly the Markdown files linked from INDEX.md and validate metadata."""
    index_path = knowledge_root / "INDEX.md"
    index = index_path.read_text(encoding="utf-8")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    properties = set(schema["properties"])
    documents: list[KnowledgeDocument] = []
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()

    for indexed_path in INDEXED_PATH_PATTERN.findall(index):
        relative = Path(indexed_path)
        if (
            relative.is_absolute()
            or len(relative.parts) != 2
            or relative.parts[0] not in ALLOWED_KNOWLEDGE_DIRECTORIES
            or relative.suffix.casefold() != ".md"
        ):
            raise ValueError(f"INDEX.md contains a path outside the knowledge corpus: {indexed_path}")
        path = (knowledge_root / relative).resolve()
        if not path.is_relative_to(knowledge_root.resolve()):
            raise ValueError(f"Knowledge path escapes the corpus directory: {indexed_path}")
        normalized_path = relative.as_posix()
        if normalized_path in seen_paths:
            raise ValueError(f"INDEX.md lists a knowledge document more than once: {indexed_path}")
        seen_paths.add(normalized_path)
        if not path.is_file():
            raise ValueError(f"INDEX.md references a missing knowledge document: {indexed_path}")

        raw_metadata, body = _parse_markdown(path)
        missing = REQUIRED_METADATA - raw_metadata.keys()
        extra = raw_metadata.keys() - properties
        if missing or extra:
            raise ValueError(
                f"Invalid metadata in {indexed_path}; missing={sorted(missing)}, extra={sorted(extra)}"
            )
        errors = sorted(validator.iter_errors(raw_metadata), key=lambda error: list(error.path))
        if errors:
            error = errors[0]
            raise ValueError(f"Invalid metadata in {indexed_path}: {error.message}")
        document_id = raw_metadata["id"]
        if document_id in seen_ids:
            raise ValueError(f"Duplicate knowledge document id: {document_id}")
        if raw_metadata["source_of_truth"] != "rag":
            raise ValueError(f"Knowledge source_of_truth must be rag: {indexed_path}")
        if raw_metadata["validation_status"] not in {
            "approved",
            "approved_with_open_issue",
            "pending_validation",
        }:
            raise ValueError(f"Invalid validation_status in {indexed_path}")
        if not body:
            raise ValueError(f"Knowledge document has no body: {indexed_path}")
        seen_ids.add(document_id)

        # Keep the entire policy file as one semantic unit so conditions and
        # escalation guidance cannot be separated into misleading fragments.
        metadata: dict[str, str | int | bool] = {
            "document_id": document_id,
            "category": str(raw_metadata["category"]),
            "kind": str(raw_metadata["kind"]),
            "source_path": normalized_path,
            "version": int(raw_metadata["version"]),
            "business_source": str(raw_metadata["business_source"]),
            "documented_at": str(raw_metadata["documented_at"]),
            "validation_status": str(raw_metadata["validation_status"]),
            "source_of_truth": "rag",
            "requires_api_data": bool(raw_metadata["requires_api_data"]),
            "requires_human_for_exceptions": bool(
                raw_metadata["requires_human_for_exceptions"]
            ),
            "room": str(raw_metadata.get("room") or "__all__").casefold(),
        }
        documents.append(KnowledgeDocument(document_id, body, metadata))

    if not documents:
        raise ValueError("INDEX.md does not list any eligible knowledge documents.")
    return documents


def _get_collection(settings: Settings):
    import chromadb

    settings.chroma_persist_directory.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(settings.chroma_persist_directory))
    collection = client.get_or_create_collection(
        name=settings.chroma_collection_name,
        metadata={"hnsw:space": "cosine"},
    )
    return client, collection


def ingest_knowledge(
    *,
    settings: Settings | None = None,
    documents: list[KnowledgeDocument] | None = None,
    embedder: OpenAIEmbedder | None = None,
    collection: Any | None = None,
) -> int:
    """Synchronize approved index documents into the persistent Chroma collection."""
    settings = settings or get_settings()
    documents = documents if documents is not None else load_knowledge_documents()
    embedder = embedder or OpenAIEmbedder(settings)
    if collection is None:
        _chroma_client, collection = _get_collection(settings)

    ids = [f"{doc.document_id}:v{doc.metadata['version']}" for doc in documents]
    embeddings = embedder.embed([doc.text for doc in documents])
    if len(embeddings) != len(documents):
        raise RuntimeError("Embedding provider returned a different number of vectors than inputs.")

    existing = collection.get(include=[])
    stale_ids = sorted(set(existing.get("ids", [])) - set(ids))
    if stale_ids:
        collection.delete(ids=stale_ids)
    collection.upsert(
        ids=ids,
        documents=[doc.text for doc in documents],
        metadatas=[doc.metadata for doc in documents],
        embeddings=embeddings,
    )
    return len(documents)


def main() -> None:
    count = ingest_knowledge()
    print(f"Ingested {count} Logic knowledge documents into the local Chroma collection.")


if __name__ == "__main__":
    main()
