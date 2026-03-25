from __future__ import annotations

import unittest

from app.parsing_metrics import aggregate_parsing_results, evaluate_parsing_case


class ParsingMetricsTests(unittest.TestCase):
    def test_case_scoring(self) -> None:
        expected = {
            "full_name": "John Doe",
            "email": "john@example.com",
            "phone": "5125551234",
            "candidate_location": "Austin, TX",
            "current_last_job": "Engineer",
            "highest_degree": "Bachelor's",
            "experience_years_final": 5.0,
            "skills": ["python", "sql", "aws"],
        }
        predicted = {
            "full_name": "John Doe",
            "email": "john@example.com",
            "phone": "(512) 555-1234",
            "candidate_location": "Austin, TX",
            "current_last_job": "Engineer",
            "highest_degree": "Bachelor's",
            "experience_years_final": 5.2,
            "skills": ["python", "aws"],
        }
        result = evaluate_parsing_case(expected, predicted)
        self.assertGreaterEqual(result["summary"]["scalar_accuracy"], 0.95)
        self.assertGreater(result["summary"]["skills_f1"], 0.7)

    def test_aggregate(self) -> None:
        results = [
            {"summary": {"scalar_accuracy": 1.0, "skills_f1": 1.0, "overall_score": 1.0}},
            {"summary": {"scalar_accuracy": 0.5, "skills_f1": 0.5, "overall_score": 0.5}},
        ]
        aggregate = aggregate_parsing_results(results)
        self.assertEqual(aggregate["case_count"], 2)
        self.assertAlmostEqual(aggregate["avg_overall_score"], 0.75)


if __name__ == "__main__":
    unittest.main()
