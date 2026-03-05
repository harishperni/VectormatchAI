from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.db.models import AuditLog


def _golden_file_path(job_id: str) -> Path:
    root = Path(os.getenv("GOLDEN_DATASET_DIR", "data/golden"))
    return root / f"{job_id}.json"


def _validate_dataset(payload: dict[str, Any]) -> dict[str, Any]:
    expected_ids = payload.get("expected_top_candidate_ids", [])
    expected_names = payload.get("expected_top_candidate_names", [])
    if not isinstance(expected_ids, list) or not all(
        isinstance(item, str) for item in expected_ids
    ):
        raise ValueError("expected_top_candidate_ids must be a list of strings")
    if not isinstance(expected_names, list) or not all(
        isinstance(item, str) for item in expected_names
    ):
        raise ValueError("expected_top_candidate_names must be a list of strings")
    return {
        "expected_top_candidate_ids": [item.strip() for item in expected_ids if item.strip()],
        "expected_top_candidate_names": [item.strip() for item in expected_names if item.strip()],
    }


def load_golden_dataset(job_id: str) -> dict[str, Any] | None:
    file_path = _golden_file_path(job_id)
    if not file_path.exists():
        return None
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        return None
    return None


def save_golden_dataset(job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    validated = _validate_dataset(payload)
    final_payload = {"job_id": job_id, **validated}
    file_path = _golden_file_path(job_id)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(json.dumps(final_payload, indent=2), encoding="utf-8")
    return final_payload


def resolve_expected_ids(
    dataset: dict[str, Any] | None, ranking_rows: list[dict[str, Any]]
) -> tuple[set[str], str | None]:
    if not dataset:
        return set(), None

    expected_ids = {
        str(value)
        for value in (dataset.get("expected_top_candidate_ids") or [])
        if isinstance(value, str) and value.strip()
    }
    expected_names = [
        str(value).strip().lower()
        for value in (dataset.get("expected_top_candidate_names") or [])
        if isinstance(value, str) and value.strip()
    ]

    if expected_names:
        for row in ranking_rows:
            candidate_name = str(row.get("candidate_name") or "").lower()
            candidate_id = str(row.get("candidate_id") or "")
            for expected in expected_names:
                if expected in candidate_name and candidate_id:
                    expected_ids.add(candidate_id)

    expected_source = "golden dataset file"
    return expected_ids, expected_source


def get_recent_ranking_run_payloads(
    db: Session, job_id: uuid.UUID, limit: int = 2
) -> list[dict[str, Any]]:
    rows = (
        db.execute(
            select(AuditLog)
            .where(
                AuditLog.entity_type == "job",
                AuditLog.entity_id == job_id,
                AuditLog.event_type == "ranking_run_completed",
            )
            .order_by(desc(AuditLog.created_at))
            .limit(limit)
        )
        .scalars()
        .all()
    )

    payloads: list[dict[str, Any]] = []
    for row in rows:
        payload = row.payload if isinstance(row.payload, dict) else {}
        payloads.append(payload)
    return payloads
