import pytest

from app.core.config import Settings
from app.rag.ingest import KNOWLEDGE_ROOT, SCHEMA_PATH, load_knowledge_documents
from app.rag.ingest import ingest_knowledge
from app.rag.models import KnowledgeDocument
from app.rag.retriever import search_business_knowledge


class FixedEmbedder:
    def embed(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]


class FixedCollection:
    def __init__(self, *, ids, documents, metadatas, distances):
        self.response = {
            "ids": [ids],
            "documents": [documents],
            "metadatas": [metadatas],
            "distances": [distances],
        }
        self.where = None

    def query(self, **kwargs):
        self.where = kwargs["where"]
        if not self.where:
            return self.response

        def matches(expression, metadata):
            if "$and" in expression:
                return all(matches(clause, metadata) for clause in expression["$and"])
            if "$or" in expression:
                return any(matches(clause, metadata) for clause in expression["$or"])
            for key, expected in expression.items():
                if isinstance(expected, dict) and "$in" in expected:
                    if metadata.get(key) not in expected["$in"]:
                        return False
                elif metadata.get(key) != expected:
                    return False
            return True

        if not matches(self.where, self.response["metadatas"][0][0]):
            return {key: [[]] for key in self.response}
        return self.response


def _portal_result(text: str = "# Excepción Portal\n\n## Condiciones\nHasta siete contando al adulto.\n\n## No aplica\nNo aplica a otras salas."):
    return FixedCollection(
        ids=["policies.minors-and-room-limits:v1"],
        documents=[text],
        metadatas=[
            {
                "document_id": "policies.minors-and-room-limits",
                "category": "age_policy",
                "source_path": "policies/minors-and-room-limits.md",
                "validation_status": "approved",
                "room": "portal",
            }
        ],
        distances=[0.2],
    )


def test_ingest_loader_reads_only_indexed_knowledge_and_keeps_semantic_units():
    documents = load_knowledge_documents(KNOWLEDGE_ROOT, SCHEMA_PATH)

    assert len(documents) == 14
    portal = next(doc for doc in documents if doc.document_id == "policies.minors-and-room-limits")
    assert "No aplica" in portal.text
    assert "Escalamiento" in portal.text
    assert portal.metadata["room"] == "portal"
    assert portal.metadata["source_path"] == "policies/minors-and-room-limits.md"


def test_retriever_returns_applicable_exception_with_source_metadata():
    collection = _portal_result()
    results = search_business_knowledge(
        "¿Portal acepta siete con menores y un adulto?",
        room="Portal",
        categories=["age_policy"],
        settings=Settings(_env_file=None),
        embedder=FixedEmbedder(),
        collection=collection,
    )

    assert len(results) == 1
    assert results[0].document_id == "policies.minors-and-room-limits"
    assert results[0].source_path == "policies/minors-and-room-limits.md"
    assert results[0].distance == pytest.approx(0.2)
    assert "No aplica a otras salas" in results[0].text
    assert collection.where == {
        "$and": [
            {"$or": [{"room": "portal"}, {"room": "__all__"}]},
            {"category": {"$in": ["age_policy"]}},
        ]
    }


def test_room_filter_excludes_portal_exception_for_a_different_room():
    collection = _portal_result()
    results = search_business_knowledge(
        "¿La excepción de siete personas también aplica en Caníbal?",
        room="Caníbal",
        settings=Settings(_env_file=None),
        embedder=FixedEmbedder(),
        collection=collection,
    )

    assert results == []
    assert collection.where == {"$or": [{"room": "caníbal"}, {"room": "__all__"}]}


def test_irrelevant_high_distance_match_is_not_returned_as_evidence():
    collection = _portal_result()
    collection.response["distances"] = [[0.95]]
    results = search_business_knowledge(
        "¿Cómo puedo pagar el estacionamiento del aeropuerto?",
        settings=Settings(_env_file=None, rag_max_distance=0.55),
        embedder=FixedEmbedder(),
        collection=collection,
    )

    assert results == []


def test_retriever_validates_query_and_top_k():
    with pytest.raises(ValueError, match="query must not be empty"):
        search_business_knowledge(" ", embedder=FixedEmbedder(), collection=_portal_result())
    with pytest.raises(ValueError, match="top_k"):
        search_business_knowledge("consulta", top_k=0, embedder=FixedEmbedder(), collection=_portal_result())


def test_settings_accepts_project_openai_key_environment_name(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("LOGIC_OPENAI_API_KEY", "test-key")
    settings = Settings(_env_file=None)

    assert settings.openai_api_key == "test-key"


def test_chroma_persists_documents_and_retrieves_traceable_metadata(tmp_path):
    chromadb = pytest.importorskip("chromadb")

    class PortalEmbedder:
        def embed(self, texts):
            return [[1.0, 0.0] if "portal" in text.casefold() else [0.0, 1.0] for text in texts]

    settings = Settings(
        _env_file=None,
        chroma_persist_directory=tmp_path / "chroma",
        chroma_collection_name="rag_test",
        rag_max_distance=0.2,
    )
    docs = [
        KnowledgeDocument(
            document_id="policies.portal-test",
            text="# Portal exception\n\nUp to seven participants counting the adult. Not other rooms.",
            metadata={
                "document_id": "policies.portal-test",
                "category": "age_policy",
                "kind": "policy",
                "source_path": "policies/portal-test.md",
                "version": 1,
                "business_source": "approved test fixture",
                "documented_at": "2026-10-17",
                "validation_status": "approved",
                "source_of_truth": "rag",
                "requires_api_data": True,
                "requires_human_for_exceptions": True,
                "room": "portal",
            },
        )
    ]
    embedder = PortalEmbedder()

    assert ingest_knowledge(settings=settings, documents=docs, embedder=embedder) == 1
    client = chromadb.PersistentClient(path=str(settings.chroma_persist_directory))
    collection = client.get_collection(settings.chroma_collection_name)
    assert collection.count() == 1

    results = search_business_knowledge(
        "Can seven people use Portal?",
        room="Portal",
        categories=["age_policy"],
        settings=settings,
        embedder=embedder,
    )

    assert len(results) == 1
    assert results[0].source_path == "policies/portal-test.md"
    assert results[0].metadata["validation_status"] == "approved"
    assert "Not other rooms" in results[0].text

