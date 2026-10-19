"""Run the frozen evaluation cases against the configured assistant services.

Run from backend/: python -m app.evaluation.run --dataset ../evaluation/cases.json
"""

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import logging
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.assistant.model import ModelConfigurationError, OpenAIChatModel
from app.assistant.orchestrator import AssistantOrchestrator
from app.assistant.schemas import ChatTurn, RouteSelection
from app.assistant.tools import AssistantTools, ToolOutcome
from app.core.config import get_settings
from app.evaluation.schemas import EvaluationDataset, ManualReview

LOGGER = logging.getLogger("logic.evaluation")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_revision() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
            check=True, timeout=3,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


class _Trace:
    def __init__(self) -> None:
        self.route: str | None = None
        self.model_calls: list[dict[str, Any]] = []
        self.tool_calls: list[dict[str, Any]] = []
        self.errors: list[dict[str, Any]] = []
        self.rag_document_ids: list[str] = []
        self.api_status_codes: list[int] = []
        self.api_result_category: str | None = None

    @property
    def model_latency_seconds(self) -> float:
        return round(sum(call["latency_seconds"] for call in self.model_calls), 6)

    @property
    def tool_latency_seconds(self) -> float:
        return round(sum(call["latency_seconds"] for call in self.tool_calls), 6)


class _ObservedModel:
    def __init__(self, model: OpenAIChatModel, trace: _Trace) -> None:
        self._model = model
        self._trace = trace

    async def select_route(self, *args: Any, **kwargs: Any) -> RouteSelection:
        started = time.perf_counter()
        call = {"name": "select_route", "latency_seconds": 0.0, "error": None}
        try:
            selection = await self._model.select_route(*args, **kwargs)
            self._trace.route = selection.route
            return selection
        except Exception as exc:
            call["error"] = type(exc).__name__
            self._trace.errors.append({"stage": "route_selection", "type": type(exc).__name__})
            raise
        finally:
            call["latency_seconds"] = round(time.perf_counter() - started, 6)
            self._trace.model_calls.append(call)

    async def generate_answer(self, *args: Any, **kwargs: Any) -> str:
        started = time.perf_counter()
        call = {"name": "generate_answer", "latency_seconds": 0.0, "error": None}
        try:
            return await self._model.generate_answer(*args, **kwargs)
        except Exception as exc:
            call["error"] = type(exc).__name__
            self._trace.errors.append({"stage": "answer_generation", "type": type(exc).__name__})
            raise
        finally:
            call["latency_seconds"] = round(time.perf_counter() - started, 6)
            self._trace.model_calls.append(call)


class _ObservedTools:
    def __init__(self, tools: AssistantTools, trace: _Trace) -> None:
        self._tools = tools
        self.settings = tools.settings
        self._trace = trace

    async def execute(self, selection: RouteSelection, user_message: str) -> ToolOutcome:
        started = time.perf_counter()
        call: dict[str, Any] = {
            "name": selection.route,
            "latency_seconds": 0.0,
            "result_category": "error",
            "evidence_mode": None,
            "error": None,
        }
        try:
            outcome = await self._tools.execute(selection, user_message)
            call["result_category"] = "fallback" if outcome.fallback_answer else "success"
            call["evidence_mode"] = outcome.evidence.mode
            for fact in outcome.evidence.rag_facts:
                document_id = fact.get("document_id")
                if document_id and document_id not in self._trace.rag_document_ids:
                    self._trace.rag_document_ids.append(document_id)
            api_expected = selection.route in {
                "get_rooms", "get_rates", "get_opening_hours", "get_quote",
                "get_availability", "check_room_policy",
            }
            if api_expected:
                self._trace.api_result_category = call["result_category"]
            return outcome
        except Exception as exc:
            code = getattr(exc, "status_code", None)
            if isinstance(code, int):
                self._trace.api_status_codes.append(code)
            call["error"] = type(exc).__name__
            call["status_code"] = code
            self._trace.errors.append({
                "stage": "tool_execution", "type": type(exc).__name__,
                "status_code": code,
            })
            self._trace.api_result_category = "error"
            raise
        finally:
            call["latency_seconds"] = round(time.perf_counter() - started, 6)
            self._trace.tool_calls.append(call)


def _source_modes(trace: _Trace) -> list[str]:
    modes = {call.get("evidence_mode") for call in trace.tool_calls}
    sources: set[str] = set()
    for mode in modes:
        if mode and "api" in mode:
            sources.add("api")
        if mode and "rag" in mode:
            sources.add("rag")
    return sorted(sources)


async def _run_case(case, model: OpenAIChatModel, tools: AssistantTools, run_id: str) -> dict[str, Any]:
    trace = _Trace()
    orchestrator = AssistantOrchestrator(_ObservedModel(model, trace), _ObservedTools(tools, trace))
    started = time.perf_counter()
    error: dict[str, str] | None = None
    try:
        answer = await orchestrator.reply(case.question, history=case.history)
    except Exception as exc:  # Fail this case while preserving a usable batch report.
        answer = ""
        error = {"type": type(exc).__name__}
        trace.errors.append({"stage": "runner", "type": type(exc).__name__})
        LOGGER.error("Evaluation case failed: %s (%s)", case.id, type(exc).__name__)
    elapsed = round(time.perf_counter() - started, 6)
    if trace.tool_calls:
        # A bounded recovery rule can replace the model's initial clarification route.
        trace.route = trace.tool_calls[-1]["name"]
    observed_source = _source_modes(trace)
    return {
        "run_id": run_id,
        "interaction_id": f"{run_id}:{case.id}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "case_id": case.id,
        "category": case.category,
        "question": case.question,
        "expected_route": case.expected_route,
        "expected_behavior": case.expected_behavior,
        "reference_answer_or_criteria": case.reference_answer_or_criteria,
        "should_answer": case.should_answer,
        "notes": case.notes,
        "selected_route": trace.route,
        "route_correct": trace.route == case.expected_route,
        "expected_source": case.expected_source,
        "observed_source": observed_source,
        "source_correct": set(case.expected_source) == set(observed_source),
        "tool_calls": trace.tool_calls,
        "api_result_category": trace.api_result_category,
        # LogicApiClient exposes typed error status codes but not success response codes.
        "api_status_codes": trace.api_status_codes,
        "rag_document_ids": trace.rag_document_ids,
        "answer": answer,
        "end_to_end_latency_seconds": elapsed,
        "model_latency_seconds": trace.model_latency_seconds,
        "tool_latency_seconds": trace.tool_latency_seconds,
        "token_usage": None,
        "error": error,
        "trace_errors": trace.errors,
        "manual_review": ManualReview().model_dump(),
    }


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * percentile)))
    return round(ordered[index], 6)


def _summary(records: list[dict[str, Any]], dataset: EvaluationDataset, run_id: str) -> dict[str, Any]:
    durations = [record["end_to_end_latency_seconds"] for record in records]
    reviewed = [record["manual_review"] for record in records if record["manual_review"]["faithfulness"] is not None]
    hallucination_reviews = [item for item in reviewed if item["unsupported_factual_claim"] is not None]
    return {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset_version": dataset.dataset_version,
        "total_cases": len(records),
        "route_accuracy": round(sum(record["route_correct"] for record in records) / len(records), 4) if records else None,
        "source_accuracy": round(sum(record["source_correct"] for record in records) / len(records), 4) if records else None,
        "cases_with_errors": sum(bool(record["error"] or record["trace_errors"]) for record in records),
        "latency_seconds": {
            "mean": round(statistics.mean(durations), 6) if durations else None,
            "median": round(statistics.median(durations), 6) if durations else None,
            "p95": _percentile(durations, 0.95),
        },
        "manual_review": {
            "reviewed_cases": len(reviewed),
            "hallucination_rate": (
                round(sum(item["unsupported_factual_claim"] is True for item in hallucination_reviews) / len(hallucination_reviews), 4)
                if hallucination_reviews else None
            ),
            "correct_abstention_cases": sum(item["correct_abstention"] is True for item in reviewed),
            "faithfulness_mean": round(statistics.mean(item["faithfulness"] for item in reviewed), 4) if reviewed else None,
            "relevance_mean": round(statistics.mean(item["relevance"] for item in reviewed if item["relevance"] is not None), 4)
            if any(item["relevance"] is not None for item in reviewed) else None,
        },
    }


async def run(dataset_path: Path, output_dir: Path, limit: int | None = None) -> dict[str, Any]:
    raw_dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    dataset = EvaluationDataset.model_validate(raw_dataset)
    dataset.validate_unique_ids()
    cases = dataset.cases[:limit] if limit else dataset.cases
    settings = get_settings()
    model = OpenAIChatModel(settings)
    tools = AssistantTools(settings=settings)
    run_id = uuid4().hex
    try:
        records = [await _run_case(case, model, tools, run_id) for case in cases]
    finally:
        await model.aclose()

    output_dir.mkdir(parents=True, exist_ok=True)
    raw_path = output_dir / "raw_runs.jsonl"
    with raw_path.open("a", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")

    summary = _summary(records, dataset, run_id)
    prompt_path = Path(__file__).resolve().parents[1] / "core" / "prompts.py"
    knowledge_paths = sorted((dataset_path.parent.parent / "knowledge").rglob("*.md"))
    summary.update({
        "code_revision": _git_revision(),
        "model": settings.openai_model,
        "prompt_sha256": _sha256(prompt_path),
        "dataset_sha256": _sha256(dataset_path),
        "knowledge_sha256": hashlib.sha256("".join(_sha256(path) for path in knowledge_paths).encode()).hexdigest(),
        "results_file": str(raw_path),
        "latency_note": "Duraciones medidas localmente; no incluyen calibración entre máquinas.",
    })
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Ejecuta el dataset de evaluación de Nox.")
    parser.add_argument("--dataset", type=Path, default=Path("../evaluation/cases.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("../evaluation/results"))
    parser.add_argument("--limit", type=int, default=None, help="Ejecuta solo los primeros N casos.")
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit debe ser mayor que cero")
    try:
        summary = asyncio.run(run(args.dataset, args.output_dir, args.limit))
    except (OSError, ValueError, ModelConfigurationError) as exc:
        print(f"No se pudo iniciar la evaluación: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
