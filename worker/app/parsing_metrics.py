from __future__ import annotations

import re
from typing import Any


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def _normalize_phone(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\D+", "", str(value))


def _as_set(values: Any) -> set[str]:
    if not isinstance(values, list):
        return set()
    return {_normalize_text(item) for item in values if _normalize_text(item)}


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _set_precision_recall_f1(predicted: set[str], expected: set[str]) -> dict[str, float]:
    if not predicted and not expected:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    if not predicted:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}
    tp = len(predicted.intersection(expected))
    precision = tp / float(len(predicted))
    recall = tp / float(len(expected)) if expected else 0.0
    if precision + recall == 0:
        f1 = 0.0
    else:
        f1 = 2.0 * precision * recall / (precision + recall)
    return {"precision": precision, "recall": recall, "f1": f1}


def evaluate_parsing_case(expected: dict[str, Any], predicted: dict[str, Any]) -> dict[str, Any]:
    scalar_fields = [
        "full_name",
        "email",
        "candidate_location",
        "current_last_job",
        "highest_degree",
    ]
    strict_scalar_fields = ["phone"]
    numeric_fields = ["experience_years_final"]

    fields: dict[str, dict[str, Any]] = {}
    for field in scalar_fields:
        exp = _normalize_text(expected.get(field))
        pred = _normalize_text(predicted.get(field))
        matched = bool(exp and pred and exp == pred) or (not exp and not pred)
        fields[field] = {"match": 1.0 if matched else 0.0, "expected": expected.get(field), "predicted": predicted.get(field)}

    for field in strict_scalar_fields:
        exp = _normalize_phone(expected.get(field))
        pred = _normalize_phone(predicted.get(field))
        matched = bool(exp and pred and exp == pred) or (not exp and not pred)
        fields[field] = {"match": 1.0 if matched else 0.0, "expected": expected.get(field), "predicted": predicted.get(field)}

    for field in numeric_fields:
        exp = _to_float(expected.get(field))
        pred = _to_float(predicted.get(field))
        if exp is None and pred is None:
            matched = True
        elif exp is None or pred is None:
            matched = False
        else:
            matched = abs(exp - pred) <= 0.5
        fields[field] = {"match": 1.0 if matched else 0.0, "expected": exp, "predicted": pred}

    expected_skills = _as_set(expected.get("skills"))
    predicted_skills = _as_set(predicted.get("skills"))
    fields["skills"] = _set_precision_recall_f1(predicted_skills, expected_skills)

    accuracy_fields = [name for name in fields if name != "skills"]
    scalar_accuracy = (
        sum(float(fields[name]["match"]) for name in accuracy_fields) / float(len(accuracy_fields))
        if accuracy_fields
        else 0.0
    )
    summary = {
        "scalar_accuracy": scalar_accuracy,
        "skills_f1": float(fields["skills"]["f1"]),
        "overall_score": (0.7 * scalar_accuracy) + (0.3 * float(fields["skills"]["f1"])),
    }
    return {"fields": fields, "summary": summary}


def aggregate_parsing_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    if not results:
        return {
            "case_count": 0,
            "avg_scalar_accuracy": 0.0,
            "avg_skills_f1": 0.0,
            "avg_overall_score": 0.0,
        }

    avg_scalar = sum(float(item["summary"]["scalar_accuracy"]) for item in results) / len(results)
    avg_skills = sum(float(item["summary"]["skills_f1"]) for item in results) / len(results)
    avg_overall = sum(float(item["summary"]["overall_score"]) for item in results) / len(results)
    return {
        "case_count": len(results),
        "avg_scalar_accuracy": avg_scalar,
        "avg_skills_f1": avg_skills,
        "avg_overall_score": avg_overall,
    }
