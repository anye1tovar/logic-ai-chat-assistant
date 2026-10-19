"""Package a completed runner output and create its human-review CSV."""

import argparse
import csv
import hashlib
import json
import platform
import subprocess
import sys
import urllib.parse
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COLUMNS = [
    "ID del escenario", "Categoría", "Pregunta del usuario", "Respuesta generada por Nox",
    "Fuente o fuentes consultadas", "Ruta esperada", "Ruta observada", "Fidelidad (0, 1, 2)",
    "Relevancia (0, 1, 2)", "Exactitud de información comercial",
    "Manejo correcto de excepciones o incertidumbre", "Presencia de afirmaciones no sustentadas",
    "Observaciones del evaluador",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_endpoint(value: str | None) -> dict[str, object]:
    if not value:
        return {"configured": False}
    parsed = urllib.parse.urlsplit(value)
    hostname = parsed.hostname
    origin = f"{parsed.scheme}://{hostname or ''}"
    if parsed.port:
        origin += f":{parsed.port}"
    return {"configured": True, "origin": origin, "base_path": parsed.path or "/"}


def git_output(*args: str) -> str | None:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True,
                              text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def package(run_dir: Path) -> None:
    run_dir = run_dir.resolve()
    summary_path = run_dir / "summary.json"
    raw_path = run_dir / "raw_runs.jsonl"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    records = [json.loads(line) for line in raw_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    dataset_path = ROOT / "evaluation" / "cases.json"
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    by_id = {case["id"]: case for case in dataset["cases"]}
    review_dir = run_dir / "review"
    review_dir.mkdir(exist_ok=True)
    matrix_path = review_dir / "matriz_evaluacion.csv"
    with matrix_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=COLUMNS)
        writer.writeheader()
        for record in records:
            source_items = []
            for tool in record.get("tool_calls", []):
                source_items.append(f"{tool['name']} ({tool.get('evidence_mode') or 'sin evidencia'})")
            for doc_id in record.get("rag_document_ids", []):
                source_items.append(f"RAG:{doc_id}")
            source_cell = "; ".join(dict.fromkeys(source_items)) or "Ninguna: falló antes de consultar herramientas"
            writer.writerow({
                "ID del escenario": record["case_id"],
                "Categoría": record["category"],
                "Pregunta del usuario": record["question"],
                "Respuesta generada por Nox": record["answer"],
                "Fuente o fuentes consultadas": source_cell,
                "Ruta esperada": record["expected_route"],
                "Ruta observada": record.get("selected_route") or "Sin selección",
                **{column: "" for column in COLUMNS[7:]},
            })

    try:
        sys.path.insert(0, str(ROOT / "backend"))
        from app.core.config import get_settings
        settings = get_settings()
        rag_path = settings.chroma_persist_directory
        if not rag_path.is_absolute():
            rag_path = ROOT / "backend" / rag_path
        configuration = {
            "app_env": settings.app_env,
            "model": settings.openai_model,
            "llm_provider_endpoint": "https://api.openai.com/v1 (OpenAI SDK default)",
            "embedding_model": settings.openai_embedding_model,
            "reasoning_effort": settings.openai_reasoning_effort,
            "chat_max_output_tokens": settings.openai_chat_max_output_tokens,
            "openai_timeout_seconds": settings.openai_timeout_seconds,
            "logic_api_endpoint": safe_endpoint(settings.logic_api_base_url),
            "logic_api_timeout_seconds": settings.logic_api_timeout_seconds,
            "reference_cache_ttl_seconds": settings.logic_reference_cache_ttl_seconds,
            "rag_collection": settings.chroma_collection_name,
            "rag_max_distance": settings.rag_max_distance,
            "rag_index_path": str(rag_path.relative_to(ROOT)) if rag_path.is_relative_to(ROOT) else str(rag_path),
            "rag_index_exists": rag_path.exists(),
            "credentials_included": False,
        }
    except Exception as exc:
        configuration = {"configuration_capture_error": type(exc).__name__, "credentials_included": False}

    sources = [ROOT / "backend" / "app", ROOT / "backend" / "pyproject.toml",
               ROOT / "evaluation" / "cases.json", ROOT / "evaluation" / "consolidate.py",
               ROOT / "evaluation" / "prepare_artifacts.py", ROOT / "docs" / "06_PHASE_EVALUATION.md",
               ROOT / "config" / "knowledge-schema.json", ROOT / "config" / "source-policy.yaml"]
    sources.extend(sorted((ROOT / "knowledge").rglob("*.md")))
    archive_path = run_dir / "reproduction_source_snapshot.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for item in sources:
            candidates = item.rglob("*") if item.is_dir() else [item]
            for path in candidates:
                if not path.is_file() or "__pycache__" in path.parts:
                    continue
                relative = path.relative_to(ROOT)
                archive.write(path, Path("source_snapshot") / relative)
        rag_path = ROOT / "backend" / ".data" / "chroma"
        if rag_path.exists():
            for path in sorted(rag_path.rglob("*")):
                if path.is_file():
                    archive.write(path, Path("data_snapshot") / path.relative_to(ROOT))

    rag_files = sorted((ROOT / "backend" / ".data" / "chroma").rglob("*"))
    rag_hash = hashlib.sha256()
    for path in rag_files:
        if path.is_file():
            rag_hash.update(str(path.relative_to(ROOT)).encode())
            rag_hash.update(bytes.fromhex(sha256(path)))

    run_errors = {}
    for record in records:
        for error in record.get("trace_errors", []):
            key = f"{error.get('stage')}:{error.get('type')}"
            run_errors[key] = run_errors.get(key, 0) + 1
    manifest = {
        "manifest_version": "1.0",
        "run_id": summary["run_id"],
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_status": "completed_with_case_errors" if summary["cases_with_errors"] else "completed",
        "evaluation_claim": "No human quality scores are present; route/source labels are not answer-quality evidence.",
        "execution_mode": {
            "runner_uses_mocks": False,
            "llm_and_embeddings": "configured external provider; network calls failed before tool execution in this run",
            "logic_api": "configured external endpoint; no Logic API request occurred because route selection failed",
            "rag": "persistent local Chroma collection; no retrieval occurred because route selection failed",
            "availability_freshness": "not applicable; no availability request occurred",
        },
        "configuration_non_secret": configuration,
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
        "source_state": {
            "git_head": git_output("rev-parse", "HEAD"),
            "working_tree_clean": not bool(git_output("status", "--porcelain")),
            "working_tree_status_sha256": hashlib.sha256((git_output("status", "--porcelain") or "").encode()).hexdigest(),
            "prompt_sha256": summary.get("prompt_sha256"),
            "dataset_sha256": summary.get("dataset_sha256"),
            "knowledge_markdown_sha256": summary.get("knowledge_sha256"),
            "rag_index_sha256": rag_hash.hexdigest() if rag_files else None,
            "runner_code_revision_reported": summary.get("code_revision"),
            "source_snapshot": archive_path.name,
            "source_snapshot_sha256": sha256(archive_path),
        },
        "result_artifacts": {
            "summary_sha256": sha256(summary_path),
            "raw_runs_sha256": sha256(raw_path),
            "review_matrix": str(matrix_path.relative_to(ROOT)),
            "review_matrix_sha256": sha256(matrix_path),
        },
        "case_errors": run_errors,
        "cases": len(records),
        "human_scored_cases": 0,
        "note": "This is a preserved failed live-service attempt, not a valid conversational quality run. A subsequent approved run must use a new output directory.",
    }
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_directory", type=Path)
    args = parser.parse_args()
    package(args.run_directory if args.run_directory.is_absolute() else ROOT / args.run_directory)


if __name__ == "__main__":
    main()
