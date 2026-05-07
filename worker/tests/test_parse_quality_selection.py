from __future__ import annotations

import unittest

from app.main import _choose_best_parse, _choose_best_parse_with_source, build_final_payload


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
        source, _ = _choose_best_parse_with_source(primary, recovered, text)
        self.assertEqual(source, "recovered")

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
        source, _ = _choose_best_parse_with_source(primary, recovered, text)
        self.assertEqual(source, "primary")

    def test_final_payload_repairs_akhil_header_fields(self) -> None:
        parsed = {
            "full_name": "Sr. Business Systems Analyst",
            "candidate_location": "8+ years of intensifying experience in multiple roles as Business Analyst, Business Systems Analyst, Scrum Master and achieved titles.",
            "current_last_job": "Sr. Business Systems Analyst/ Scrum Master",
            "skills": ["Java", "JIRA", "SharePoint"],
            "skills_raw": ["Java", "JIRA", "SharePoint"],
            "education": [],
            "highest_degree": "Master",
            "certifications": [
                {"name": "Scrum Master Accredited Certification (SMAC).", "issuer": None, "date": None, "credential_id": None},
                {"name": "Six Sigma Green Belt certified.", "issuer": None, "date": None, "credential_id": None},
            ],
            "experience_entries": [
                {
                    "title": "Sr. Business Systems Analyst/ Scrum Master",
                    "company": "Client: JPMorgan Chase",
                    "location": "Wilmington, Delaware",
                    "start_date": "2016-03",
                    "end_date": "Present",
                    "is_current": True,
                }
            ],
        }
        text = """
Akhil
Sr. Business Systems Analyst
akhil.mohan0109@gmail.com
Phone no: 510-953-0677 Professional Summary:
8+ years of intensifying experience in multiple roles as Business Analyst, Business Systems Analyst, Scrum Master.
Professional Work Experience:
Client: JPMorgan Chase MAR 2016 to Till Date
Location: Wilmington, Delaware.
Role: Sr. Business Systems Analyst/ Scrum Master
Education: Bachelor of Technology, JNTU, Hyderabad.
Certifications:
Professional Scrum Master (PSM).
Scrum Master Accredited Certification (SMAC).
Six Sigma Green Belt certified.
""".strip()

        final_payload = build_final_payload(parsed, text)
        cert_names = [str(item.get("name") or "") for item in final_payload.get("certifications", [])]

        self.assertEqual(final_payload.get("full_name"), "Akhil")
        self.assertEqual(final_payload.get("candidate_location"), "Wilmington, Delaware")
        self.assertEqual(final_payload.get("highest_degree"), "Bachelor of Technology")
        self.assertEqual(final_payload.get("education")[0].get("institution"), "JNTU")
        self.assertIn("Professional Scrum Master (PSM).", cert_names)

    def test_final_payload_prefers_current_entry_location(self) -> None:
        parsed = {
            "candidate_location": "Atlas air, NY",
            "current_last_job": "Sr. Business Analyst",
            "experience_entries": [
                {
                    "title": "Sr. Business Analyst",
                    "company": "Office of Attorney General Child Support Division, TX",
                    "location": "TX",
                    "start_date": "2015-10",
                    "end_date": "Present",
                    "is_current": True,
                },
                {
                    "title": "Sr. Business Analyst",
                    "company": "Atlas air",
                    "location": "Atlas air, NY",
                    "start_date": "2014-02",
                    "end_date": "2015-09",
                    "is_current": False,
                },
            ],
        }
        final_payload = build_final_payload(parsed, "WORK EXPERIENCE")
        self.assertEqual(final_payload.get("candidate_location"), "TX")


if __name__ == "__main__":
    unittest.main()
