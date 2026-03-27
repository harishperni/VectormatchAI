from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.main import extract_resume_features_fallback
from app.llm_parse import (
    calculate_experience_years_from_entries,
    derive_primary_domain,
    derive_seniority_level,
    normalize_resume_text,
    parse_resume_with_ft_v2,
)
from app.parsing_metrics import aggregate_parsing_results, evaluate_parsing_case


def _load_dataset(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Dataset must be a JSON object")
    return payload


def _build_final_payload(strict_parsed: dict[str, Any]) -> dict[str, Any]:
    final_payload = dict(strict_parsed)
    final_payload["experience_years"] = calculate_experience_years_from_entries(
        strict_parsed.get("experience_entries", [])
    )
    final_payload["primary_domain"] = derive_primary_domain(
        strict_parsed.get("current_last_job"),
        strict_parsed.get("experience_entries", []),
        strict_parsed.get("skills", []),
    )
    final_payload["seniority_level"] = derive_seniority_level(
        strict_parsed.get("current_last_job")
    )
    return final_payload


def _predict(text: str, enable_llm: bool) -> dict[str, Any]:
    normalized_text = normalize_resume_text(text)

    if not enable_llm:
        strict_parsed = extract_resume_features_fallback(normalized_text)
        return _build_final_payload(strict_parsed)

    llm_parsed = parse_resume_with_ft_v2(normalized_text)
    if not llm_parsed:
        strict_parsed = extract_resume_features_fallback(normalized_text)
        return _build_final_payload(strict_parsed)

    return _build_final_payload(llm_parsed)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate v2 resume parsing quality on a golden dataset.")
    parser.add_argument(
        "--dataset",
        default="data/parsing/parsing_golden_sample.json",
        help="JSON dataset path containing parsing cases",
    )
    parser.add_argument(
        "--enable-llm",
        action="store_true",
        help="Enable v2 fine-tuned model parse mode for evaluation",
    )
    parser.add_argument(
        "--min-overall-score",
        type=float,
        default=None,
        help="Fail if average overall score is below threshold",
    )
    args = parser.parse_args()

    dataset = _load_dataset(Path(args.dataset))
    cases = dataset.get("cases", [])
    if not isinstance(cases, list) or not cases:
        raise SystemExit("Dataset must contain non-empty 'cases' array")

    evaluated: list[dict[str, Any]] = []
    for case in cases:
        if not isinstance(case, dict):
            continue

        text = str(case.get("text") or "")
        expected = case.get("expected") if isinstance(case.get("expected"), dict) else {}
        if not text.strip():
            continue

        predicted = _predict(text, enable_llm=args.enable_llm)
        result = evaluate_parsing_case(expected, predicted)

        evaluated.append(
            {
                "id": case.get("id"),
                "tags": case.get("tags", []),
                "summary": result["summary"],
                "fields": result["fields"],
            }
        )

    aggregate = aggregate_parsing_results(evaluated)
    payload = {
        "dataset": args.dataset,
        "enable_llm": bool(args.enable_llm),
        "aggregate": aggregate,
        "cases": evaluated,
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))

    if args.min_overall_score is not None and aggregate["avg_overall_score"] < args.min_overall_score:
        raise SystemExit(
            f"Parsing regression check failed: avg_overall_score "
            f"{aggregate['avg_overall_score']:.4f} < {args.min_overall_score:.4f}"
        )


if __name__ == "__main__":
    main()