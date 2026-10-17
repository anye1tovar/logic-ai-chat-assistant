from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class KnowledgeDocument:
    document_id: str
    text: str
    metadata: dict[str, str | int | bool]


@dataclass(frozen=True)
class KnowledgeSearchResult:
    chunk_id: str
    document_id: str
    category: str
    text: str
    source_path: str
    metadata: dict[str, Any]
    distance: float | None
