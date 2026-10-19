import json
from collections import Counter
from pathlib import Path

import pytest

from app.evaluation.run import _summary
from app.evaluation.schemas import EvaluationDataset


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_evaluation_dataset_has_40_valid_unique_cases_balanced_by_category():
    payload = json.loads((REPOSITORY_ROOT / "evaluation" / "cases.json").read_text(encoding="utf-8"))
    dataset = EvaluationDataset.model_validate(payload)
    dataset.validate_unique_ids()

    assert len(dataset.cases) == 40
    assert Counter(case.category for case in dataset.cases) == {
        "general_structured": 10,
        "room_price_conditions": 10,
        "availability_quote": 10,
        "ambiguous_unsupported_exception": 10,
    }


def test_evaluation_dataset_rejects_duplicate_case_ids():
    payload = {
        "dataset_version": "test",
        "description": "duplicate ids",
        "cases": [
            {
                "id": "DUP", "category": "general_structured", "question": "a",
                "expected_route": "get_rooms", "expected_behavior": "b",
                "reference_answer_or_criteria": ["c"], "should_answer": True,
            },
            {
                "id": "DUP", "category": "general_structured", "question": "d",
                "expected_route": "get_rooms", "expected_behavior": "e",
                "reference_answer_or_criteria": ["f"], "should_answer": True,
            },
        ],
    }
    dataset = EvaluationDataset.model_validate(payload)

    with pytest.raises(ValueError, match="unique"):
        dataset.validate_unique_ids()


def test_evaluation_summary_reports_repeatable_metrics_and_leaves_manual_scores_blank():
    payload = json.loads((REPOSITORY_ROOT / "evaluation" / "cases.json").read_text(encoding="utf-8"))
    dataset = EvaluationDataset.model_validate(payload)
    records = [
        {
            "route_correct": True, "source_correct": True, "error": None, "trace_errors": [],
            "end_to_end_latency_seconds": 1.0,
            "manual_review": {"faithfulness": None, "relevance": None,
                              "unsupported_factual_claim": None, "correct_abstention": None, "notes": None},
        },
        {
            "route_correct": False, "source_correct": False, "error": None, "trace_errors": [],
            "end_to_end_latency_seconds": 3.0,
            "manual_review": {"faithfulness": None, "relevance": None,
                              "unsupported_factual_claim": None, "correct_abstention": None, "notes": None},
        },
    ]

    result = _summary(records, dataset, "run-1")

    assert result["route_accuracy"] == 0.5
    assert result["source_accuracy"] == 0.5
    assert result["latency_seconds"] == {"mean": 2.0, "median": 2.0, "p95": 3.0}
    assert result["manual_review"]["hallucination_rate"] is None
