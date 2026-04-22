from __future__ import annotations

import unittest

from app.llm_parse import _normalize_llm_parse_output_v2


class LlmParseConsistencyTests(unittest.TestCase):
    def test_recovers_core_sections_when_model_output_is_empty(self) -> None:
        parsed: dict = {}
        raw_text = """
Yeswanth Naga Harish Perni
yeswanthnagaharish.perni@gmail.com | 3096218996 | Plano, TX | LinkedIn

Professional Summary
Microsoft 365 System Administrator and SharePoint Developer with 3+ years of experience.

Skills:
Microsoft 365, SharePoint Online, Power Apps, Power Automate, HTML, CSS, Python

Work Experience:
Urology Austin
SharePoint Developer
Location: Plano, TX | Duration: Feb 2025 – Present
Built SharePoint intranet portal and automated onboarding with Power Automate.

Caterpillar
SharePoint Data Analyst
Location: Nashville, Tennessee | Duration: Aug 2024 – Dec 2024
Automated invoice processing workflow with Power Automate.
""".strip()

        normalized = _normalize_llm_parse_output_v2(parsed, raw_text)
        entries = normalized.get("experience_entries", [])
        skills = [str(item).lower() for item in normalized.get("skills", [])]

        self.assertGreaterEqual(len(entries), 2)
        self.assertTrue(any("urology austin" == str(item.get("company") or "").lower() for item in entries))
        self.assertTrue(any("sharepoint developer" in str(item.get("title") or "").lower() for item in entries))
        self.assertIn("sharepoint online", skills)
        self.assertIn("power automate", skills)
        self.assertEqual(normalized.get("candidate_location"), "Plano, TX")
        self.assertEqual(normalized.get("email"), "yeswanthnagaharish.perni@gmail.com")

    def test_repairs_malformed_experience_entries_with_fallback(self) -> None:
        parsed = {
            "full_name": "Test User",
            "current_last_job": "SharePoint Developer",
            "experience_entries": [
                {
                    "title": None,
                    "company": "Location: Plano, TX | Duration: Feb 2025 – Present",
                    "start_date": "2025-02",
                    "end_date": "Present",
                    "is_current": True,
                    "location": "Plano, TX",
                    "description": None,
                    "skills_used": [],
                    "achievements": [],
                },
                {
                    "title": None,
                    "company": "Location: Nashville, Tennessee | Duration: Aug 2024 – Dec 2024",
                    "start_date": "2024-08",
                    "end_date": "2024-12",
                    "is_current": False,
                    "location": "Nashville, Tennessee",
                    "description": None,
                    "skills_used": [],
                    "achievements": [],
                },
            ],
        }

        raw_text = """
WORK EXPERIENCE
Urology Austin
SharePoint Developer
Location: Plano, TX | Duration: Feb 2025 – Present
Caterpillar
SharePoint Data Analyst
Location: Nashville, Tennessee | Duration: Aug 2024 – Dec 2024
EDUCATION
Bradley University
""".strip()

        normalized = _normalize_llm_parse_output_v2(parsed, raw_text)
        entries = normalized.get("experience_entries", [])
        self.assertGreaterEqual(len(entries), 2)

        first = entries[0]
        self.assertEqual(first.get("company"), "Urology Austin")
        self.assertEqual(first.get("title"), "SharePoint Developer")
        self.assertEqual(first.get("location"), "Plano, TX")
        self.assertEqual(first.get("start_date"), "2025-02")

    def test_reuses_current_last_job_when_current_title_missing(self) -> None:
        parsed = {
            "current_last_job": "SharePoint Developer",
            "experience_entries": [
                {
                    "title": None,
                    "company": "Urology Austin",
                    "start_date": "2025-02",
                    "end_date": "Present",
                    "is_current": True,
                    "location": "Plano, TX",
                    "description": None,
                    "skills_used": [],
                    "achievements": [],
                }
            ],
        }

        normalized = _normalize_llm_parse_output_v2(parsed, "WORK EXPERIENCE\nUrology Austin\n")
        entries = normalized.get("experience_entries", [])
        self.assertEqual(entries[0].get("title"), "SharePoint Developer")

    def test_partial_model_output_is_stabilized_by_text_fallback(self) -> None:
        parsed = {
            "full_name": "Yeswanth Naga Harish Perni",
            "skills": [],
            "experience_entries": [
                {
                    "title": None,
                    "company": "Location: Plano, TX | Duration: Feb 2025 – Present",
                    "start_date": "2025-02",
                    "end_date": "Present",
                    "is_current": True,
                    "location": "Plano, TX",
                    "description": None,
                    "skills_used": [],
                    "achievements": [],
                }
            ],
            "current_last_job": "SharePoint Developer",
        }
        raw_text = """
WORK EXPERIENCE
Urology Austin
SharePoint Developer
Location: Plano, TX | Duration: Feb 2025 – Present
Managed Microsoft 365 tenant and automated onboarding with Power Automate.

SKILLS
Microsoft 365, SharePoint Online, Power Automate, Power Apps
""".strip()

        normalized = _normalize_llm_parse_output_v2(parsed, raw_text)
        entries = normalized.get("experience_entries", [])
        skills = [str(item).lower() for item in normalized.get("skills", [])]

        self.assertGreaterEqual(len(entries), 1)
        self.assertEqual(entries[0].get("company"), "Urology Austin")
        self.assertEqual(entries[0].get("title"), "SharePoint Developer")
        self.assertIn("power automate", skills)
        self.assertIn("sharepoint online", skills)


if __name__ == "__main__":
    unittest.main()
