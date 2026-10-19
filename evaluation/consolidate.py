"""Consolidate completed human reviews into category tables and SVG charts.

Usage: python evaluation/consolidate.py evaluation/review/current-tree-20261018-01.csv
"""

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path


FIDELITY = "Fidelidad (0, 1, 2)"
RELEVANCE = "Relevancia (0, 1, 2)"
COMMERCIAL = "Exactitud de información comercial"
EXCEPTIONS = "Manejo correcto de excepciones o incertidumbre"
UNSUPPORTED = "Presencia de afirmaciones no sustentadas"
VALID_JUDGMENTS = {"Sí", "Parcial", "No", "No aplica"}


def read_reviews(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
        required = {"ID del escenario", "Categoría", FIDELITY, RELEVANCE,
                    COMMERCIAL, EXCEPTIONS, UNSUPPORTED}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Faltan columnas requeridas: {', '.join(sorted(missing))}")
    ids = [row["ID del escenario"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("Hay IDs de escenario duplicados.")
    for row in rows:
        for column in (FIDELITY, RELEVANCE):
            value = row[column].strip()
            if value and value not in {"0", "1", "2"}:
                raise ValueError(f"{row['ID del escenario']}: {column} debe ser 0, 1, 2 o vacío.")
        for column in (COMMERCIAL, EXCEPTIONS, UNSUPPORTED):
            value = row[column].strip()
            if value and value not in VALID_JUDGMENTS:
                raise ValueError(
                    f"{row['ID del escenario']}: {column} debe ser {', '.join(sorted(VALID_JUDGMENTS))} o vacío."
                )
    return rows


def mean(rows: list[dict[str, str]], column: str) -> float | None:
    values = [int(row[column]) for row in rows if row[column].strip()]
    return round(sum(values) / len(values), 4) if values else None


def judgment_stats(rows: list[dict[str, str]], column: str) -> dict[str, object]:
    values = [row[column].strip() for row in rows if row[column].strip()]
    counts = {label: values.count(label) for label in ("Sí", "Parcial", "No", "No aplica")}
    denominator = len(values)
    return {
        "n": denominator,
        "counts": counts,
        "percentages": {
            label: round(count / denominator * 100, 2) if denominator else None
            for label, count in counts.items()
        },
    }


def score_stats(rows: list[dict[str, str]], column: str) -> dict[str, object]:
    values = [row[column].strip() for row in rows if row[column].strip()]
    counts = {str(score): values.count(str(score)) for score in (0, 1, 2)}
    denominator = len(values)
    return {
        "n": denominator,
        "mean": mean(rows, column),
        "counts": counts,
        "percentages": {
            score: round(count / denominator * 100, 2) if denominator else None
            for score, count in counts.items()
        },
    }


def svg_chart(categories: list[str], values: list[float | None], title: str,
              output: Path, maximum: float) -> None:
    width, height = 960, max(220, 100 + 58 * len(categories))
    left, right = 300, 70
    plot_width = width - left - right
    bars = []
    for index, (category, value) in enumerate(zip(categories, values, strict=True)):
        y = 62 + index * 58
        label = category.replace("&", "&amp;").replace("<", "&lt;")
        if value is None:
            bar, value_text = "", "Sin valoraciones"
        else:
            bar_width = max(1, plot_width * value / maximum)
            bar = f'<rect x="{left}" y="{y}" width="{bar_width:.1f}" height="28" rx="5" fill="#3b82f6" />'
            value_text = f"{value:.2f}"
        bars.append(
            f'<text x="20" y="{y + 19}" class="label">{label}</text>{bar}'
            f'<text x="{left + plot_width + 12}" y="{y + 19}" class="value">{value_text}</text>'
        )
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<style>text{{font-family:Arial,sans-serif;fill:#172033}}.title{{font-size:22px;font-weight:bold}}.label{{font-size:14px}}.value{{font-size:13px;fill:#475569}}</style>
<rect width="100%" height="100%" fill="#fff"/><text x="20" y="32" class="title">{title}</text>
{''.join(bars)}</svg>'''
    output.write_text(svg, encoding="utf-8")


def consolidate(input_csv: Path, output_dir: Path) -> dict[str, object]:
    rows = read_reviews(input_csv)
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        groups[row["Categoría"]].append(row)
    categories = sorted(groups)
    summary: dict[str, object] = {
        "input_file": input_csv.name, "total_cases": len(rows), "overall": {}, "by_category": {}
    }
    summary["overall"] = {
        "faithfulness": score_stats(rows, FIDELITY),
        "relevance": score_stats(rows, RELEVANCE),
        "commercial_accuracy": judgment_stats(rows, COMMERCIAL),
        "exception_handling": judgment_stats(rows, EXCEPTIONS),
        "unsupported_claims": judgment_stats(rows, UNSUPPORTED),
    }
    for category in categories:
        items = groups[category]
        summary["by_category"][category] = {
            "cases": len(items),
            "faithfulness": score_stats(items, FIDELITY),
            "relevance": score_stats(items, RELEVANCE),
            "commercial_accuracy": judgment_stats(items, COMMERCIAL),
            "exception_handling": judgment_stats(items, EXCEPTIONS),
            "unsupported_claims": judgment_stats(items, UNSUPPORTED),
        }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "consolidated_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    fields = ["Categoría", "Casos", "Fidelidad n", "Fidelidad promedio", "Relevancia n",
              "Relevancia promedio", "Exactitud comercial evaluada", "Excepciones evaluadas",
              "Afirmaciones no sustentadas evaluadas"]
    with (output_dir / "by_category.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for category in categories:
            item = summary["by_category"][category]
            writer.writerow({"Categoría": category, "Casos": item["cases"],
                             "Fidelidad n": item["faithfulness"]["n"],
                             "Fidelidad promedio": item["faithfulness"]["mean"],
                             "Relevancia n": item["relevance"]["n"],
                             "Relevancia promedio": item["relevance"]["mean"],
                             "Exactitud comercial evaluada": item["commercial_accuracy"]["n"],
                             "Excepciones evaluadas": item["exception_handling"]["n"],
                             "Afirmaciones no sustentadas evaluadas": item["unsupported_claims"]["n"]})
    svg_chart(categories, [summary["by_category"][c]["faithfulness"]["mean"] for c in categories],
              "Fidelidad media por categoría (escala 0–2)", output_dir / "faithfulness_by_category.svg", 2)
    svg_chart(categories, [summary["by_category"][c]["relevance"]["mean"] for c in categories],
              "Relevancia media por categoría (escala 0–2)", output_dir / "relevance_by_category.svg", 2)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Consolida la matriz de evaluación humana de Nox.")
    parser.add_argument("matrix", type=Path)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()
    output = args.output_dir or args.matrix.parent / "consolidated"
    print(json.dumps(consolidate(args.matrix, output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
