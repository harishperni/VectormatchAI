from __future__ import annotations

import unittest

from app.services.ranking_metrics import mrr, ndcg_at_k, precision_at_k, recall_at_k


class RankingMetricsTests(unittest.TestCase):
    def test_precision_and_recall(self) -> None:
        predicted = ["c1", "c2", "c3", "c4"]
        expected = {"c2", "c4"}
        self.assertAlmostEqual(precision_at_k(predicted, expected, 2), 0.5)
        self.assertAlmostEqual(recall_at_k(predicted, expected, 2), 0.5)
        self.assertAlmostEqual(recall_at_k(predicted, expected, 4), 1.0)

    def test_mrr(self) -> None:
        predicted = ["c9", "c8", "c7", "c2"]
        expected = {"c2", "c5"}
        self.assertAlmostEqual(mrr(predicted, expected), 0.25)

    def test_ndcg(self) -> None:
        predicted = ["c1", "c2", "c3"]
        expected = {"c1", "c2"}
        score = ndcg_at_k(predicted, expected, 3)
        self.assertGreater(score, 0.9)


if __name__ == "__main__":
    unittest.main()
