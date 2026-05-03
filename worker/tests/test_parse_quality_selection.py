from __future__ import annotations

import unittest

from app.main import _choose_best_parse


class ParseQualitySelectionTests(unittest.TestCase):
    def test_prefers_recovered_when_primary_is_sparse(self) -> None:
        text = """
TECHNTECHNICAL SKILLS:
OLAP, SQL Server, Oracle
PROFESSIONAL EXPERIENCE:
Client – A, NY (2018-Present)
Role\\Designation: Project Manager
""".strip()

        primary = {
            "email": None,
            "phone": None,
            "full_name": None,
            "skills": ["OLAP"],
            "experience_entries": [],
            "current_last_job": "PMP Expiration Date: February 6th 2020",
        }
        recovered = {
            "email": "a@b.com",
            "phone": "111-222-3333",
            "full_name": "Alex Doe",
            "skills": ["OLAP", "SQL Server", "Oracle"],
            "experience_entries": [
                {"title": "Project Manager", "company": "Client A", "description": "desc"}
            ],
            "current_last_job": "Project Manager",
        }

        best = _choose_best_parse(primary, recovered, text)
        self.assertEqual(best.get("full_name"), "Alex Doe")
        self.assertEqual(best.get("current_last_job"), "Project Manager")

    def test_keeps_primary_when_it_is_stronger(self) -> None:
        text = "PROFESSIONAL EXPERIENCE:\nRole: Analyst\n"
        primary = {
            "email": "a@b.com",
            "phone": "111-222-3333",
            "full_name": "Alex Doe",
            "skills": ["SQL", "Python", "Tableau", "Power BI"],
            "experience_entries": [
                {"title": "Analyst", "company": "X", "description": "desc"},
                {"title": "Senior Analyst", "company": "Y", "description": "desc"},
            ],
            "current_last_job": "Analyst",
        }
        recovered = {
            "email": None,
            "phone": None,
            "full_name": None,
            "skills": ["SQL"],
            "experience_entries": [],
            "current_last_job": None,
        }
        best = _choose_best_parse(primary, recovered, text)
        self.assertEqual(best.get("full_name"), "Alex Doe")
        self.assertEqual(best.get("email"), "a@b.com")


if __name__ == "__main__":
    unittest.main()

