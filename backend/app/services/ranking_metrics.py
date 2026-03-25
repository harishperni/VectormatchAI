from __future__ import annotations

import math


def precision_at_k(predicted_ids: list[str], expected_ids: set[str], k: int) -> float:
    if k <= 0:
        return 0.0
    top_k = predicted_ids[:k]
    if not top_k:
        return 0.0
    hits = sum(1 for item in top_k if item in expected_ids)
    return hits / float(k)


def recall_at_k(predicted_ids: list[str], expected_ids: set[str], k: int) -> float:
    if not expected_ids or k <= 0:
        return 0.0
    top_k = predicted_ids[:k]
    hits = sum(1 for item in top_k if item in expected_ids)
    return hits / float(len(expected_ids))


def mrr(predicted_ids: list[str], expected_ids: set[str]) -> float:
    for idx, item in enumerate(predicted_ids, start=1):
        if item in expected_ids:
            return 1.0 / float(idx)
    return 0.0


def ndcg_at_k(predicted_ids: list[str], expected_ids: set[str], k: int) -> float:
    if k <= 0 or not expected_ids:
        return 0.0
    top_k = predicted_ids[:k]

    dcg = 0.0
    for idx, item in enumerate(top_k, start=1):
        relevance = 1.0 if item in expected_ids else 0.0
        if relevance > 0:
            dcg += relevance / math.log2(idx + 1.0)

    ideal_hits = min(k, len(expected_ids))
    idcg = sum(1.0 / math.log2(idx + 1.0) for idx in range(1, ideal_hits + 1))
    if idcg == 0:
        return 0.0
    return dcg / idcg
