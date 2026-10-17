"""Bounded semantic retrieval over the persistent Logic knowledge collection."""

from typing import Any

from app.core.config import Settings, get_settings
from app.rag.embeddings import OpenAIEmbedder
from app.rag.ingest import _get_collection
from app.rag.models import KnowledgeSearchResult


def _build_where(
    room: str | None,
    categories: list[str] | None,
) -> dict[str, Any] | None:
    clauses: list[dict[str, Any]] = []
    if room:
        room_value = room.casefold().strip()
        clauses.append(
            {"$or": [{"room": room_value}, {"room": "__all__"}]}
        )
    if categories:
        normalized = sorted({category.strip() for category in categories if category.strip()})
        if normalized:
            clauses.append({"category": {"$in": normalized}})
    if not clauses:
        return None
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}


def search_business_knowledge(
    query: str,
    room: str | None = None,
    categories: list[str] | None = None,
    top_k: int = 4,
    *,
    settings: Settings | None = None,
    embedder: OpenAIEmbedder | None = None,
    collection: Any | None = None,
) -> list[KnowledgeSearchResult]:
    """Return traceable policy evidence; callers decide whether it applies."""
    if not query or not query.strip():
        raise ValueError("query must not be empty")
    if top_k < 1 or top_k > 20:
        raise ValueError("top_k must be between 1 and 20")

    settings = settings or get_settings()
    embedder = embedder or OpenAIEmbedder(settings)
    if collection is None:
        _chroma_client, collection = _get_collection(settings)

    query_embedding = embedder.embed([query.strip()])[0]
    if not query_embedding:
        raise RuntimeError("Embedding provider returned an empty query vector.")
    response = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        where=_build_where(room, categories),
        include=["documents", "metadatas", "distances"],
    )
    ids = response.get("ids", [[]])[0]
    texts = response.get("documents", [[]])[0]
    metadatas = response.get("metadatas", [[]])[0]
    distances = response.get("distances", [[]])[0]
    results = [
        KnowledgeSearchResult(
            chunk_id=chunk_id,
            document_id=str(metadata["document_id"]),
            category=str(metadata["category"]),
            text=text,
            source_path=str(metadata["source_path"]),
            metadata=metadata,
            distance=float(distances[index]) if index < len(distances) else None,
        )
        for index, (chunk_id, text, metadata) in enumerate(zip(ids, texts, metadatas, strict=False))
        if index >= len(distances) or float(distances[index]) <= settings.rag_max_distance
    ]
    return results
