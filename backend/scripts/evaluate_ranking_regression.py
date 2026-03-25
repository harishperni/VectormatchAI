from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
import urllib.request
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.ranking_metrics import mrr, ndcg_at_k, precision_at_k, recall_at_k


def _fetch_json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _load_golden_dataset(job_id: str, root: Path) -> dict[str, Any] | None:
    file_path = root / f"{job_id}.json"
    if not file_path.exists():
        return None
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        return None
    return None


def _resolve_expected_ids(dataset: dict[str, Any] | None, rankings: list[dict[str, Any]]) -> set[str]:
    if not dataset:
        return set()

    expected_ids = {
        str(item).strip()
        for item in (dataset.get("expected_top_candidate_ids") or [])
        if isinstance(item, str) and item.strip()
    }
    expected_names = [
        str(item).strip().lower()
        for item in (dataset.get("expected_top_candidate_names") or [])
        if isinstance(item, str) and item.strip()
    ]
    if expected_names:
        for row in rankings:
            candidate_name = str(row.get("candidate_name") or "").lower()
            candidate_id = str(row.get("candidate_id") or "").strip()
            if not candidate_id:
                continue
            for expected_name in expected_names:
                if expected_name and expected_name in candidate_name:
                    expected_ids.add(candidate_id)
    return expected_ids


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate ranking regression metrics for a job.")
    parser.add_argument("--job-id", required=True, help="Job UUID")
    parser.add_argument("--top-k", type=int, default=5, help="Top-K for metrics")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Backend API base URL")
    parser.add_argument(
        "--golden-dir",
        default="data/golden",
        help="Directory containing {job_id}.json golden datasets",
    )
    parser.add_argument("--min-precision", type=float, default=None, help="Fail if precision@k is below threshold")
    parser.add_argument("--min-recall", type=float, default=None, help="Fail if recall@k is below threshold")
    parser.add_argument("--min-ndcg", type=float, default=None, help="Fail if ndcg@k is below threshold")
    parser.add_argument("--min-mrr", type=float, default=None, help="Fail if MRR is below threshold")
    args = parser.parse_args()

    rankings_payload = _fetch_json(f"{args.base_url.rstrip('/')}/api/v1/jobs/{args.job_id}/rankings")
    rankings = rankings_payload.get("items", [])
    if not isinstance(rankings, list):
        raise SystemExit("Invalid rankings payload")

    predicted_ids = [str(row.get("candidate_id") or "") for row in rankings if row.get("candidate_id")]
    dataset = _load_golden_dataset(args.job_id, Path(args.golden_dir))
    expected_ids = _resolve_expected_ids(dataset, rankings)

    metrics = {
        "job_id": args.job_id,
        "top_k": args.top_k,
        "ranked_count": len(predicted_ids),
        "expected_count": len(expected_ids),
        "precision_at_k": round(precision_at_k(predicted_ids, expected_ids, args.top_k), 4),
        "recall_at_k": round(recall_at_k(predicted_ids, expected_ids, args.top_k), 4),
        "ndcg_at_k": round(ndcg_at_k(predicted_ids, expected_ids, args.top_k), 4),
        "mrr": round(mrr(predicted_ids, expected_ids), 4),
    }

    print(json.dumps(metrics, indent=2))

    failures: list[str] = []
    if args.min_precision is not None and metrics["precision_at_k"] < args.min_precision:
        failures.append(
            f"precision@{args.top_k} {metrics['precision_at_k']} < min_precision {args.min_precision}"
        )
    if args.min_recall is not None and metrics["recall_at_k"] < args.min_recall:
        failures.append(f"recall@{args.top_k} {metrics['recall_at_k']} < min_recall {args.min_recall}")
    if args.min_ndcg is not None and metrics["ndcg_at_k"] < args.min_ndcg:
        failures.append(f"ndcg@{args.top_k} {metrics['ndcg_at_k']} < min_ndcg {args.min_ndcg}")
    if args.min_mrr is not None and metrics["mrr"] < args.min_mrr:
        failures.append(f"mrr {metrics['mrr']} < min_mrr {args.min_mrr}")

    if failures:
        raise SystemExit("Ranking regression check failed: " + "; ".join(failures))


if __name__ == "__main__":
    main()
