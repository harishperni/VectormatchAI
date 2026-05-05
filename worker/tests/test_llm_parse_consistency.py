from __future__ import annotations

import unittest

from app.llm_parse import _normalize_llm_parse_output_v2, derive_primary_domain


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

    def test_akhil_style_role_location_and_domain_recovery(self) -> None:
        parsed = {
            "full_name": "Akhil",
            "candidate_location": "8+ years of intensifying experience in multiple roles as Business Analyst, Business Systems Analyst, Scrum Master and achieved titles.",
            "current_last_job": "Scrum Master",
            "skills": ["Java", "Oracle", "JIRA", "SharePoint"],
            "experience_entries": [
                {
                    "company": "Client: JPMorgan Chase",
                    "title": "Scrum Master",
                    "location": None,
                    "start_date": "2016-03",
                    "end_date": "Present",
                    "is_current": True,
                    "description": "Project Description",
                    "skills_used": [],
                    "achievements": [],
                },
                {
                    "company": "Client: Global Payments",
                    "title": None,
                    "location": None,
                    "start_date": "2015-04",
                    "end_date": "2016-02",
                    "is_current": False,
                    "description": "Project Description",
                    "skills_used": [],
                    "achievements": [],
                },
            ],
        }
        raw_text = """
Akhil
Sr. Business Systems Analyst
akhil.mohan0109@gmail.com
Phone no: 510-953-0677 Professional Summary:
8+ years of intensifying experience in multiple roles as Business Analyst, Business Systems Analyst, Scrum Master.
Professional Work Experience:
Client: JPMorgan Chase MAR 2016 to Till Date
Location: Wilmington, Delaware.
Role: Sr. Business Systems Analyst/ Scrum Master
Project Description: Initiated Loan Origination System.
Responsibilities:
Supported multiple product teams.
Environment: Waterfall-Scrum hybrid, JIRA, Confluence, Oracle 11g, Java, SharePoint
Client: Global Payments APR 2015 to FEB 2016
Location: Atlanta, Georgia.
Role: Sr. Business Analyst/Scrum Master
Project Description: Business Glossary migration.
Responsibilities:
Gathered Business requirements.
Environment: SAFe, Agile/Scrum, IBM InfoSphere suite, Oracle, Java, MS VISIO, SharePoint
Education: Bachelor of Technology, JNTU, Hyderabad.
Certifications:
Professional Scrum Master (PSM).
""".strip()

        normalized = _normalize_llm_parse_output_v2(parsed, raw_text)
        entries = normalized.get("experience_entries", [])

        self.assertEqual(normalized.get("candidate_location"), "Wilmington, Delaware")
        self.assertEqual(entries[0].get("location"), "Wilmington, Delaware")
        self.assertEqual(entries[1].get("title"), "Sr. Business Analyst/Scrum Master")
        self.assertEqual(entries[1].get("location"), "Atlanta, Georgia")
        self.assertEqual(
            derive_primary_domain(
                normalized.get("current_last_job"),
                entries,
                normalized.get("skills", []),
            ),
            "Business Analysis / Agile Delivery",
        )

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
        self.assertIn("java", skills)
        self.assertIn("soap", skills)
        self.assertIn("oracle", skills)
        self.assertIn("agile", skills)
        self.assertIn("core java", skills)
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

    def test_extracts_multiple_education_lines_without_experience_year_leak(self) -> None:
        raw_text = """
Education:
Master’s in management information system
Computer Science in Engineering
Tools/Methods Professional Experience
Sr. Business Analyst
University of Texas Dallas, TX Nov 2011-Dec 2013
""".strip()
        normalized = _normalize_llm_parse_output_v2({"education": []}, raw_text)
        education = normalized.get("education", [])
        self.assertGreaterEqual(len(education), 2)
        self.assertIn("Master", str(education[0].get("degree") or ""))
        self.assertIn("management information system", str(education[0].get("field_of_study") or "").lower())
        self.assertIn("Computer Science in Engineering", str(education[1].get("degree") or ""))
        self.assertIsNone(education[0].get("end_date"))
        self.assertIsNone(education[1].get("end_date"))

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
        self.assertIn("java", skills)
        self.assertIn("j2ee", skills)
        self.assertIn("sql", skills)
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
        self.assertIn("java", skills)
        self.assertIn("j2ee", skills)
        self.assertIn("sql", skills)
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

    def test_emits_raw_and_canonical_skills(self) -> None:
        parsed = {
            "skills": ["Java Script", "Node JS", "AWS (Amazon Web Services)", "Hibernate ORM"]
        }
        normalized = _normalize_llm_parse_output_v2(parsed, "TECHNICAL SKILLS")
        self.assertIn("skills_raw", normalized)
        self.assertIn("Java Script", normalized.get("skills_raw", []))
        self.assertIn("javascript", normalized.get("skills", []))
        self.assertIn("nodejs", normalized.get("skills", []))
        self.assertIn("aws", normalized.get("skills", []))
        self.assertIn("hibernate", normalized.get("skills", []))
        self.assertIn("skills_unknown_tokens", normalized)

    def test_tracks_unknown_skill_tokens(self) -> None:
        parsed = {
            "skills": ["Java Script", "MyCustomInternalTool", "FooPlatformX"]
        }
        normalized = _normalize_llm_parse_output_v2(parsed, "TECHNICAL SKILLS")
        unknown = normalized.get("skills_unknown_tokens", [])
        self.assertIn("MyCustomInternalTool", unknown)
        self.assertIn("FooPlatformX", unknown)

    def test_filters_client_location_noise_and_recovers_role_title(self) -> None:
        parsed = {
            "skills": ["Client", "Location", "Pittsburgh", "ServiceNow", "HP ALM", "Over time"],
            "current_last_job": "Environment\\Tools: SDLC Waterfall, HP ALM",
            "experience_entries": [
                {
                    "title": None,
                    "company": "Role:Lead Business Systems Analyst",
                    "start_date": "2016-08",
                    "end_date": "Present",
                    "is_current": True,
                    "location": None,
                    "description": "Environment\\Tools: Service Now, HP ALM",
                    "skills_used": [],
                    "achievements": [],
                }
            ],
        }

        normalized = _normalize_llm_parse_output_v2(parsed, "WORK EXPERIENCE")
        skills = normalized.get("skills", [])
        self.assertIn("servicenow", skills)
        self.assertIn("hp alm", skills)
        self.assertNotIn("client", skills)
        self.assertNotIn("location", skills)
        self.assertNotIn("over time", skills)

        entries = normalized.get("experience_entries", [])
        self.assertGreaterEqual(len(entries), 1)
        self.assertEqual(entries[0].get("title"), "Lead Business Systems Analyst")
        self.assertIsNone(entries[0].get("company"))
        self.assertEqual(normalized.get("current_last_job"), "Lead Business Systems Analyst")

    def test_extracts_inline_environment_tools_skills(self) -> None:
        parsed = {"skills": []}
        raw_text = (
            "Responsibilities: ... Environment\\Tools: Mainframes, SDLC Waterfall, HP ALM, "
            "MS Visio, MS Office Suite, SharePoint, Snagit, SAP, HPQC, QTP. Role: Business Analyst"
        )
        normalized = _normalize_llm_parse_output_v2(parsed, raw_text)
        skills = normalized.get("skills", [])
        self.assertIn("mainframes", skills)
        self.assertIn("sharepoint", skills)
        self.assertIn("sap", skills)
        self.assertIn("hpqc", skills)
        self.assertIn("qtp", skills)

    def test_uses_role_line_when_current_last_job_is_company_name(self) -> None:
        parsed = {
            "current_last_job": "Tata Consultancy Services Ltd.",
            "experience_entries": [],
        }
        raw_text = "Role:Lead Business Systems Analyst August 2016- Till Now"
        normalized = _normalize_llm_parse_output_v2(parsed, raw_text)
        self.assertEqual(normalized.get("current_last_job"), "Lead Business Systems Analyst")

    def test_removes_client_location_from_skills_and_strips_technologies_like(self) -> None:
        parsed = {
            "skills": [
                "technologies like Mainframes",
                "PNC Financial Services",
                "Pittsburgh",
                "ServiceNow",
            ]
        }
        raw_text = """
Client: PNC Financial Services
Location: Pittsburgh, PA
""".strip()
        normalized = _normalize_llm_parse_output_v2(parsed, raw_text)
        skills = normalized.get("skills", [])
        self.assertIn("mainframes", skills)
        self.assertIn("servicenow", skills)
        self.assertNotIn("pnc financial services", skills)
        self.assertNotIn("pittsburgh", skills)

    def test_filters_heading_company_date_and_normalizes_composite_server_skill(self) -> None:
        parsed = {
            "skills": [
                "PROFESSIONAL EXPERIENCE",
                "SYSINTELLIINC",
                "SANDIEGO",
                "FEBURARY 2016 – TILL DATE",
                "Node JS Web Logic Application Server",
                "Java",
            ]
        }
        normalized = _normalize_llm_parse_output_v2(parsed, "TECHNICAL SKILLS")
        skills = normalized.get("skills", [])
        self.assertIn("java", skills)
        self.assertIn("weblogic", skills)
        self.assertNotIn("professional experience", skills)
        self.assertNotIn("sysintelliinc", skills)
        self.assertNotIn("sandiego", skills)
        self.assertNotIn("feburary 2016 till date", skills)

    def test_keeps_versioned_skill_variants_distinct(self) -> None:
        parsed = {
            "skills": [
                "MS Visio V14.0",
                "MS Visio V15.0",
                "Jira V6.3",
                "Jira V6",
            ]
        }
        normalized = _normalize_llm_parse_output_v2(parsed, "TECHNICAL SKILLS")
        skills = normalized.get("skills", [])
        self.assertIn("ms visio v14.0", skills)
        self.assertIn("ms visio v15.0", skills)
        self.assertIn("jira v6.3", skills)
        self.assertIn("jira v6", skills)

    def test_extracts_skills_from_malformed_techntechnical_header(self) -> None:
        parsed = {"skills": []}
        raw_text = """
TECHNTECHNICAL SKILLS:
DWH technologies: OLAP
RDBMS: SQL Server 2000/2005/2008 R2, Oracle 10g
E-Com Frameworks/Web Technologies: VBScripts
EDUCATION:
Bachelor of Engineering
""".strip()
        normalized = _normalize_llm_parse_output_v2(parsed, raw_text)
        skills = normalized.get("skills", [])
        self.assertIn("olap", skills)
        self.assertIn("vbscripts", skills)

    def test_recovers_company_and_state_from_timeline_line(self) -> None:
        parsed = {"experience_entries": []}
        raw_text = """
PROFESSIONAL EXPERIENCE:
Citi Bank, NJ Aug 2016 to till date
Business Analyst, Commercial Banking IT
Responsibilities:
Wrote SQL queries to test the database.
""".strip()
        normalized = _normalize_llm_parse_output_v2(parsed, raw_text)
        entries = normalized.get("experience_entries", [])
        self.assertGreaterEqual(len(entries), 1)
        self.assertEqual(entries[0].get("company"), "Citi Bank")
        self.assertEqual(entries[0].get("location"), "NJ")

    def test_drops_fully_empty_experience_rows(self) -> None:
        parsed = {
            "experience_entries": [
                {
                    "title": "Business Analyst",
                    "company": "Citi Bank",
                    "location": "NJ",
                    "start_date": "2016-08",
                    "end_date": "Present",
                    "is_current": True,
                    "description": "desc",
                    "skills_used": [],
                    "achievements": [],
                },
                {
                    "title": None,
                    "company": None,
                    "location": None,
                    "start_date": None,
                    "end_date": None,
                    "is_current": None,
                    "description": None,
                    "skills_used": [],
                    "achievements": [],
                },
            ]
        }
        normalized = _normalize_llm_parse_output_v2(parsed, "WORK EXPERIENCE")
        entries = normalized.get("experience_entries", [])
        self.assertEqual(len(entries), 1)

    def test_prefers_specific_current_entry_title_over_generic_current_last_job(self) -> None:
        parsed = {
            "current_last_job": "Business Analyst",
            "experience_entries": [
                {
                    "title": "Business Analyst, Commercial Banking IT",
                    "company": "Citi Bank",
                    "location": "NJ",
                    "start_date": "2016-08",
                    "end_date": "Present",
                    "is_current": True,
                    "description": "desc",
                    "skills_used": [],
                    "achievements": [],
                }
            ],
        }
        normalized = _normalize_llm_parse_output_v2(parsed, "PROFESSIONAL EXPERIENCE")
        self.assertEqual(normalized.get("current_last_job"), "Business Analyst, Commercial Banking IT")

    def test_client_block_fallback_and_pmp_title_guard(self) -> None:
        parsed = {
            "current_last_job": "PMP Expiration Date: February 6th 2020",
            "experience_entries": [],
            "skills": [],
            "email": None,
            "phone": None,
            "full_name": None,
        }
        raw_text = """
Amar Agarwal
Amar.srbsa@gmail.com Phone : 201-708-8565
CERTIFICATION:
Project Management Professional (PMP)
PMP Expiration Date: February 6th 2020
Client – Sanofi, Somerset, NJ (September 2016 – till date)
Role\\Designation: Project Manager
Project Description: ...
Technology: OLAP, SQL Server 2014
Client – OKI Europe Limited, New Delhi, India (May 2015 – Aug 2016)
Role\\Designation: Project Manager
Technology: Business Objects 4.0
""".strip()
        normalized = _normalize_llm_parse_output_v2(parsed, raw_text)
        self.assertEqual(normalized.get("full_name"), "Amar Agarwal")
        self.assertEqual(normalized.get("email"), "Amar.srbsa@gmail.com")
        self.assertEqual(normalized.get("phone"), "201-708-8565")
        self.assertEqual(normalized.get("current_last_job"), "Project Manager")
        self.assertGreaterEqual(len(normalized.get("experience_entries", [])), 2)

    def test_mounika_style_name_location_and_company_split_repairs(self) -> None:
        parsed = {
            "full_name": None,
            "candidate_location": "Overall 8+ years of experience in Information technology industry.",
            "experience_entries": [
                {
                    "title": "Sr. Business Analyst",
                    "company": "Office of",
                    "location": "Attorney General Child Support Division, TX",
                    "start_date": "2015-10",
                    "end_date": "Present",
                    "is_current": True,
                    "description": "Environment: ...",
                    "skills_used": [],
                    "achievements": [],
                },
                {
                    "title": "Sr. Business Analyst/Scrum Master",
                    "company": "Environment: Java, Oracle PL/SQL",
                    "location": "University of Texas Dallas, TX",
                    "start_date": "2011-11",
                    "end_date": "2013-12",
                    "is_current": False,
                    "description": "Project description",
                    "skills_used": [],
                    "achievements": [],
                },
            ],
        }
        raw_text = """
Mounika10200@gmail.com Mounika Reddy
414-909-0756 Sr. Business Analyst
Summary
Overall 8+ years of experience in Information technology industry as Business Analyst in Retail, Healthcare, and Finance domains.
""".strip()

        normalized = _normalize_llm_parse_output_v2(parsed, raw_text)
        self.assertEqual(normalized.get("full_name"), "Mounika Reddy")
        self.assertEqual(normalized.get("candidate_location"), "TX")
        entries = normalized.get("experience_entries", [])
        self.assertEqual(entries[0].get("company"), "Office of Attorney General Child Support Division")
        self.assertEqual(entries[0].get("location"), "TX")
        self.assertIsNone(entries[1].get("company"))

    def test_infers_missing_current_location_from_raw_timeline_line(self) -> None:
        parsed = {
            "candidate_location": None,
            "experience_entries": [
                {
                    "title": "Sr. Business Analyst",
                    "company": "Office of Attorney General Child Support Division",
                    "location": None,
                    "start_date": "2015-10",
                    "end_date": "Present",
                    "is_current": True,
                    "description": "Project details",
                    "skills_used": [],
                    "achievements": [],
                },
                {
                    "title": "Sr. Business Analyst",
                    "company": "Atlas air",
                    "location": "NY",
                    "start_date": "2014-02",
                    "end_date": "2015-09",
                    "is_current": False,
                    "description": "Project details",
                    "skills_used": [],
                    "achievements": [],
                },
            ],
        }
        raw_text = """
Office of Attorney General Child Support Division, TX Oct 2015-Present
Atlas air, NY Feb 2014-Sep 2015
""".strip()

        normalized = _normalize_llm_parse_output_v2(parsed, raw_text)
        entries = normalized.get("experience_entries", [])
        self.assertEqual(entries[0].get("location"), "TX")
        self.assertEqual(normalized.get("candidate_location"), "TX")

    def test_brahma_name_line_and_summary_location_guard(self) -> None:
        parsed = {
            "full_name": None,
            "candidate_location": "Summary: 8+ years of experience in Information technology industry.",
            "experience_entries": [
                {
                    "title": "Sr. Business System Analyst",
                    "company": "DST Health Solutions",
                    "location": "Birmingham, AL",
                    "start_date": "2016-07",
                    "end_date": "Present",
                    "is_current": True,
                    "description": "Project details",
                    "skills_used": [],
                    "achievements": [],
                }
            ],
        }
        raw_text = """
Name: Brahma Prathi
Business System Analyst
Summary: 8+ years of experience...
""".strip()
        normalized = _normalize_llm_parse_output_v2(parsed, raw_text)
        self.assertEqual(normalized.get("full_name"), "Brahma Prathi")
        self.assertEqual(normalized.get("candidate_location"), "Birmingham, AL")

    def test_brahma_summary_line_and_cert_education_section_parsing(self) -> None:
        parsed = {
            "professional_summary": None,
            "education": [],
            "certifications": [],
            "skills": [],
            "experience_entries": [
                {
                    "title": "Sr. Business System Analyst",
                    "company": "DST Health Solutions",
                    "location": "Birmingham, AL",
                    "start_date": "2016-07",
                    "end_date": "Present",
                    "is_current": True,
                    "description": "Project details",
                    "skills_used": [],
                    "achievements": [],
                }
            ],
        }
        raw_text = """
Name: Brahma Prathi
Summary: 8+ years of experience, discipline and highly-motivated Business System Analyst with healthcare domain.
CERTIFICATION AND TECHNICAL SKILLS
Languages:
SQL, PL/SQL, XML, Java
Certifications:
SAS Certified Data Mining and Business Intelligence professional
Google Analytics and AdWords Certified Professional
Certified Microsoft Technology Associate (MTA) in .NET
Education:
Master's Degree in Computer Applications
""".strip()

        normalized = _normalize_llm_parse_output_v2(parsed, raw_text)
        self.assertIn("8+ years of experience", str(normalized.get("professional_summary") or ""))
        self.assertGreaterEqual(len(normalized.get("certifications", [])), 2)
        education = normalized.get("education", [])
        self.assertGreaterEqual(len(education), 1)
        self.assertIn("Master", str(education[0].get("degree") or ""))


if __name__ == "__main__":
    unittest.main()
