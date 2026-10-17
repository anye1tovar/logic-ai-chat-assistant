import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE = ROOT / "knowledge"
INDEX = KNOWLEDGE / "INDEX.md"
SCHEMA_PATH = ROOT / "config" / "knowledge-schema.json"
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


def _knowledge_files() -> list[Path]:
    return sorted(
        path
        for path in KNOWLEDGE.rglob("*.md")
        if path.name not in {"INDEX.md", "INGESTION.md"}
    )


def _metadata(path: Path) -> dict:
    content = path.read_text(encoding="utf-8")
    assert content.startswith("---\n"), f"Missing YAML front matter: {path}"
    _, front_matter, _body = content.split("---", maxsplit=2)
    result = yaml.safe_load(front_matter)
    assert isinstance(result, dict), f"Invalid front matter: {path}"
    return result


def test_knowledge_front_matter_matches_schema_and_has_unique_ids():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    properties = set(schema["properties"])
    ids = []

    for path in _knowledge_files():
        metadata = _metadata(path)
        assert REQUIRED_METADATA <= metadata.keys(), path
        assert set(metadata) <= properties, path
        assert metadata["source_of_truth"] == "rag"
        assert metadata["validation_status"] in {
            "approved",
            "approved_with_open_issue",
            "pending_validation",
        }
        assert isinstance(metadata["keywords"], list) and metadata["keywords"]
        assert re.fullmatch(r"[a-z0-9]+(?:[._-][a-z0-9]+)*", metadata["id"])
        ids.append(metadata["id"])

    assert len(ids) == len(set(ids))
    assert len(ids) == 14


def test_index_links_resolve_and_list_every_knowledge_document_once():
    index = INDEX.read_text(encoding="utf-8")
    indexed_ids = re.findall(r"`([a-z0-9]+(?:[._-][a-z0-9]+)*)`\s*\|", index)
    indexed_paths = re.findall(r"\]\(([^)]+\.md)\)", index)
    expected = {metadata["id"] for metadata in map(_metadata, _knowledge_files())}

    assert set(indexed_ids) == expected
    assert len(indexed_ids) == len(expected)
    assert len(indexed_paths) == len(set(indexed_paths))
    assert all((KNOWLEDGE / path).is_file() for path in indexed_paths)


def test_indexable_corpus_excludes_dynamic_values_and_payment_identifiers():
    corpus = "\n".join(path.read_text(encoding="utf-8") for path in _knowledge_files())
    for forbidden in (
        "$33.000",
        "$40.000",
        "$50.000",
        "17:00",
        "18:30",
        "19:30",
    ):
        assert forbidden not in corpus


def test_scenario_jsonl_is_valid_and_has_required_fields():
    path = ROOT / "quality" / "rag-scenarios.jsonl"
    required = {
        "id",
        "user_input",
        "context",
        "expected_sources",
        "must_include",
        "must_not_claim",
        "expected_handoff",
        "notes",
    }
    scenarios = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(scenarios) == 34
    assert [scenario["id"] for scenario in scenarios] == [
        f"T{number:02d}" for number in range(1, 35)
    ]
    assert len({scenario["id"] for scenario in scenarios}) == len(scenarios)
    for scenario in scenarios:
        assert required <= scenario.keys()
        assert scenario["expected_sources"]
        assert scenario["must_include"]
        assert scenario["must_not_claim"]
    assert all(not re.search(r"\b\d{10}\b", line) for line in path.read_text(encoding="utf-8").splitlines())


def test_source_policy_and_operational_template_are_valid_yaml():
    source_policy = yaml.safe_load((ROOT / "config" / "source-policy.yaml").read_text(encoding="utf-8"))
    operational = yaml.safe_load(
        (ROOT / "config" / "operational-links.example.yaml").read_text(encoding="utf-8")
    )
    assert {"logic_api", "rag", "operational_config", "agent_policy"} <= source_policy["sources"].keys()
    assert source_policy["sources"]["logic_api"]["cache"]["availability"] is False
    assert source_policy["sources"]["logic_api"]["cache"]["quote"] is False
    assert operational["payments"]["bre_b_key_env"] == "LOGIC_BRE_B_KEY"
    assert operational["payments"]["typical_deposit_per_room_cop"] is None
    assert operational["human_attention"]["verified_for_exposure"] is False
    assert operational["business"]["name"] == ""
    assert operational["business"]["city"] == ""
    assert operational["business"]["timezone"] == ""
    assert operational["business"]["map_url"] == ""
    assert operational["business"]["official_website_url"] == ""
    assert operational["business"]["escape_room_explainer_url"] == ""
    assert operational["human_attention"]["documented_daily_window"] == ""
    assert operational["business"]["address_env"] == "LOGIC_BUSINESS_ADDRESS"
    assert operational["human_attention"]["documented_daily_window_env"] == "LOGIC_HUMAN_ATTENTION_HOURS"
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    for variable in (
        "LOGIC_BUSINESS_NAME",
        "LOGIC_BUSINESS_ADDRESS",
        "LOGIC_MAP_URL",
        "LOGIC_OFFICIAL_WEBSITE_URL",
        "LOGIC_ESCAPE_ROOM_EXPLAINER_URL",
        "LOGIC_CAFETERIA_MENU_URL",
        "LOGIC_TYPICAL_DEPOSIT_PER_ROOM_COP",
        "LOGIC_BRE_B_KEY",
        "LOGIC_HUMAN_ATTENTION_HOURS",
        "LOGIC_ALTERNATIVE_CONTACT_CHANNEL",
    ):
        assert f"{variable}=\n" in env_example


def test_policy_smoke_queries_have_relevant_terms_in_expected_documents():
    expected_queries = {
        "somos 10": {
            "policies.groups-and-special-pricing": ["grupos de siete", "varias salas", "tramo de siete"]
        },
        "somos 2 para Caníbal": {
            "policies.minors-and-room-limits": ["mínimo", "adulto"],
            "recommendations.room-difficulty-and-intensity": ["Caníbal"]
        },
        "abono menor": {
            "policies.deposits-and-payments": ["abono", "excepciones", "equipo"]
        },
        "cumpleaños": {
            "experience.birthdays-and-cafeteria": ["cumpleaños", "cafetería", "torta"]
        },
        "niños": {
            "policies.minors-and-room-limits": ["niños", "acompañantes", "Portal"]
        },
    }
    contents = {
        _metadata(path)["id"]: path.read_text(encoding="utf-8").casefold()
        for path in _knowledge_files()
    }
    for query, target_documents in expected_queries.items():
        assert query
        for document_id, terms in target_documents.items():
            assert all(term.casefold() in contents[document_id] for term in terms)
