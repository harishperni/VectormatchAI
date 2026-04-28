from __future__ import annotations

import unittest

from app.llm_parse import _normalize_llm_parse_output_v2


class LlmParseConsistencyTests(unittest.TestCase):
    """Regression tests for parser normalization and fallback stability."""

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

    def test_extracts_company_when_location_is_on_same_line(self) -> None:
        parsed = {"experience_entries": []}
        raw_text = """
WORK EXPERIENCE
Vietnam Bank for Social Policies (VBSP) Chennai, India Oct 2011 to Jan 2014
Java / J2EE Developer
Bob Tech, Bangalore, India Aug 2009 to Oct 2010
Software Engineer
EDUCATION
Bachelor of Computer Science
""".strip()

        normalized = _normalize_llm_parse_output_v2(parsed, raw_text)
        entries = normalized.get("experience_entries", [])
        self.assertGreaterEqual(len(entries), 1)
        self.assertEqual(entries[0].get("company"), "Vietnam Bank for Social Policies (VBSP)")
        self.assertEqual(entries[0].get("title"), "Java / J2EE Developer")
        self.assertEqual(entries[0].get("location"), "Chennai, India")

    def test_strips_skill_category_prefix_noise(self) -> None:
        parsed = {
            "skills": [
                "Programming Languages: JAVA",
                "Web Services: SOAP",
                "Databases: Oracle",
                "Methodologies: Agile",
                "Environment: Core JAVA",
                "2.x",
            ]
        }
        normalized = _normalize_llm_parse_output_v2(parsed, "TECHNICAL SKILLS")
        skills = normalized.get("skills", [])
        self.assertIn("JAVA", skills)
        self.assertIn("SOAP", skills)
        self.assertIn("Oracle", skills)
        self.assertIn("Agile", skills)
        self.assertIn("Core JAVA", skills)
        self.assertNotIn("2.x", skills)

    def test_fallback_recovery_fills_missing_descriptions(self) -> None:
        parsed = {
            "experience_entries": [
                {
                    "company": "Union Pacific Railroad",
                    "title": "Senior Java Developer",
                    "location": "Dallas, TX",
                    "start_date": "2015-12",
                    "end_date": "Present",
                    "is_current": True,
                    "description": None,
                    "skills_used": [],
                    "achievements": [],
                },
                {
                    "company": "Misys Financial Services",
                    "title": "Sr Full Stack Java Developer",
                    "location": "Bangalore, India",
                    "start_date": "2014-03",
                    "end_date": "2015-12",
                    "is_current": False,
                    "description": None,
                    "skills_used": [],
                    "achievements": [],
                },
            ]
        }
        raw_text = """
WORK EXPERIENCE
Union Pacific Railroad, Dallas, TX Dec 2015 to Till Date Senior Java Developer
Responsibilities:
Implemented Spring MVC and Hibernate modules.
Built REST APIs and deployed with Jenkins.
Misys Financial Services, Bangalore, India Mar 2014 – Dec 2015
Sr Full Stack Java Developer
Responsibilities:
Developed Java/J2EE services and Hibernate DAO layer.
EDUCATION
Bachelor of Computer Science from Osmania University in 2008.
""".strip()

        normalized = _normalize_llm_parse_output_v2(parsed, raw_text)
        entries = normalized.get("experience_entries", [])
        self.assertGreaterEqual(len(entries), 2)
        self.assertTrue(any(isinstance(item.get("description"), str) and item.get("description") for item in entries))

    def test_extracts_education_when_llm_returns_empty_education(self) -> None:
        normalized = _normalize_llm_parse_output_v2(
            {"education": []},
            "EDUCATION AND CERTIFICATIONS\nBachelor of Computer Science from Osmania University in 2008.",
        )
        education = normalized.get("education", [])
        self.assertGreaterEqual(len(education), 1)
        self.assertIn("Bachelor", str(education[0].get("degree") or ""))
        self.assertIn("Osmania University", str(education[0].get("institution") or ""))

    def test_noisy_llm_skills_fall_back_to_cleaner_extraction(self) -> None:
        parsed = {
            "skills": [
                "Role: Sr.JAVA DEVELOPER Responsibilities:",
                "Developed technical specifications for various back end modules from business requirements.",
                "Involved in consuming and producing Restful web services using JAX-RS.",
                "JAVA",
            ],
            "experience_entries": [
                {
                    "company": "General Motors",
                    "title": "JAVA J2EE Developer",
                    "location": "Detroit, Michigan",
                    "start_date": "2013-01",
                    "end_date": "2014-03",
                    "is_current": False,
                    "description": None,
                    "skills_used": [],
                    "achievements": [],
                }
            ],
        }
        raw_text = """
TECHNICAL SKILLS:
Programming Languages: JAVA, J2EE, SQL
Web Services: SOAP, REST
PROFESSIONAL EXPERIENCE:
General Motors – Detroit, Michigan Jan2013-Mar2014
Role: JAVA J2EE Developer
Environment: Core Java, J2EE, SQL, REST Web Services
""".strip()

        normalized = _normalize_llm_parse_output_v2(parsed, raw_text)
        skills = normalized.get("skills", [])
        self.assertIn("JAVA", skills)
        self.assertIn("J2EE", skills)
        self.assertIn("SQL", skills)
        self.assertNotIn("Role: Sr.JAVA DEVELOPER Responsibilities:", skills)
        self.assertFalse(
            any("Developed technical specifications" in str(item) for item in skills)
        )

    def test_filters_location_timeline_and_role_fragments_from_skills(self) -> None:
        parsed = {
            "skills": [
                "California State Health Department (PHI)",
                "San Jose, CA Mar2014 – Till Date",
                "Role: Sr.JAVA DEVELOPER Responsibilities:",
                "JAVA",
                "J2EE",
                "SQL",
            ]
        }
        raw_text = """
TECHNICAL SKILLS:
Programming Languages: JAVA, J2EE, SQL
PROFESSIONAL EXPERIENCE:
California State Health Department (PHI), San Jose, CA Mar2014 – Till Date
Role: Sr.JAVA DEVELOPER Responsibilities:
""".strip()

        normalized = _normalize_llm_parse_output_v2(parsed, raw_text)
        skills = normalized.get("skills", [])
        self.assertIn("JAVA", skills)
        self.assertIn("J2EE", skills)
        self.assertIn("SQL", skills)
        self.assertFalse(any("San Jose" in str(item) for item in skills))
        self.assertFalse(any("Till Date" in str(item) for item in skills))
        self.assertFalse(any("Role:" in str(item) for item in skills))

    def test_filters_prose_like_skill_fragments(self) -> None:
        parsed = {
            "skills": [
                "automation tools using a ColdFusion front end.",
                "management of multi-step user input flows.",
                "Strong understanding",
                "Java",
                "Spring",
                "Hibernate",
            ],
            "experience_entries": [],
        }
        raw_text = """
TECHNICAL SKILLS:
Programming Languages: Java, SQL
Application Frameworks: Spring, Hibernate
""".strip()
        normalized = _normalize_llm_parse_output_v2(parsed, raw_text)
        skills = [str(item).lower() for item in normalized.get("skills", [])]
        self.assertIn("java", skills)
        self.assertIn("spring", skills)
        self.assertIn("hibernate", skills)
        self.assertNotIn("automation tools using a coldfusion front end.", skills)
        self.assertNotIn("management of multi-step user input flows.", skills)


if __name__ == "__main__":
    unittest.main()
