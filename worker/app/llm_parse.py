from __future__ import annotations

import calendar
import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date
from typing import Any

logger = logging.getLogger(__name__)

OPENAI_API_BASE_URL = os.getenv("OPENAI_API_BASE_URL", "https://api.openai.com/v1")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
LLM_PARSE_MODEL = os.getenv(
    "OPENAI_PARSE_MODEL",
    "ft:gpt-4.1-nano-2025-04-14:personal:resume-parser-v2nano500:DNmfuCvx",
).strip()
LLM_PARSE_TIMEOUT = int(os.getenv("LLM_PARSE_TIMEOUT_SECONDS", "90"))
LLM_PARSE_MAX_RETRIES = int(os.getenv("LLM_PARSE_MAX_RETRIES", "4"))

# LLM parse validation/repair settings
LLM_PARSE_VALIDATION_ENABLED = os.getenv("LLM_PARSE_VALIDATION_ENABLED", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
LLM_PARSE_VALIDATION_MODEL = os.getenv("OPENAI_PARSE_VALIDATION_MODEL", "gpt-5-mini").strip()

ATS_RESUME_SCHEMA_DESCRIPTION_V2 = """You are an expert resume parser.

Extract only information explicitly present in the resume text.
Do not infer, guess, invent, rewrite, summarize beyond the text, or move information into a different field.
If a field is not present, return null or [].
Return only valid JSON matching the exact schema.
Do not add extra fields.

Global extraction rules:
- Every returned value must be supported by exact text from the resume.
- Do not use world knowledge, assumptions, or common resume patterns to fill missing data.
- Do not derive contact info, locations, dates, education, certifications, or skills.
- Do not treat section headers, labels, client names, employer names, locations, or sentence fragments as skills.
- Do not duplicate the same information across unrelated fields.

Contact rules:
- Extract full_name, email, phone, candidate_location, LinkedIn, GitHub, and portfolio only if explicitly present.
- If the top line contains labels such as Name, Email, Phone, Current Location, or Visa Status, split each labeled value correctly. Example: "Name: Abiral Pandey Email: x@y.com" means full_name = "Abiral Pandey" only.
- Do not include labels like "Current Location:" in candidate_location. Example: "Current Location: Woonsocket, Rhode Island" means candidate_location = "Woonsocket, Rhode Island".
- Do not use employer locations as candidate_location unless the resume clearly states it as the candidate's location.
- Extract willing_to_relocate only when the resume explicitly says the candidate is willing/open to relocate.

Skills rules:
- Extract skills only from explicit skills/tool sections such as Skills, Key Skills, Technical Skills, Toolkit, Expertise, Technologies, Tools, Tech Stack, or Environment/Tools.
- Skills must be concrete technologies, tools, programming languages, frameworks, databases, cloud platforms, methodologies, or domain skills explicitly listed.
- Do not extract soft skills, responsibilities, verbs, adjectives, business phrases, company names, client names, project names, locations, industries, or section labels as skills.
- Do not convert experience bullet text into skills unless the bullet explicitly names a technology/tool.
- Do not split normal phrases into fake skills.

Experience rules:
- Extract only professional work experience into experience_entries.
- Do not put education, projects, certifications, volunteering, awards, summaries, section headers, or responsibility bullet lines into experience_entries.
- company must be the employer/client/company explicitly shown for that role.
- title must be the explicit job title/role/designation for that role.
- description should contain only the role's explicit responsibilities or bullet text.
- current_last_job must be the most recent explicit job title only, not company, location, summary, or skill.
- is_current should be true only when the role has Present, Current, Till Date, Ongoing, or equivalent explicit text.
- If a resume line follows this format: Company, City, State Job Title followed by a date range on the next line, split it as company = Company, location = City, State, title = Job Title.
- Never use "Professional Experience", "Responsibilities", "Environment", or a responsibility sentence as the company name.
- Never use a responsibility sentence as an employer/company.

Education rules:
- highest_degree must align with the highest explicit degree found in education.
- Do not infer highest_degree from skills, job title, summary, or experience.
- Do not invent institution, field_of_study, GPA, start_date, or end_date.
- For education lines like "Bachelor of Computer Science – University of North Texas, Denton, Texas", degree = "Bachelor of Computer Science", institution = "University of North Texas", and location = "Denton, Texas".
- Do not use the education location as the institution.

Projects rules:
- Extract projects only from explicit project sections such as Projects, Personal Projects, Side Projects, Selected Projects, or Academic Projects.
- Do not create projects from work experience bullets unless the resume has a separate explicit project name/section.
- Keep project URLs only if explicitly present.

Certification rules:
- Keep certifications only if explicitly present in a Certifications, Licenses, Credentials, Training, or Education/Certifications section.
- Do not convert skills, tools, courses, summaries, or responsibilities into certifications.
- Do not invent issuer, date, or credential_id.

Achievements and optional sections:
- Keep achievements empty unless they are explicitly separated and clearly identifiable as achievements/accomplishments/awards.
- Extract awards, volunteering, publications, and languages only if explicitly present in their own section or clearly labeled text.
"""

ATS_RESUME_OUTPUT_SCHEMA_V2 = """{
  "full_name": null,
  "email": null,
  "phone": null,
  "candidate_location": null,
  "willing_to_relocate": null,
  "linkedin_url": null,
  "github_url": null,
  "portfolio_url": null,
  "professional_summary": null,
  "skills": [],
  "languages": [],
  "highest_degree": null,
  "education": [
    {
      "institution": null,
      "degree": null,
      "field_of_study": null,
      "start_date": null,
      "end_date": null,
      "gpa": null,
      "location": null
    }
  ],
  "current_last_job": null,
  "experience_entries": [
    {
      "company": null,
      "title": null,
      "location": null,
      "start_date": null,
      "end_date": null,
      "is_current": null,
      "employment_type": null,
      "description": null,
      "skills_used": [],
      "achievements": []
    }
  ],
  "projects": [
    {
      "name": null,
      "description": null,
      "technologies": [],
      "url": null
    }
  ],
  "certifications": [
    {
      "name": null,
      "issuer": null,
      "date": null,
      "credential_id": null
    }
  ],
  "awards": [],
  "volunteering": [],
  "publications": []
}"""

DEGREE_RANK = {
    "ph.d.": 6,
    "phd": 6,
    "doctorate": 6,
    "doctoral": 6,
    "m.d.": 6,
    "master": 5,
    "m.sc.": 5,
    "ms": 5,
    "m.s.": 5,
    "m.tech.": 5,
    "mba": 5,
    "bachelor": 4,
    "b.sc.": 4,
    "bs": 4,
    "b.s.": 4,
    "b.tech.": 4,
    "ba": 4,
    "b.a.": 4,
    "associate": 3,
    "diploma": 2,
}

MONTH_MAP = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

SKILL_ALIAS_MAP = {
    "js": "javascript",
    "java script": "javascript",
    "javascript": "javascript",
    "ts": "typescript",
    "node js": "nodejs",
    "node.js": "nodejs",
    "nodejs": "nodejs",
    "react js": "react",
    "reactjs": "react",
    "reactjs": "react",
    "react js": "react",
    "angular js": "angularjs",
    "angular.js": "angularjs",
    "mongo db": "mongodb",
    "mongo": "mongodb",
    "aws (amazon web services)": "aws",
    "aws amazon web services": "aws",
    "amazon web services": "aws",
    "rest web services": "rest",
    "rest webservice": "rest",
    "rest webservices": "rest",
    "soap web services": "soap",
    "soap webservice": "soap",
    "soap webservices": "soap",
    "hibernate orm": "hibernate",
    "spring orm": "spring",
    "spring ioc": "spring",
    "spring dao": "spring",
    "spring orm": "spring",
    "spring mvc": "spring mvc",
    "junit": "junit",
    "j unit": "junit",
    "spring framework": "spring",
    "spring boot framework": "spring boot",
    "restful web services": "rest",
    "soap restful web services": "soap",
    "amazon web service": "aws",
    "aws cloud": "aws",
    "git hub": "github",
    "git-hub": "github",
    "power shell": "powershell",
    "c sharp": "c#",
    "post gre sql": "postgresql",
    "postgre sql": "postgresql",
    "my sql": "mysql",
    "mongo db": "mongodb",
    "ms sql": "sql server",
    "mssql": "sql server",
    "web sphere": "websphere",
    "web logic": "weblogic",
    "micro services": "microservices",
    "core java": "java",
    "java/j2ee": "java",
}

PRESENT_WORDS = {
    "present",
    "current",
    "currently",
    "now",
    "today",
    "ongoing",
    "till",
    "till date",
    "till now",
    "to date",
}
MIN_PLAUSIBLE_YEAR = 1950
PRESENT_TOKEN_PATTERN = r"present|current|currently|now|today|ongoing|till(?:\s+(?:date|now))?|to\s+date"

URL_PATTERN = re.compile(r"https?://[^\s|,;]+", re.IGNORECASE)
EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
MONTH_NAME_PATTERN = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t)?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
DATE_RANGE_MONTH_PATTERN = re.compile(
    rf"(?P<smon>{MONTH_NAME_PATTERN})\s*[,/-]?\s*(?P<syear>\d{{4}})\s*(?:-|–|—|to)\s*(?:(?P<emon>{MONTH_NAME_PATTERN})\s*[,/-]?\s*(?P<eyear>\d{{4}})|(?P<present>{PRESENT_TOKEN_PATTERN}))",
    re.IGNORECASE,
)
DATE_RANGE_NUMERIC_PATTERN = re.compile(
    rf"(?P<sm>\d{{1,2}})/(?P<sy>\d{{4}})\s*(?:-|–|—|to)\s*(?:(?P<em>\d{{1,2}})/(?P<ey>\d{{4}})|(?P<present>{PRESENT_TOKEN_PATTERN}))",
    re.IGNORECASE,
)
DATE_RANGE_YEAR_PATTERN = re.compile(
    rf"(?P<sy>\d{{4}})\s*(?:-|–|—|to)\s*(?:(?P<ey>\d{{4}})|(?P<present>{PRESENT_TOKEN_PATTERN}))",
    re.IGNORECASE,
)
DATE_RANGE_MONTH_APOS_PATTERN = re.compile(
    rf"(?P<smon>{MONTH_NAME_PATTERN})\s*[’']?\s*(?P<sy>\d{{2,4}})\s*(?:-|–|—|to)\s*(?:(?P<emon>{MONTH_NAME_PATTERN})\s*[’']?\s*(?P<ey>\d{{2,4}})|(?P<present>{PRESENT_TOKEN_PATTERN}))",
    re.IGNORECASE,
)
DATE_RANGE_ISO_PATTERN = re.compile(
    rf"(?P<siso>\d{{4}}-\d{{2}})\s*(?:-|–|—|to)\s*(?:(?P<eiso>\d{{4}}-\d{{2}})|(?P<present>{PRESENT_TOKEN_PATTERN}))",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DateInterval:
    start: date
    end: date


def _post_chat_completions(payload: dict[str, Any]) -> dict[str, Any] | None:
    if not OPENAI_API_KEY:
        logger.warning("[LLM_PARSE] OPENAI_API_KEY is not set; skipping OpenAI call")
        return None

    url = f"{OPENAI_API_BASE_URL.rstrip('/')}/chat/completions"
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OPENAI_API_KEY}",
        },
        method="POST",
    )

    for attempt in range(1, LLM_PARSE_MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(request, timeout=LLM_PARSE_TIMEOUT) as response:
                raw = response.read().decode("utf-8")
                payload_json = json.loads(raw)
                logger.info(
                    "[LLM_PARSE] OpenAI call succeeded model=%s attempt=%s",
                    payload.get("model", "unknown"),
                    attempt,
                )
                return payload_json
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", errors="ignore")[:2000]
            except Exception:
                detail = str(exc)
            logger.error("[LLM_PARSE] OpenAI HTTPError attempt=%s: %s", attempt, detail)
            return None
        except urllib.error.URLError as exc:
            logger.error("[LLM_PARSE] OpenAI URLError attempt=%s: %s", attempt, exc)
        except TimeoutError:
            logger.error("[LLM_PARSE] OpenAI request timed out attempt=%s", attempt)
        except json.JSONDecodeError:
            logger.error("[LLM_PARSE] OpenAI returned non-JSON response attempt=%s", attempt)
            return None

        if attempt < LLM_PARSE_MAX_RETRIES:
            time.sleep(1.0 * attempt)

    return None


def parse_resume_with_ft_v2(text: str) -> dict[str, Any] | None:
    if not isinstance(text, str) or not text.strip():
        return None

    normalized_text = normalize_resume_text(text)

    system_prompt = (
        f"{ATS_RESUME_SCHEMA_DESCRIPTION_V2}\n\n"
        "OUTPUT SCHEMA\n\n"
        f"{ATS_RESUME_OUTPUT_SCHEMA_V2}"
    )

    payload = {
        "model": LLM_PARSE_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Resume text:\n\n{normalized_text[:24000]}"},
        ],
        "response_format": {"type": "json_object"},
    }

    response = _post_chat_completions(payload)
    if not response:
        logger.warning("[LLM_PARSE] No usable response from OpenAI")
        return None

    parsed = _extract_json_from_openai_response(response)
    if not parsed:
        return None

    normalized = _normalize_llm_parse_output_v2(parsed, normalized_text)
    return _validate_and_repair_resume_parse_if_needed(normalized_text, normalized)


def _extract_json_from_openai_response(response: dict[str, Any]) -> dict[str, Any] | None:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        logger.warning("[LLM_PARSE] OpenAI response missing choices")
        return None

    message = choices[0].get("message", {})
    output = message.get("content")
    if not isinstance(output, str):
        logger.warning("[LLM_PARSE] OpenAI response missing message content")
        return None

    try:
        parsed = json.loads(output)
    except json.JSONDecodeError:
        logger.warning("[LLM_PARSE] OpenAI content was not valid JSON object")
        return None

    return parsed if isinstance(parsed, dict) else None


# --- Resume parse LLM validation/repair ---

def _validate_and_repair_resume_parse_if_needed(raw_text: str, parsed: dict[str, Any]) -> dict[str, Any]:
    if not LLM_PARSE_VALIDATION_ENABLED:
        return parsed
    if not isinstance(parsed, dict):
        return parsed
    if not _resume_parse_needs_llm_validation(parsed, raw_text):
        return parsed

    repaired = _validate_and_repair_resume_parse_with_llm(raw_text, parsed)
    if not isinstance(repaired, dict):
        return parsed

    repaired = _normalize_llm_parse_output_v2(repaired, raw_text)
    if _parse_repair_is_better(parsed, repaired, raw_text):
        repaired["parse_source"] = "validated_repaired"
        return repaired

    return parsed


def _resume_parse_needs_llm_validation(parsed: dict[str, Any], raw_text: str) -> bool:
    if parsed.get("parse_source") == "recovered":
        return True

    entries = parsed.get("experience_entries")
    if not isinstance(entries, list):
        return True

    if _experience_entries_need_fallback(entries, raw_text):
        return True

    for entry in entries:
        if not isinstance(entry, dict):
            return True
        company = _clean_string(entry.get("company")) or ""
        title = _clean_string(entry.get("title")) or ""
        location = _clean_string(entry.get("location")) or ""
        if not company or not title:
            return True
        if len(company.split()) > 12:
            return True
        if re.search(r"(?i)\b(professional experience|responsibilities|environment|technical skills)\b", company):
            return True
        if company.endswith("."):
            return True
        if re.search(r"(?i)\b(developed|implemented|created|configured|responsible|worked|used)\b", company):
            if len(company.split()) > 6:
                return True
        if re.match(r"(?i)^\s*current\s+location\s*:", location):
            return True

    candidate_location = _clean_string(parsed.get("candidate_location"))
    if candidate_location and re.match(r"(?i)^\s*current\s+location\s*:", candidate_location):
        return True

    education = parsed.get("education")
    if isinstance(education, list):
        for item in education:
            if not isinstance(item, dict):
                continue
            institution = _clean_string(item.get("institution")) or ""
            location = _clean_string(item.get("location")) or ""
            if institution and _looks_like_location_text(institution):
                return True
            if institution and location and institution.lower() == location.lower():
                return True

    return False


def _validate_and_repair_resume_parse_with_llm(raw_text: str, parsed: dict[str, Any]) -> dict[str, Any] | None:
    if not OPENAI_API_KEY:
        return None

    validator_prompt = """You are a strict resume parse validator and repair assistant.

Compare the raw resume text against the parsed JSON.
Only correct fields that are clearly wrong based on explicit resume text.
Do not infer, guess, invent, or add unsupported information.
Do not rewrite valid descriptions for style.
Do not remove valid data.
Return only the corrected resume JSON using the same schema as the parsed JSON.
Do not add explanations, comments, confidence scores, issue lists, or extra fields.

Critical checks:
- full_name must not include Email, Phone, Current Location, or Visa Status labels.
- candidate_location must not include labels like "Current Location:".
- Do not use employer/job locations as candidate_location unless explicitly shown as candidate location/header location.
- experience_entries.company must be an employer/client/company, not "Professional Experience", "Responsibilities", "Environment", or a responsibility sentence.
- If a job line is formatted as "Company, City, State Job Title" and the date range is on the next line, split it into company, location, title, and dates correctly.
- Do not use responsibility bullets as company names.
- Education institution and location must not be swapped. For "Bachelor of Computer Science – University of North Texas, Denton, Texas", institution is "University of North Texas" and location is "Denton, Texas".
- Remove malformed skill fragments such as incomplete parenthesis tokens or truncated version tokens only when clearly malformed.
"""

    payload = {
        "model": LLM_PARSE_VALIDATION_MODEL,
        "messages": [
            {"role": "system", "content": validator_prompt},
            {
                "role": "user",
                "content": (
                    "Raw resume text:\n\n"
                    f"{raw_text[:24000]}\n\n"
                    "Parsed JSON to validate and repair:\n\n"
                    f"{json.dumps(parsed, ensure_ascii=False)}"
                ),
            },
        ],
        "response_format": {"type": "json_object"},
    }

    response = _post_chat_completions(payload)
    if not response:
        return None
    return _extract_json_from_openai_response(response)


def _parse_repair_is_better(original: dict[str, Any], repaired: dict[str, Any], raw_text: str) -> bool:
    original_entries = original.get("experience_entries") if isinstance(original, dict) else []
    repaired_entries = repaired.get("experience_entries") if isinstance(repaired, dict) else []

    original_score = _experience_entries_quality_score(original_entries)
    repaired_score = _experience_entries_quality_score(repaired_entries)
    if repaired_score < original_score:
        return False

    if isinstance(repaired_entries, list):
        for entry in repaired_entries:
            if not isinstance(entry, dict):
                return False
            company = _clean_string(entry.get("company")) or ""
            if company and (
                len(company.split()) > 12
                or re.search(r"(?i)\b(professional experience|responsibilities|environment|technical skills)\b", company)
                or company.endswith(".")
            ):
                return False

    if not isinstance(repaired, dict):
        return False
    return True


def _normalize_llm_parse_output_v2(parsed: dict[str, Any], raw_text: str) -> dict[str, Any]:
    def clean(value: Any) -> str | None:
        return _clean_string(value)

    parsed = parsed if isinstance(parsed, dict) else {}

    result: dict[str, Any] = {
        "full_name": clean(parsed.get("full_name")),
        "email": clean(parsed.get("email")),
        "phone": clean(parsed.get("phone")),
        "candidate_location": clean(parsed.get("candidate_location")),
        "willing_to_relocate": _to_optional_bool(parsed.get("willing_to_relocate")),
        "linkedin_url": clean(parsed.get("linkedin_url")),
        "github_url": clean(parsed.get("github_url")),
        "portfolio_url": clean(parsed.get("portfolio_url")),
        "professional_summary": clean(parsed.get("professional_summary")),
        "skills": _unique_clean_strings(parsed.get("skills", [])) if isinstance(parsed.get("skills"), list) else [],
        "skills_raw": [],
        "skills_unknown_tokens": [],
        "languages": _unique_clean_strings(parsed.get("languages", [])) if isinstance(parsed.get("languages"), list) else [],
        "highest_degree": clean(parsed.get("highest_degree")),
        "education": [],
        "current_last_job": clean(parsed.get("current_last_job")),
        "experience_entries": [],
        "projects": [],
        "certifications": [],
        "awards": _unique_clean_strings(parsed.get("awards", [])) if isinstance(parsed.get("awards"), list) else [],
        "volunteering": _unique_clean_strings(parsed.get("volunteering", [])) if isinstance(parsed.get("volunteering"), list) else [],
        "publications": _unique_clean_strings(parsed.get("publications", [])) if isinstance(parsed.get("publications"), list) else [],
    }

    education = parsed.get("education", [])
    if isinstance(education, list):
        result["education"] = [
            _normalize_education_entry_v2(entry)
            for entry in education
            if isinstance(entry, dict)
        ]

    experience_entries = parsed.get("experience_entries", [])
    if isinstance(experience_entries, list):
        result["experience_entries"] = [
            _normalize_experience_entry_v2(entry)
            for entry in experience_entries
            if isinstance(entry, dict)
        ]
    result["experience_entries"] = _repair_experience_entries(
        result.get("experience_entries", []),
        current_last_job=result.get("current_last_job"),
        raw_text=raw_text,
    )

    projects = parsed.get("projects", [])
    if isinstance(projects, list):
        normalized_projects: list[dict[str, Any]] = []
        for project in projects:
            if isinstance(project, str):
                normalized_projects.append(
                    {
                        "name": clean(project),
                        "description": None,
                        "technologies": [],
                        "url": None,
                    }
                )
            elif isinstance(project, dict):
                normalized_projects.append(
                    {
                        "name": clean(project.get("name")),
                        "description": clean(project.get("description")),
                        "technologies": _unique_clean_strings(project.get("technologies", []))
                        if isinstance(project.get("technologies"), list) else [],
                        "url": clean(project.get("url")),
                    }
                )
        result["projects"] = normalized_projects

    certifications = parsed.get("certifications", [])
    if isinstance(certifications, list):
        result["certifications"] = [
            _normalize_certification_entry_v2(entry)
            for entry in certifications
            if isinstance(entry, dict)
        ]
        result["certifications"] = [
            entry
            for entry in result["certifications"]
            if (
                not _is_empty_certification(entry)
                and not _is_invalid_certification_name(entry.get("name"))
            )
        ]

    result["experience_entries"] = sort_experience_entries(result["experience_entries"])

    fallback_entries = _extract_experience_entries_from_text(raw_text)
    header_date_entries = _extract_company_location_title_date_next_line_entries(raw_text)
    if header_date_entries:
        fallback_entries = _merge_experience_entries(fallback_entries, header_date_entries)
    if fallback_entries and (
        _experience_entries_need_fallback(result["experience_entries"], raw_text)
        or _experience_entries_quality_score(
            _merge_experience_entries(result["experience_entries"], fallback_entries)
        )
        > _experience_entries_quality_score(result["experience_entries"])
    ):
        merged_entries = _merge_experience_entries(result["experience_entries"], fallback_entries)
        current_score = _experience_entries_quality_score(result["experience_entries"])
        merged_score = _experience_entries_quality_score(merged_entries)
        fallback_score = _experience_entries_quality_score(fallback_entries)

        if merged_score >= max(current_score, fallback_score):
            result["experience_entries"] = sort_experience_entries(merged_entries)
        elif fallback_score > current_score:
            result["experience_entries"] = sort_experience_entries(fallback_entries)
    result["experience_entries"] = _repair_experience_entries(
        result.get("experience_entries", []),
        current_last_job=result.get("current_last_job"),
    )

    result["projects"] = [item for item in result["projects"] if not _is_empty_project(item)]
    result["education"] = [item for item in result["education"] if not _is_empty_education(item)]
    if not result["education"]:
        result["education"] = _extract_education_from_text(raw_text)
    else:
        # Keep existing parser behavior, but augment when LLM returns only a partial
        # education list and we can reliably recover additional entries from text.
        extracted_education = _extract_education_from_text(raw_text)
        if extracted_education:
            existing_keys = {
                (
                    (_clean_string(item.get("degree")) or "").lower(),
                    (_clean_string(item.get("field_of_study")) or "").lower(),
                    (_clean_string(item.get("institution")) or "").lower(),
                )
                for item in result["education"]
                if isinstance(item, dict)
            }
            for item in extracted_education:
                key = (
                    (_clean_string(item.get("degree")) or "").lower(),
                    (_clean_string(item.get("field_of_study")) or "").lower(),
                    (_clean_string(item.get("institution")) or "").lower(),
                )
                if key in existing_keys:
                    continue
                result["education"].append(item)
                existing_keys.add(key)
    result["education"] = _dedupe_education_entries(result.get("education", []))

    environment_skills = _extract_environment_skills_from_text(raw_text)
    if not result["skills"] and _has_skills_section(raw_text):
        result["skills"] = _extract_skills_from_text(raw_text, result["experience_entries"])
    if environment_skills:
        result["skills"] = _unique_clean_strings([*result["skills"], *environment_skills])

    if _has_certification_section(raw_text):
        extracted_certifications = _extract_certifications_from_text(raw_text)
        if extracted_certifications:
            existing_cert_keys = {
                (_clean_string(item.get("name")) or "").lower()
                for item in result["certifications"]
                if isinstance(item, dict)
            }
            for item in extracted_certifications:
                cert_name = (_clean_string(item.get("name")) or "").lower()
                if cert_name and cert_name not in existing_cert_keys:
                    result["certifications"].append(item)
                    existing_cert_keys.add(cert_name)

    if not result["volunteering"] and _has_volunteering_section(raw_text):
        result["volunteering"] = _extract_volunteering_from_text(raw_text)
    result["volunteering_entries"] = _normalize_volunteering_entries(
        result.get("volunteering", []),
        raw_text,
    )
    if result["volunteering_entries"]:
        result["volunteering"] = _stringify_volunteering_entries(result["volunteering_entries"])

    result["phone"] = _normalize_phone_value(result.get("phone"), raw_text)
    if result["email"] is None:
        result["email"] = _extract_email_from_text(raw_text)
    if result.get("full_name") is None or _looks_like_role_title(result.get("full_name")):
        result["full_name"] = _extract_full_name_from_top(raw_text)
    else:
        top_full_name = _extract_full_name_from_top(raw_text)
        if _should_prefer_top_full_name(result.get("full_name"), top_full_name):
            result["full_name"] = top_full_name
    result["skills"] = _postprocess_skills(
        result.get("skills", []),
        result.get("certifications", []),
        raw_text,
    )
    result["skills"] = _remove_client_location_skill_leakage(result.get("skills", []), raw_text)
    if _skills_need_fallback(result.get("skills", [])):
        extracted_skills = _extract_skills_from_text(raw_text, result.get("experience_entries", []))
        environment_skills = _extract_environment_skills_from_text(raw_text)
        combined = _postprocess_skills(
            [*extracted_skills, *environment_skills],
            result.get("certifications", []),
            raw_text,
        )
        if combined:
            result["skills"] = combined
            result["skills"] = _remove_client_location_skill_leakage(result.get("skills", []), raw_text)
    if len(result.get("skills", [])) <= 1:
        low_signal_skills = _extract_explicit_tech_mentions_from_text(raw_text)
        if low_signal_skills:
            merged = _postprocess_skills(
                [*result.get("skills", []), *low_signal_skills],
                result.get("certifications", []),
                raw_text,
            )
            if merged:
                result["skills"] = _remove_client_location_skill_leakage(merged, raw_text)
    result["skills_raw"] = _unique_clean_strings(result.get("skills", []))
    canonical_skills, unknown_tokens = canonicalize_skill_tokens_with_unknowns(result.get("skills", []))
    result["skills"] = canonical_skills
    result["skills_unknown_tokens"] = unknown_tokens

    if result["professional_summary"] is None:
        result["professional_summary"] = _extract_professional_summary_from_text(raw_text)

    if _looks_like_bad_candidate_location(result.get("candidate_location")):
        result["candidate_location"] = None

    # Do not infer candidate_location from work history locations.
    # Candidate location should only come from explicit resume header/contact info.
    if not result.get("candidate_location"):
        fallback_location = _derive_candidate_location_from_recent_experience(
            result.get("experience_entries", [])
        )
        if fallback_location:
            result["candidate_location"] = fallback_location

    if isinstance(result.get("candidate_location"), str):
        result["candidate_location"] = re.sub(
            r"(?i)^\s*current\s+location\s*:\s*",
            "",
            result["candidate_location"],
        ).strip() or None

    if result["highest_degree"] is None:
        result["highest_degree"] = derive_highest_degree(result["education"])

    if (
        isinstance(result.get("current_last_job"), str)
        and re.match(r"(?i)^\s*(environment|environment\\tools|tools)\s*[:\\]", result["current_last_job"])
    ):
        result["current_last_job"] = None
    if (
        isinstance(result.get("current_last_job"), str)
        and re.search(r"(?i)\b(pmp\s*expiration|certification|pmp number)\b", result["current_last_job"])
    ):
        result["current_last_job"] = None

    if result["current_last_job"] is None:
        result["current_last_job"] = derive_current_last_job(result["experience_entries"])
    if result["current_last_job"] is None:
        inferred_role = _extract_current_role_from_text(raw_text)
        if inferred_role:
            result["current_last_job"] = inferred_role
    specific_current_title = _extract_specific_current_title(result.get("experience_entries", []))
    if specific_current_title and _should_prefer_specific_current_title(
        result.get("current_last_job"),
        specific_current_title,
    ):
        result["current_last_job"] = specific_current_title
    if specific_current_title and isinstance(result.get("current_last_job"), str):
        current_value = _clean_string(result.get("current_last_job")) or ""
        current_company = None
        for entry in result.get("experience_entries", []):
            if isinstance(entry, dict) and entry.get("is_current") is True:
                current_company = _clean_string(entry.get("company"))
                break
        if current_company and current_value.lower() == current_company.lower():
            result["current_last_job"] = specific_current_title
        elif "," in current_value and not _looks_like_probable_job_title(current_value):
            result["current_last_job"] = specific_current_title
    if _looks_like_company_label(result.get("current_last_job")):
        inferred_role = _extract_current_role_from_text(raw_text)
        if inferred_role:
            result["current_last_job"] = inferred_role
    if result["willing_to_relocate"] is None:
        result["willing_to_relocate"] = _infer_willing_to_relocate_from_text(raw_text)

    return result


def _normalize_skill_lookup_key(value: str) -> str:
    token = value.lower()
    token = re.sub(r"[^a-z0-9+#./ -]+", " ", token)
    token = re.sub(r"\s+", " ", token).strip()
    return token


def _has_version_marker(token: str) -> bool:
    # Preserve versioned skills as distinct tokens:
    # e.g. "ms visio v14.0", "oracle 11g", "servlets 2.5", "jsp v2.2"
    return bool(
        re.search(
            r"(?i)\b(v\d+(?:\.\d+){0,2}|\d+(?:\.\d+){1,2}[a-z]?|\d+[a-z])\b",
            token,
        )
    )


def _canonicalize_skill_fallback(token: str) -> str:
    # Reduce common parser noise without requiring explicit aliases for every skill.
    cleaned = token.strip(" .,:;()[]{}")
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"\bframeworks?\b", "framework", cleaned)
    cleaned = re.sub(r"\btechnologies?\b", "technology", cleaned)
    cleaned = re.sub(r"\bweb services?\b", "web service", cleaned)

    # Unify obvious spaced variants.
    cleaned = cleaned.replace("java script", "javascript")
    cleaned = cleaned.replace("node js", "nodejs")
    cleaned = cleaned.replace("react js", "react")
    cleaned = cleaned.replace("angular js", "angularjs")
    cleaned = cleaned.replace("power shell", "powershell")
    cleaned = cleaned.replace("my sql", "mysql")
    cleaned = cleaned.replace("mongo db", "mongodb")
    cleaned = cleaned.replace("web sphere", "websphere")
    cleaned = cleaned.replace("web logic", "weblogic")
    cleaned = cleaned.replace("micro services", "microservices")

    return cleaned.strip()


def canonicalize_skill_tokens_with_unknowns(skills: Any) -> tuple[list[str], list[str]]:
    if not isinstance(skills, list):
        return [], []
    canonical: list[str] = []
    unknown_raw: list[str] = []
    for skill in skills:
        if not isinstance(skill, str):
            continue
        cleaned = _clean_string(skill)
        if not cleaned:
            continue
        # malformed OCR/parser fragments
        if cleaned.count("(") != cleaned.count(")"):
            continue

        if re.fullmatch(r"(?i)java\s+\d", cleaned):
            continue

        if len(cleaned.strip()) <= 2:
            continue

        cleaned = cleaned.strip(".,:- ")
        key = _normalize_skill_lookup_key(cleaned)
        if not key:
            continue
        # Do not normalize versioned variants; keep each explicit version.
        if _has_version_marker(key):
            token = key
            if token not in canonical:
                canonical.append(token)
            if cleaned not in unknown_raw:
                unknown_raw.append(cleaned)
            continue
        token = SKILL_ALIAS_MAP.get(key)
        if token is None:
            token = _canonicalize_skill_fallback(key)
            token = SKILL_ALIAS_MAP.get(token, token)
        if token and token not in canonical:
            canonical.append(token)
        if key == token and len(key) >= 3 and key not in SKILL_ALIAS_MAP:
            if cleaned not in unknown_raw:
                unknown_raw.append(cleaned)
    return canonical, unknown_raw


def canonicalize_skill_tokens(skills: Any) -> list[str]:
    canonical, _ = canonicalize_skill_tokens_with_unknowns(skills)
    return canonical


def _normalize_education_entry_v2(entry: dict[str, Any]) -> dict[str, Any]:
    institution = _clean_string(entry.get("institution"))
    if institution:
        sentence_inst_match = re.search(
            r"(?i)\bfrom\s+([A-Za-z][A-Za-z0-9 .&'/-]{2,100}(?:University|Institute|College))\b",
            institution,
        )
        if sentence_inst_match:
            institution = _clean_string(sentence_inst_match.group(1))
    return {
        "institution": institution,
        "degree": _clean_string(entry.get("degree")),
        "field_of_study": _clean_string(entry.get("field_of_study")),
        "start_date": _clean_education_date_string(entry.get("start_date")),
        "end_date": _clean_education_date_string(entry.get("end_date")),
        "gpa": _clean_string(entry.get("gpa")),
        "location": _clean_string(entry.get("location")),
    }


def _normalize_experience_entry_v2(entry: dict[str, Any]) -> dict[str, Any]:
    is_current = entry.get("is_current")
    raw_start = entry.get("start_date")
    raw_end = entry.get("end_date")
    start_date = _clean_date_string(raw_start)
    end_date = _clean_date_string(raw_end)
    inferred_is_current = is_current if isinstance(is_current, bool) else None

    if (start_date is None or end_date is None) and (
        isinstance(raw_start, str) or isinstance(raw_end, str)
    ):
        range_source = f"{raw_start or ''} {raw_end or ''}".strip()
        inferred_start, inferred_end, inferred_current = _extract_date_range_from_text(range_source)
        if start_date is None:
            start_date = inferred_start
        if end_date is None:
            end_date = inferred_end
        if inferred_is_current is None and inferred_current:
            inferred_is_current = True

    raw_company = _clean_string(entry.get("company"))
    normalized_company = _normalize_company_string(raw_company)
    normalized_title = _clean_experience_title(entry.get("title"))
    if (
        not normalized_title
        and raw_company
        and re.match(r"(?i)^\s*role\s*:", raw_company)
    ):
        normalized_title = _clean_experience_title(re.sub(r"(?i)^\s*role\s*:\s*", "", raw_company))

    return {
        "company": normalized_company,
        "title": normalized_title,
        "location": _clean_string(entry.get("location")),
        "start_date": start_date,
        "end_date": end_date,
        "is_current": inferred_is_current,
        "employment_type": _clean_string(entry.get("employment_type")),
        "description": _trim_experience_description(entry.get("description")),
        "skills_used": _sanitize_skills_used(_unique_clean_strings(entry.get("skills_used", [])))
        if isinstance(entry.get("skills_used"), list) else [],
        "achievements": _unique_clean_strings(entry.get("achievements", []))
        if isinstance(entry.get("achievements"), list) else [],
    }


def _normalize_company_string(value: Any) -> str | None:
    company = _clean_string(value)
    if company and re.fullmatch(
        r"(?i)\s*(professional experience|professional experiences|experience|technical skills|skills|summary)\s*:?\s*",
        company,
    ):
        return None
    if not company:
        return None
    had_client_prefix = bool(re.match(r"(?i)^\s*client\s*:", company))
    if had_client_prefix:
        company = re.sub(r"(?i)^\s*client\s*:\s*", "", company).strip()

    # Drop label-only fragments that frequently appear in malformed OCR/LLM output.
    if re.fullmatch(r"(?i)\s*(location|duration)\s*:?\s*", company):
        return None
    if re.match(r"(?i)^\s*role\s*:", company):
        return None
    if re.match(r"(?i)^\s*(environment|environment\\tools|tools|technology|technologies)\s*:", company):
        return None

    # Remove date range and explicit labels when they bleed into company.
    company = _strip_date_range_from_text(company)
    company = re.sub(r"(?i)\bduration\s*:\s*", " ", company)

    parts = [part.strip() for part in re.split(r"\|", company) if part.strip()]
    cleaned_parts: list[str] = []
    for part in parts:
        fragment = re.sub(r"(?i)\blocation\s*:\s*", "", part).strip()
        fragment = re.sub(r"(?i)^\s*client\s*:\s*", "", fragment).strip()
        if not fragment:
            continue
        location_fragment = _extract_location_fragment(fragment)
        if location_fragment:
            # Preserve organization text even when location is on the same line.
            fragment = re.sub(
                re.escape(location_fragment),
                " ",
                fragment,
                flags=re.IGNORECASE,
            )
            fragment = re.sub(r"\s+", " ", fragment).strip(" |,-")
        if had_client_prefix:
            # "Client: McDonald's, Oak Brook, IL (HCL America)" -> "McDonald's"
            fragment = re.sub(r"\s*\([^)]*\)\s*$", "", fragment).strip(" |,-")
        # Preserve company names that legitimately contain action words.
        if re.fullmatch(r"[A-Za-z0-9 .&'()/,-]{2,120}", fragment):
            cleaned_parts.append(fragment)
            continue
        if not fragment or _looks_like_location_text(fragment):
            continue
        cleaned_parts.append(fragment)

    if cleaned_parts:
        return _clean_string(cleaned_parts[0])

    fallback = re.sub(r"(?i)\blocation\s*:\s*", "", company).strip(" |,-")
    if not fallback or _extract_location_fragment(fallback):
        return None
    return _clean_string(fallback)


def _repair_experience_entries(entries: Any, *, current_last_job: Any, raw_text: str = "") -> list[dict[str, Any]]:
    if not isinstance(entries, list):
        return []

    normalized_entries = [entry for entry in entries if isinstance(entry, dict)]
    normalized_current_title = _clean_string(current_last_job)
    if normalized_current_title and re.match(
        r"(?i)^\s*(environment|environment\\tools|tools)\s*[:\\]",
        normalized_current_title,
    ):
        normalized_current_title = None
    if normalized_current_title and re.search(
        r"(?i)\b(pmp\s*expiration|certification|pmp number)\b",
        normalized_current_title,
    ):
        normalized_current_title = None
    current_filled = False

    repaired: list[dict[str, Any]] = []
    for entry in normalized_entries:
        item = dict(entry)
        raw_company = _clean_string(item.get("company"))
        parsed_client_company = None
        parsed_client_location = None
        if raw_company:
            parsed_client_company, parsed_client_location = _parse_client_company_location_from_line(raw_company)
        item["company"] = _normalize_company_string(raw_company)
        if _looks_like_month_or_date_fragment(item.get("company")):
            item["company"] = None
        item["title"] = _clean_experience_title(item.get("title"))
        if item.get("company") and item.get("title"):
            company_text = _clean_string(item.get("company")) or ""
            title_text = _clean_string(item.get("title")) or ""
            if _looks_like_probable_job_title(company_text) and (
                _looks_like_org_line(title_text) or _extract_location_fragment(title_text) is not None
            ):
                swapped_title = _clean_experience_title(company_text)
                swapped_company = _normalize_company_string(title_text)
                if swapped_title and swapped_company:
                    item["title"] = swapped_title
                    item["company"] = swapped_company
                    if not item.get("location"):
                        loc = _extract_location_fragment(title_text)
                        if loc:
                            item["location"] = loc
        if parsed_client_company:
            item["company"] = parsed_client_company
        if item["title"] and re.match(r"(?i)^\s*(environment|environment\\tools|tools)\s*[:\\]", item["title"]):
            item["title"] = None
        if not item.get("title") and raw_company and re.match(r"(?i)^\s*role\s*:", raw_company):
            derived_title = _clean_experience_title(re.sub(r"(?i)^\s*role\s*:\s*", "", raw_company))
            if derived_title:
                item["title"] = derived_title
        item["location"] = parsed_client_location or _clean_string(item.get("location")) or _extract_location_fragment(
            _clean_string(entry.get("company")) or ""
        )
        if item.get("company") and not item.get("location"):
            split_company, split_location = _split_org_and_region_from_line(str(item["company"]))
            if split_company and split_location:
                item["company"] = split_company
                item["location"] = split_location
        if not item.get("location"):
            inferred_location = _infer_location_from_raw_timeline_line(
                raw_text,
                company=item.get("company"),
                start_date=item.get("start_date"),
            )
            if inferred_location:
                item["location"] = inferred_location
        if not item.get("company"):
            inferred_company = _infer_company_from_raw_timeline_line(
                raw_text,
                start_date=item.get("start_date"),
                title=item.get("title"),
            )
            if inferred_company:
                item["company"] = inferred_company
        if item.get("company") and item.get("location"):
            repaired_company, repaired_location = _repair_company_location_split(
                str(item["company"]),
                str(item["location"]),
            )
            item["company"] = repaired_company
            item["location"] = repaired_location
        item["description"] = _trim_experience_description(item.get("description"))
        if not item.get("title"):
            inferred_title = _extract_title_from_description_prefix(item.get("description"))
            if inferred_title:
                item["title"] = inferred_title
        item["skills_used"] = _sanitize_skills_used(_unique_clean_strings(item.get("skills_used", []))) if isinstance(item.get("skills_used"), list) else []
        item["achievements"] = _unique_clean_strings(item.get("achievements", [])) if isinstance(item.get("achievements"), list) else []
        if isinstance(item.get("title"), str) and re.fullmatch(r"(?i)\s*responsibilities\s*:?\s*", item["title"]):
            continue
        company_text = (_clean_string(item.get("company")) or "").lower().strip()

        if company_text in {
            "professional experience",
            "professional experiences",
            "experience",
            "work experience",
            "technical skills",
            "skills",
            "summary",
        }:
            continue

        if company_text.endswith(":"):
            continue

        if re.fullmatch(r"(?i)[a-z ]+:", company_text):
            continue
        if (
            _looks_like_sentence_fragment(_clean_string(item.get("company")) or "")
            and not any(
                [
                    _clean_string(item.get("title")),
                    _clean_string(item.get("location")),
                    _clean_date_string(item.get("start_date")),
                    _clean_date_string(item.get("end_date")),
                    bool(item.get("is_current")),
                    _clean_string(item.get("description")),
                ]
            )
        ):
            continue
        if _looks_like_education_artifact_experience_entry(item):
            continue
        if not any(
            [
                _clean_string(item.get("company")),
                _clean_string(item.get("title")),
                _clean_string(item.get("location")),
                _clean_date_string(item.get("start_date")),
                _clean_date_string(item.get("end_date")),
                bool(item.get("is_current")),
                _clean_string(item.get("description")),
            ]
        ):
            continue

        if (
            normalized_current_title
            and not item.get("title")
            and item.get("is_current") is True
            and not current_filled
        ):
            item["title"] = normalized_current_title
            current_filled = True

        repaired.append(item)

    return repaired


def _experience_entries_quality_score(entries: Any) -> int:
    if not isinstance(entries, list) or not entries:
        return 0

    score = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if _clean_string(entry.get("company")):
            score += 2
        if _clean_string(entry.get("title")):
            score += 2
        if _clean_string(entry.get("description")):
            score += 2
        if _clean_string(entry.get("location")):
            score += 1
        if _clean_date_string(entry.get("start_date")):
            score += 1
        if _clean_date_string(entry.get("end_date")) or entry.get("is_current") is True:
            score += 1
    return score


def _experience_entries_need_fallback(entries: Any, raw_text: str) -> bool:
    if not isinstance(entries, list):
        return _count_date_ranges(raw_text) >= 2
    if len(entries) <= 1:
        return _count_date_ranges(raw_text) >= 2

    weak_entries = 0
    missing_company_entries = 0
    missing_description_entries = 0
    for entry in entries:
        if not isinstance(entry, dict):
            weak_entries += 1
            missing_company_entries += 1
            missing_description_entries += 1
            continue
        company = _clean_string(entry.get("company"))
        title = _clean_string(entry.get("title"))
        description = _clean_string(entry.get("description"))
        malformed_company = bool(company and re.search(r"(?i)\b(location|duration)\s*:", company))
        if not company:
            missing_company_entries += 1
        if not description:
            missing_description_entries += 1
        if (not title and not description) or malformed_company:
            weak_entries += 1

    if weak_entries >= max(2, len(entries) // 2):
        return True
    if missing_company_entries >= max(2, len(entries) // 2) and _count_date_ranges(raw_text) >= len(entries):
        return True
    if (
        missing_description_entries >= max(2, len(entries) // 2)
        and re.search(r"(?i)\b(responsibilities|environment|project)\s*:?", raw_text)
    ):
        return True
    return False


def _merge_experience_entries(
    primary_entries: Any,
    fallback_entries: Any,
) -> list[dict[str, Any]]:
    if not isinstance(primary_entries, list):
        return fallback_entries if isinstance(fallback_entries, list) else []
    if not isinstance(fallback_entries, list):
        return [entry for entry in primary_entries if isinstance(entry, dict)]

    fallback_by_key: dict[tuple[str | None, str | None, bool], dict[str, Any]] = {}
    fallback_pool: list[dict[str, Any]] = []
    for raw in fallback_entries:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        key = (
            _clean_date_string(item.get("start_date")),
            _clean_date_string(item.get("end_date")),
            bool(item.get("is_current")),
        )
        fallback_by_key[key] = item
        fallback_pool.append(item)

    merged: list[dict[str, Any]] = []
    for raw in primary_entries:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        key = (
            _clean_date_string(item.get("start_date")),
            _clean_date_string(item.get("end_date")),
            bool(item.get("is_current")),
        )
        candidate = fallback_by_key.get(key)
        if not candidate:
            # Last chance match by start date only.
            start = key[0]
            for fallback in fallback_pool:
                if _clean_date_string(fallback.get("start_date")) == start and start is not None:
                    candidate = fallback
                    break

        if candidate:
            if not _clean_string(item.get("company")):
                item["company"] = _normalize_company_string(candidate.get("company"))
            if not _clean_string(item.get("title")):
                item["title"] = _clean_string(candidate.get("title"))
            if not _clean_string(item.get("location")):
                item["location"] = _clean_string(candidate.get("location"))
            if not _clean_string(item.get("description")):
                item["description"] = _trim_experience_description(candidate.get("description"))
            if (not isinstance(item.get("skills_used"), list) or not item.get("skills_used")) and isinstance(candidate.get("skills_used"), list):
                item["skills_used"] = _sanitize_skills_used(_unique_clean_strings(candidate.get("skills_used", [])))

        merged.append(item)

    # Preserve fallback-only rows (for cases where LLM misses a role entirely).
    seen_keys: set[tuple[str | None, str | None, bool]] = set()
    for item in merged:
        if not isinstance(item, dict):
            continue
        seen_keys.add(
            (
                _clean_date_string(item.get("start_date")),
                _clean_date_string(item.get("end_date")),
                bool(item.get("is_current")),
            )
        )

    for raw in fallback_entries:
        if not isinstance(raw, dict):
            continue
        key = (
            _clean_date_string(raw.get("start_date")),
            _clean_date_string(raw.get("end_date")),
            bool(raw.get("is_current")),
        )
        if key in seen_keys:
            continue
        merged.append(dict(raw))
        seen_keys.add(key)

    return merged


def _normalize_certification_entry_v2(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": _clean_string(entry.get("name")),
        "issuer": _clean_string(entry.get("issuer")),
        "date": _clean_date_string(entry.get("date")),
        "credential_id": _clean_string(entry.get("credential_id")),
    }


def _is_empty_project(project: dict[str, Any]) -> bool:
    return (
        not project.get("name")
        and not project.get("description")
        and not project.get("url")
        and not project.get("technologies")
    )


def _is_empty_education(education: dict[str, Any]) -> bool:
    return (
        not education.get("institution")
        and not education.get("degree")
        and not education.get("field_of_study")
        and not education.get("start_date")
        and not education.get("end_date")
        and not education.get("gpa")
        and not education.get("location")
    )


def _dedupe_education_entries(entries: Any) -> list[dict[str, Any]]:
    if not isinstance(entries, list):
        return []
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    seen_soft: set[tuple[str, str, str]] = set()
    for item in entries:
        if not isinstance(item, dict):
            continue
        degree = (_clean_string(item.get("degree")) or "").strip(" .").lower()
        field = (_clean_string(item.get("field_of_study")) or "").strip(" .").lower()
        if not field and " in " in degree:
            prefix, suffix = degree.split(" in ", 1)
            if prefix and suffix:
                degree = prefix.strip()
                field = suffix.strip()
        institution = (_clean_string(item.get("institution")) or "").strip(" .").lower()
        if institution:
            sentence_inst_match = re.search(
                r"(?i)\bfrom\s+([A-Za-z][A-Za-z0-9 .&'/-]{2,100}(?:university|institute|college))\b",
                institution,
            )
            if sentence_inst_match:
                institution = sentence_inst_match.group(1).strip(" .").lower()
        end_date = (_clean_string(item.get("end_date")) or "").strip().lower()
        key = (degree, field, institution, end_date)
        degree_bucket = degree
        if "bachelor" in degree:
            degree_bucket = "bachelor"
        elif "master" in degree:
            degree_bucket = "master"
        elif "diploma" in degree:
            degree_bucket = "diploma"
        elif "phd" in degree or "doctor" in degree:
            degree_bucket = "doctorate"
        soft_key = (degree_bucket, institution, end_date)
        if key in seen:
            continue
        if soft_key in seen_soft:
            continue
        seen.add(key)
        seen_soft.add(soft_key)
        deduped.append(item)
    return deduped


def _is_empty_certification(certification: dict[str, Any]) -> bool:
    return (
        not certification.get("name")
        and not certification.get("issuer")
        and not certification.get("date")
        and not certification.get("credential_id")
    )


def _is_invalid_certification_name(value: Any) -> bool:
    name = _clean_string(value)
    if not name:
        return True
    return bool(
        re.fullmatch(
            r"(?i)\s*(professional experiences?|work experiences?|experience|summary|technical skills?)\s*:?\s*",
            name,
        )
    )


def _has_skills_section(text: str) -> bool:
    return bool(
        re.search(
            r"(?im)^\s*(technical\s+skill(?:-set|s)?|skills?|toolkit|expertise)\s*:?\s*$",
            text,
        )
    )


def _has_certification_section(text: str) -> bool:
    return bool(
        re.search(
            r"(?im)\b(certifications?|education\s*/\s*certi\w*\s*/\s*training)\b",
            text,
        )
    )


def _extract_education_from_text(text: str) -> list[dict[str, Any]]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    block = _extract_section_block(
        text,
        r"^\s*(education(?:al details)?(?: and certifications)?|education & certifications)\s*:?",
        max_lines=30,
    )
    if not block:
        inline_matches = re.findall(
            r"(?im)^\s*education\s*:\s*([^\n.]+(?:\.[^\n]*)?)\s*$",
            text,
        )
        block = [_clean_string(match) for match in inline_matches if _clean_string(match)]
    if not block:
        return []

    stop_pattern = re.compile(
        r"(?i)\b(professional experience|work experience|technical skills|tools/methods|skills)\b"
    )
    degree_pattern = re.compile(
        r"(?i)\b(master(?:['’]s)?|bachelor(?:['’]s)?|ph\.?d|doctorate|associate|diploma)\b"
    )
    institution_pattern = re.compile(
        r"(?i)\b([A-Z][A-Za-z .'-]{3,80}(?:University|Institute|College))\b"
    )
    field_pattern = re.compile(
        r"(?i)\b(?:in|of)\s+([A-Za-z][A-Za-z0-9 &/().'-]{3,80})$"
    )

    entries: list[dict[str, Any]] = []
    for raw in block:
        line = _clean_string(re.sub(r"^[•*\-\s]+", "", raw))
        if not line:
            continue
        if stop_pattern.search(line):
            break
        if len(line) > 140:
            continue

        degree_match = degree_pattern.search(line)
        looks_like_secondary_degree = bool(
            re.search(r"(?i)\bengineering\b", line) and 2 <= len(line.split()) <= 8
        )
        if not degree_match and not looks_like_secondary_degree:
            continue

        degree = None
        field = None
        if degree_match:
            degree = _clean_string(degree_match.group(1))
            degree_phrase_match = re.search(
                r"(?i)\b((?:bachelor|master)(?:['’]s)?(?:\s+of\s+[A-Za-z][A-Za-z &/().'-]{2,60})?)",
                line,
            )
            if degree_phrase_match:
                degree = _clean_string(degree_phrase_match.group(1))
            field_match = field_pattern.search(line)
            if field_match:
                field = _clean_string(field_match.group(1))
        elif looks_like_secondary_degree:
            degree = _clean_string(line)

        institution_match = institution_pattern.search(line)
        institution_value = _clean_string(institution_match.group(1)) if institution_match else None
        if not institution_match:
            dash_parts = [part.strip(" .") for part in re.split(r"\s+[–—-]\s+", line, maxsplit=1) if part.strip(" .")]
            if len(dash_parts) == 2 and degree_match:
                school_and_location = dash_parts[1]
                comma_parts = [part.strip(" .") for part in school_and_location.split(",") if part.strip(" .")]
                if comma_parts:
                    institution_candidate = comma_parts[0]
                    if re.fullmatch(r"[A-Za-z][A-Za-z0-9 .&'-]{1,100}", institution_candidate):
                        institution_value = _clean_string(institution_candidate)
            if not institution_value:
                parts = [part.strip(" .") for part in line.split(",") if part.strip(" .")]
                if len(parts) >= 2 and degree_match:
                    institution_candidate = parts[1]
                    if re.fullmatch(r"[A-Za-z][A-Za-z0-9 .&'-]{1,80}", institution_candidate):
                        institution_value = _clean_string(institution_candidate)
        year_match = re.search(r"\b(19|20)\d{2}\b", line)
        end_date = f"{year_match.group(0)}-06" if year_match else None

        education_location = None
        dash_parts = [part.strip(" .") for part in re.split(r"\s+[–—-]\s+", line, maxsplit=1) if part.strip(" .")]
        if len(dash_parts) == 2:
            comma_parts = [part.strip(" .") for part in dash_parts[1].split(",") if part.strip(" .")]
            if len(comma_parts) >= 3:
                education_location = f"{comma_parts[-2]}, {comma_parts[-1]}"

        entries.append(
            {
                "institution": institution_value,
                "degree": degree,
                "field_of_study": field,
                "start_date": None,
                "end_date": end_date,
                "gpa": None,
                "location": education_location,
            }
        )

    if entries:
        return entries
    return []


def _has_volunteering_section(text: str) -> bool:
    return bool(
        re.search(
            r"(?im)^\s*(volunteering|volunteer(?:\s+experience)?|community\s+involvement)\s*:?\s*$",
            text,
        )
    )


def _extract_section_block(text: str, header_pattern: str, max_lines: int = 60) -> list[str]:
    lines = [line.strip() for line in text.splitlines()]
    in_section = False
    collected: list[str] = []

    for line in lines:
        if not in_section and re.search(header_pattern, line, re.IGNORECASE):
            in_section = True
            inline = re.sub(header_pattern, "", line, flags=re.IGNORECASE).strip(" :-")
            if inline:
                collected.append(inline)
            continue

        if not in_section:
            continue

        if re.fullmatch(
            r"(?i)\s*(professional summary|summary|professional experiences?|work experiences?|experience|education(?:al details)?|technical skills?|skills?|projects?|certifications?|languages?)\s*:?\s*",
            line,
        ):
            break
        if re.fullmatch(r"[A-Z][A-Z /\-&]{3,}:?", line) and collected:
            break
        if re.fullmatch(r"[A-Za-z][A-Za-z /\-&]{3,}:", line) and collected:
            break

        if line:
            collected.append(line)
            if len(collected) >= max_lines:
                break

    return collected


def _extract_skills_from_text(text: str, entries: list[dict[str, Any]]) -> list[str]:
    skill_candidates: list[str] = []

    block = _extract_section_block(
        text,
        r"^\s*((?:technical|techntechnical|technnical|techn\s*technical)\s+skill(?:-set|s)?|skills?|toolkit|expertise)\s*:?\s*$",
        max_lines=80,
    )
    for line in block:
        parts = re.split(r"[:|,;/]", line)
        for part in parts:
            cleaned = _clean_string(part)
            if not cleaned:
                continue
            if len(cleaned) < 2:
                continue
            if cleaned.lower() in {"tools", "methodologies", "database", "other tools", "operating system"}:
                continue
            skill_candidates.append(cleaned)

    for entry in entries:
        for skill in entry.get("skills_used", []) if isinstance(entry.get("skills_used"), list) else []:
            if isinstance(skill, str):
                skill_candidates.append(skill)

    return _unique_clean_strings(skill_candidates)


def _extract_environment_skills_from_text(text: str) -> list[str]:
    skills: list[str] = []
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    header_pattern = re.compile(
        r"(?i)^(environment(?:\s*(?:\\|/)\s*tools)?|tech\s*stack|tools\s*used|technologies)\s*:"
    )

    for line in lines:
        if not header_pattern.match(line):
            continue
        payload = header_pattern.sub("", line).strip()
        if not payload:
            continue

        for part in re.split(r",|;|\|", payload):
            token = _clean_string(part)
            if not token:
                continue
            token = re.sub(r"^[\-\u2022•\s]+", "", token).strip()
            token = re.sub(r"[.]+$", "", token).strip()
            if not token:
                continue
            # Avoid capturing plain labels as skills.
            if token.lower() in {"environment", "tools", "technologies"}:
                continue
            skills.append(token)

    # Also capture inline blocks when OCR/LLM flattens multiple fields into one line:
    # "... Responsibilities ... Environment\Tools: A, B, C. Role: ..."
    inline_pattern = re.compile(
        r"(?i)\b(environment(?:\s*(?:\\|/)\s*tools)?|tech\s*stack|tools\s*used|technologies)\s*:\s*([^\n]+)"
    )
    stop_pattern = re.compile(
        r"(?i)\b(role|project name|client|location|responsibilities)\s*:"
    )
    for match in inline_pattern.finditer(text):
        payload = match.group(2).strip()
        if not payload:
            continue
        stop_match = stop_pattern.search(payload)
        if stop_match:
            payload = payload[: stop_match.start()].strip()
        payload = payload.split(".")[0].strip()
        if not payload:
            continue
        for part in re.split(r",|;|\|", payload):
            token = _clean_string(part)
            if not token:
                continue
            token = re.sub(r"^[\-\u2022•\s]+", "", token).strip()
            token = re.sub(r"[.]+$", "", token).strip()
            if not token:
                continue
            if token.lower() in {"environment", "tools", "technologies"}:
                continue
            skills.append(token)

    return _unique_clean_strings(skills)


def _extract_current_role_from_text(text: str) -> str | None:
    date_cut = re.compile(
        r"(?i)\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s*\d{0,4}.*$|\s+\d{4}.*$"
    )
    for line in text.splitlines():
        stripped = line.strip()
        if not re.match(r"(?i)^role(?:\s*[\\/]\s*designation)?\s*:", stripped):
            continue
        title_part = re.sub(r"(?i)^role(?:\s*[\\/]\s*designation)?\s*:\s*", "", stripped).strip()
        title_part = date_cut.sub("", title_part).strip(" -")
        title = _clean_string(title_part)
        if title:
            return title
    return None


def _looks_like_company_label(value: str | None) -> bool:
    if not value:
        return False
    lower = value.lower().strip()
    return bool(
        re.search(r"\b(ltd|llc|inc|corp|corporation|consultancy|services)\b", lower)
    )


def _extract_certifications_from_text(text: str) -> list[dict[str, Any]]:
    # Zero-hallucination mode: only parse explicit certification-labeled sections.
    block = _extract_section_block(
        text,
        r"(?im)^\s*(certifications?|licenses?|professional certifications?)\s*:?\s*$",
        max_lines=40,
    )
    if not block:
        return []

    certs: list[dict[str, Any]] = []
    for line in block:
        if re.fullmatch(r"(?i)\s*professional experiences?\s*:?\s*", line.strip()):
            continue
        if not re.search(r"(certified|certification|professional|psm|csm|istqb|six sigma|ncfm|qtp|quality center|analytics|adwords|mta|toastmasters)", line, re.IGNORECASE):
            continue
        name = _clean_string(re.sub(r"^[•*\-\s]+", "", line))
        if not name:
            continue
        segments = [seg.strip() for seg in re.split(r"\s*,\s*", name) if seg.strip()]
        split_added = False
        for seg in segments:
            if re.search(r"(?i)(certified|certification|analytics|adwords|mta|toastmasters|professional)", seg):
                certs.append(
                    {
                        "name": seg,
                        "issuer": None,
                        "date": None,
                        "credential_id": None,
                    }
                )
                split_added = True
        if not split_added:
            certs.append(
                {
                    "name": name,
                    "issuer": None,
                    "date": None,
                    "credential_id": None,
                }
            )

    return certs


def _extract_professional_summary_from_text(text: str) -> str | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    # Prefer explicit single-line summary labels first.
    for line in lines[:20]:
        m = re.match(r"(?i)^\s*summary\s*:\s*(.+)$", line)
        if m:
            candidate = _clean_string(m.group(1))
            if candidate and len(candidate.split()) >= 8:
                return candidate

    for idx, line in enumerate(lines):
        if re.fullmatch(r"professional summary:?", line, re.IGNORECASE):
            parts: list[str] = []
            for nxt in lines[idx + 1 : idx + 8]:
                if re.fullmatch(r"[A-Z][A-Z /\-&]{3,}:?", nxt):
                    break
                if re.fullmatch(r"[A-Za-z][A-Za-z /\-&]{3,}:", nxt):
                    break
                parts.append(nxt)
                if len(parts) >= 3:
                    break
            merged = _clean_string(" ".join(parts))
            if merged:
                return merged
    return None


def _extract_full_name_from_top(text: str) -> str | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return None

    # Highest-confidence path: explicit Name line.
    for line in lines[:12]:
        m = re.match(r"(?i)^\s*name\s*:\s*(.+)$", line)
        if not m:
            continue
        candidate = _clean_string(m.group(1))
        candidate = re.split(r"(?i)\b(?:email|phone|current\s+location|visa\s+status)\s*:", candidate)[0].strip(" ,-|")
        if not candidate:
            continue
        if re.search(r"(?i)\b(business system analyst|business analyst|data analyst|quality analyst)\b", candidate):
            continue
        if re.fullmatch(r"[A-Za-z][A-Za-z .'-]{1,80}", candidate) and 2 <= len(candidate.split()) <= 5:
            candidate = re.sub(r"(?i)\bEmployer Details\b", "", candidate).strip(" ,-")
            return candidate

    for line in lines[:6]:
        if "@" in line:
            # Recover names from OCR lines like:
            # "Mounika10200@gmail.com Mounika Reddy"
            candidate = re.sub(EMAIL_PATTERN, " ", line)
            candidate = re.sub(r"\+?\d[\d()\-\s]{7,}\d", " ", candidate)
            candidate = re.sub(
                r"(?i)\b(sr\.?\s*business analyst|business system analyst|business analyst|data analyst|quality analyst|project manager)\b",
                " ",
                candidate,
            )
            candidate = re.sub(r"\s+", " ", candidate).strip(" |,-")
            candidate = re.sub(r"(?i)\bEmployer Details\b", "", candidate).strip(" ,-")
            if re.fullmatch(r"[A-Za-z][A-Za-z .'-]{1,80}", candidate or "") and 2 <= len(candidate.split()) <= 5:
                return _clean_string(candidate)
            continue
        if "@" in line:
            continue
        if re.search(r"\b(phone|email|summary|skills|experience|education|certification)\b", line, re.IGNORECASE):
            continue
        if re.search(r"(?i)\b(business system analyst|business analyst|data analyst|quality analyst|project manager)\b", line):
            continue
        line = re.sub(r"(?i)\bEmployer Details\b", "", line).strip(" ,-")
        line = re.sub(r"\+?\(?\d[\d()\-\s]{7,}\d", " ", line)
        line = re.sub(r"\s+", " ", line).strip(" ,-")
        if re.fullmatch(r"[A-Za-z][A-Za-z .'-]{1,80}", line) and 1 <= len(line.split()) <= 5:
            return _clean_string(line)
    return None


def _should_prefer_top_full_name(current_name: Any, top_name: Any) -> bool:
    current = _clean_string(current_name)
    candidate = _clean_string(top_name)
    if not current or not candidate:
        return False

    current_norm = re.sub(r"[^a-z]", "", current.lower())
    candidate_norm = re.sub(r"[^a-z]", "", candidate.lower())
    if not current_norm or not candidate_norm or current_norm == candidate_norm:
        return False

    current_words = current.split()
    candidate_words = candidate.split()
    if not (2 <= len(current_words) <= 5 and len(current_words) == len(candidate_words)):
        return False

    same_first_name = current_words[0].lower() == candidate_words[0].lower()
    near_match = current_norm.startswith(candidate_norm) or candidate_norm.startswith(current_norm)
    return same_first_name and near_match


def _repair_company_location_split(company: str, location: str) -> tuple[str, str]:
    clean_company = _clean_string(company) or company
    clean_location = _clean_string(location) or location

    # Repair split like:
    # company="YANA Software Pvt." + location="LTD - Hyderabad, INDIA."
    ltd_split_match = re.match(
        r"(?i)^\s*ltd\s*-\s*(.+?)\s*\.?\s*$",
        clean_location,
    )
    if ltd_split_match and not re.search(r"(?i)\bltd\b", clean_company):
        repaired_company = _clean_string(f"{clean_company} LTD")
        repaired_location = _clean_string(ltd_split_match.group(1).strip(" ,.-"))
        if repaired_company and repaired_location:
            return repaired_company, repaired_location

    # Repair cases where city is attached to company using hyphen format.
    # Example: "US Cellular - Chicago" + "IL"
    hyphen_city_match = re.match(
        r"^(.+?)\s+-\s+([A-Za-z][A-Za-z .'-]{1,50})$",
        clean_company,
    )
    if hyphen_city_match and re.fullmatch(r"[A-Z]{2}", clean_location):
        repaired_company = _clean_string(hyphen_city_match.group(1))
        repaired_city = _clean_string(hyphen_city_match.group(2))

        if repaired_company and repaired_city:
            return repaired_company, f"{repaired_city}, {clean_location}"

    # Pattern seen in OCR/LLM output:
    # company="Office of", location="Attorney General Child Support Division, TX"
    if re.search(r"(?i)\bof$", clean_company):
        parts = [part.strip() for part in clean_location.split(",") if part.strip()]
        if len(parts) >= 2:
            region = parts[-1]
            if re.fullmatch(r"[A-Z]{2}", region):
                org_part = ", ".join(parts[:-1]).strip()
                if org_part:
                    merged_company = f"{clean_company} {org_part}".strip()
                    return _clean_string(merged_company) or clean_company, region

    # Recover reversed split:
    # company="PA", location="Premiere Global Services, Pittsburg"
    if re.fullmatch(r"[A-Z]{2}", clean_company):
        parts = [part.strip() for part in clean_location.split(",") if part.strip()]
        if len(parts) == 2:
            org_part, city_part = parts[0], parts[1]
            if _looks_like_org_line(org_part) and re.fullmatch(r"[A-Za-z][A-Za-z .'-]{1,40}", city_part):
                return _clean_string(org_part) or org_part, f"{city_part}, {clean_company}"

    return clean_company, clean_location


def _infer_location_from_raw_timeline_line(raw_text: str, *, company: Any, start_date: Any) -> str | None:
    comp = _clean_string(company)
    if not comp or not raw_text:
        return None

    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    year = None
    if isinstance(start_date, str):
        year_match = re.match(r"^(\d{4})", start_date.strip())
        if year_match:
            year = year_match.group(1)

    for line in lines:
        if comp.lower() not in line.lower():
            continue
        if year and year not in line:
            continue

        # Example: "Office of Attorney General Child Support Division, TX Oct 2015-Present"
        m = re.search(r",\s*([A-Z]{2})\b", line)
        if m:
            return m.group(1)
        loc = _extract_location_fragment(line)
        if loc:
            return loc
    return None


def _infer_company_from_raw_timeline_line(raw_text: str, *, start_date: Any, title: Any) -> str | None:
    if not raw_text:
        return None

    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    year = None
    if isinstance(start_date, str):
        year_match = re.match(r"^(\d{4})", start_date.strip())
        if year_match:
            year = year_match.group(1)

    title_l = (_clean_string(title) or "").lower()

    for idx, line in enumerate(lines):
        if _extract_date_range_from_text(line) == (None, None, False):
            continue
        if year and year not in line:
            continue

        for back in range(1, 4):
            prev_idx = idx - back
            if prev_idx < 0:
                break
            prev = _clean_string(lines[prev_idx])
            if not prev:
                continue
            if re.search(r"(?i)^\s*(professional summary|summary|technical skills?|skills?|education|educational documents)\s*:?\s*$", prev):
                continue
            if _extract_date_range_from_text(prev) != (None, None, False):
                continue
            if title_l and prev.lower() == title_l:
                continue
            if _looks_like_probable_job_title(prev):
                continue
            if _looks_like_month_or_date_fragment(prev):
                continue
            candidate = _normalize_company_string(prev)
            if candidate and not _looks_like_month_or_date_fragment(candidate):
                return candidate

        same_line_company = _normalize_company_string(_strip_date_range_from_text(line))
        if same_line_company and not _looks_like_month_or_date_fragment(same_line_company):
            return same_line_company

    return None


def _derive_candidate_location_from_recent_experience(entries: Any) -> str | None:
    if not isinstance(entries, list):
        return None

    sorted_entries = sort_experience_entries(entries)

    for entry in sorted_entries:
        if not isinstance(entry, dict):
            continue

        location = _clean_string(entry.get("location"))
        if not location:
            continue

        if _looks_like_bad_candidate_location(location):
            continue

        lowered = location.lower()

        if lowered in {
            "india",
            "usa",
            "united states",
        }:
            continue

        if len(location) > 80:
            continue

        return location

    return None


def _extract_volunteering_from_text(text: str) -> list[str]:
    block = _extract_section_block(
        text,
        r"^\s*(volunteering|volunteer(?:\s+experience)?|community\s+involvement)\s*:?\s*$",
        max_lines=50,
    )
    if not block:
        return []

    # Build compact entries from common patterns:
    # role line, org line, optional date line, plus short highlight list.
    entries: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    section_header_pattern = re.compile(
        r"(?i)^\s*(languages?|skills?|education|experience|projects?|certifications?|publications?)\s*:?\s*$"
    )
    section_inline_upper_pattern = re.compile(
        r"(?<!\w)(LANGUAGES?|SKILLS?|EDUCATION|EXPERIENCE|PROJECTS?|CERTIFICATIONS?|PUBLICATIONS?)\s*:?"
    )
    role_hint_pattern = re.compile(
        r"(?i)\b(volunteer|mentor|coach|coordinator|specialist|lead|assistant|member|teacher|facilitator)\b"
    )

    def flush_current() -> None:
        nonlocal current
        if not current:
            return
        if not _clean_string(current.get("role")) and not _clean_string(current.get("org")):
            current = None
            return
        entries.append(current)
        current = None

    cleaned_block: list[tuple[str, bool]] = []
    for raw in block:
        raw_line = re.sub(r"\s+", " ", raw).strip()
        if not raw_line:
            continue

        # Stop once another section header appears (supports two-column OCR where
        # section names may be appended at end of a volunteering line).
        if section_header_pattern.fullmatch(raw_line):
            break

        stop_match = section_inline_upper_pattern.search(raw_line)
        if stop_match:
            prefix = raw_line[: stop_match.start()].strip(" |,-")
            if prefix:
                cleaned_block.append((prefix, bool(re.match(r"^[•*\-]", raw.strip()))))
            break

        cleaned_block.append((raw_line, bool(re.match(r"^[•*\-]", raw.strip()))))

    # Merge wrapped lines so "Implemented ... to" + "enhance ..." becomes one highlight.
    merged_block: list[tuple[str, bool]] = []
    for raw_line, is_bullet in cleaned_block:
        line = _clean_string(re.sub(r"^[•*\-\s]+", "", raw_line))
        if not line:
            continue

        if (
            merged_block
            and not is_bullet
            and not merged_block[-1][0].endswith((".", "!", "?", ":"))
            and not re.match(r"^[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3}$", line)
            and not role_hint_pattern.search(line)
        ):
            prev_text, prev_bullet = merged_block[-1]
            merged_block[-1] = (f"{prev_text} {line}".strip(), prev_bullet)
            continue
        merged_block.append((line, is_bullet))

    for line, is_bullet in merged_block:
        start_date, end_date, is_current = _extract_date_range_from_text(line)
        has_date = bool(start_date or end_date or is_current)

        # A likely new volunteering role starts a new record when current one is already populated.
        if (
            not is_bullet
            and role_hint_pattern.search(line)
            and current
            and (_clean_string(current.get("role")) or _clean_string(current.get("org")))
            and current.get("date")
        ):
            flush_current()

        if has_date:
            if current is None:
                current = {"role": None, "org": None, "date": None, "highlights": []}
            date_free = _clean_string(_strip_date_range_from_text(line))
            if date_free and not current.get("org") and _looks_like_org_line(date_free):
                current["org"] = date_free
            elif date_free and not current.get("role") and _looks_like_volunteer_role_line(date_free):
                current["role"] = date_free
            date_label = " - ".join(
                [
                    value
                    for value in [start_date, end_date or ("Present" if is_current else None)]
                    if value
                ]
            )
            current["date"] = _clean_string(date_label) or _clean_string(line)
            continue

        if is_bullet:
            if current is None:
                current = {"role": None, "org": None, "date": None, "highlights": []}
            highlights = current.get("highlights", [])
            if isinstance(highlights, list) and len(highlights) < 4:
                highlights.append(line)
                current["highlights"] = highlights
            continue

        if current is None:
            current = {"role": line, "org": None, "date": None, "highlights": []}
            continue

        if not current.get("org"):
            if _looks_like_org_line(line):
                current["org"] = line
            else:
                highlights = current.get("highlights", [])
                if isinstance(highlights, list) and len(highlights) < 4:
                    highlights.append(line)
                    current["highlights"] = highlights
            continue

        # If role/org/date already present, treat subsequent text as highlights before opening a new entry.
        if current.get("date"):
            highlights = current.get("highlights", [])
            if isinstance(highlights, list) and len(highlights) < 4:
                highlights.append(line)
                current["highlights"] = highlights
            continue

        flush_current()
        current = {"role": line, "org": None, "date": None, "highlights": []}

    flush_current()

    output: list[str] = []
    for item in entries:
        role = _clean_string(item.get("role"))
        org = _clean_string(item.get("org"))
        date_label = _clean_string(item.get("date"))
        highlights = item.get("highlights") if isinstance(item.get("highlights"), list) else []
        highlights = [_clean_string(h) for h in highlights if _clean_string(h)]

        parts = [part for part in [role, org, date_label] if part]
        if highlights:
            parts.append("; ".join(highlights[:3]))
        merged = _clean_string(" | ".join(parts))
        if merged:
            output.append(merged)

    return _unique_clean_strings(output)


def _looks_like_org_line(value: str) -> bool:
    line = _clean_string(value)
    if not line:
        return False

    lowered = line.lower()
    words = [w for w in re.split(r"\s+", line) if w]
    if len(words) < 2:
        # Allow single-word organization names like "Caterpillar".
        if len(words) == 1 and re.match(r"^[A-Z][A-Za-z&'.-]{2,}$", words[0]):
            return True
        return False
    if line.endswith("."):
        return False
    if re.search(r"\d", line):
        return False

    verb_signals = {
        "developed",
        "implemented",
        "conducted",
        "improved",
        "created",
        "managed",
        "built",
        "enhanced",
        "supported",
        "trained",
        "coordinated",
        "led",
        "helped",
        "assisted",
    }
    if any(f" {verb} " in f" {lowered} " for verb in verb_signals):
        return False

    role_signals = {
        "developer",
        "engineer",
        "analyst",
        "administrator",
        "architect",
        "consultant",
        "intern",
        "manager",
        "specialist",
        "coordinator",
        "lead",
        "officer",
    }
    if any(re.search(rf"\b{signal}\b", lowered) for signal in role_signals):
        return False

    org_signals = {
        "foundation",
        "fund",
        "society",
        "association",
        "organization",
        "committee",
        "nonprofit",
        "charity",
        "community",
        "school",
        "college",
        "university",
        "club",
        "center",
    }
    if any(signal in lowered for signal in org_signals):
        return True

    title_like = sum(1 for w in words if re.match(r"^[A-Z][a-zA-Z&'.-]*$", w))
    return title_like >= max(2, len(words) - 1)


def _looks_like_volunteer_role_line(value: str) -> bool:
    line = _clean_string(value)
    if not line:
        return False
    return bool(
        re.search(
            r"(?i)\b(volunteer|mentor|coach|coordinator|specialist|lead|assistant|member|teacher|facilitator)\b",
            line,
        )
    )


def _strip_date_range_from_text(value: str) -> str:
    cleaned = value
    patterns = [
        DATE_RANGE_MONTH_APOS_PATTERN,
        DATE_RANGE_ISO_PATTERN,
        DATE_RANGE_MONTH_PATTERN,
        DATE_RANGE_NUMERIC_PATTERN,
        DATE_RANGE_YEAR_PATTERN,
    ]
    for pattern in patterns:
        cleaned = pattern.sub(" ", cleaned)
    cleaned = re.sub(r"\s*(?:-|–|—|to)\s*(?:present|current|currently|now|today|ongoing)\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" |,-")
    return cleaned


def _extract_location_fragment(value: str) -> str | None:
    line = _clean_string(value)
    if not line:
        return None
    # Prefer trailing "City, ST" when a client header contains organization, city, state.
    comma_parts = [part.strip() for part in line.split(",") if part.strip()]
    if len(comma_parts) >= 3:
        tail = f"{comma_parts[-2]}, {comma_parts[-1]}"
        tail = re.sub(r"\s*\([^)]*\)\s*$", "", tail).strip()
        if _looks_like_location_text(tail):
            return tail

    trailing_match = re.search(
        r"\b([A-Za-z][A-Za-z .'-]{0,40},\s*(?:[A-Z]{2}|[A-Za-z]+)(?:,\s*(?:USA|US|United States))?)\s*$",
        line,
    )
    if trailing_match:
        candidate = _clean_string(trailing_match.group(1))
        if candidate and _looks_like_location_text(candidate):
            return candidate

    match = re.search(
        r"\b([A-Za-z .'-]+,\s*(?:[A-Z]{2}|[A-Za-z]+)(?:,\s*(?:USA|US|United States))?)\b",
        line,
    )
    if not match:
        return None
    candidate = _clean_string(match.group(1))
    if not candidate:
        return None
    return candidate if _looks_like_location_text(candidate) else None


def _looks_like_location_text(value: str) -> bool:
    text = _clean_string(value)
    if not text:
        return False
    if "," not in text:
        return False

    parts = [part.strip() for part in text.split(",") if part.strip()]
    if len(parts) < 2:
        return False

    city = parts[0]
    region = parts[1]

    # City token should be short and title-like.
    city_words = [w for w in city.split() if w]
    if not city_words or len(city_words) > 5:
        return False
    if any(re.search(r"\d", w) for w in city_words):
        return False
    # Avoid misclassifying employer names as locations (e.g., "Citi Bank, NJ").
    city_lower = city.lower()
    org_city_signals = {
        "bank",
        "insurance",
        "technologies",
        "systems",
        "solutions",
        "university",
        "college",
        "hospital",
        "therapeutics",
        "investments",
        "division",
        "department",
    }
    if any(signal in city_lower for signal in org_city_signals):
        return False

    # Reject obvious sentence fragments accidentally captured as locations.
    lower_text = text.lower()
    sentence_signals = {
        "developed",
        "implemented",
        "conducted",
        "improving",
        "improved",
        "reaching",
        "focused",
        "impacting",
        "collaborated",
        "designed",
        "managed",
        "provided",
        "assisted",
    }
    if any(f" {signal} " in f" {lower_text} " for signal in sentence_signals):
        return False

    # Region should be a US state abbreviation, common US state name, or country marker.
    us_states = {
        "alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut",
        "delaware", "florida", "georgia", "hawaii", "idaho", "illinois", "indiana", "iowa",
        "kansas", "kentucky", "louisiana", "maine", "maryland", "massachusetts", "michigan",
        "minnesota", "mississippi", "missouri", "montana", "nebraska", "nevada", "new hampshire",
        "new jersey", "new mexico", "new york", "north carolina", "north dakota", "ohio",
        "oklahoma", "oregon", "pennsylvania", "rhode island", "south carolina", "south dakota",
        "tennessee", "texas", "utah", "vermont", "virginia", "washington", "west virginia",
        "wisconsin", "wyoming",
    }
    region_clean = region.strip()
    if re.fullmatch(r"[A-Z]{2}", region_clean):
        return True
    if region_clean.lower() in us_states:
        return True
    if region_clean.lower() in {"usa", "us", "united states"}:
        return True
    if re.fullmatch(r"[A-Za-z][A-Za-z .'-]{1,30}", region_clean):
        return True

    return False


def _looks_like_bad_candidate_location(value: Any) -> bool:
    text = _clean_string(value)
    if not text:
        return True
    if len(text) > 80:
        return True
    lower = text.lower()
    if len(text.split()) > 5:
        return True
    if any(signal in lower for signal in ["experience", "years", "summary", "industry", "worked", "project"]):
        return True
    if lower.startswith("summary:"):
        return True
    if re.search(r"[.!?]", text):
        return True
    if "," in text and not _looks_like_location_text(text):
        return True
    return False


def _extract_volunteering_org_and_locations(raw_text: str) -> tuple[list[str], list[str]]:
    block = _extract_section_block(
        raw_text,
        r"^\s*(volunteering|volunteer(?:\s+experience)?|community\s+involvement)\s*:?\s*$",
        max_lines=50,
    )
    if not block:
        return [], []

    section_header_pattern = re.compile(
        r"(?i)^\s*(languages?|skills?|education|experience|projects?|certifications?|publications?)\s*:?\s*$"
    )
    organizations: list[str] = []
    locations: list[str] = []

    for raw in block:
        line = _clean_string(re.sub(r"^[•*\-\s]+", "", raw))
        if not line:
            continue
        if section_header_pattern.fullmatch(line):
            break

        loc = _extract_location_fragment(line)
        if loc:
            locations.append(loc)
            continue

        if _looks_like_volunteer_role_line(line):
            continue
        if _extract_date_range_from_text(line) != (None, None, False):
            continue
        if _looks_like_org_line(line):
            organizations.append(line)

    return _unique_clean_strings(organizations), _unique_clean_strings(locations)


def _parse_volunteering_line(value: str) -> dict[str, Any]:
    parts = [
        part
        for part in (_clean_string(item) for item in re.split(r"\|", value))
        if part
    ]

    role: str | None = None
    organization: str | None = None
    location: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    is_current = False
    highlights: list[str] = []

    for part in parts:
        start, end, current = _extract_date_range_from_text(part)
        if start or end or current:
            start_date = start_date or start
            end_date = end_date or end
            is_current = is_current or current
            continue

        loc = _extract_location_fragment(part)
        if loc and not location:
            location = loc
            continue

        if not role and _looks_like_volunteer_role_line(part):
            role = part
            continue
        if not organization and _looks_like_org_line(part):
            organization = part
            continue

        highlights.append(part)

    if not role and parts:
        role = parts[0]

    if not organization:
        for item in list(highlights):
            if _looks_like_org_line(item) and not _looks_like_volunteer_role_line(item):
                organization = item
                highlights.remove(item)
                break

    return {
        "role": role,
        "organization": organization,
        "location": location,
        "start_date": start_date,
        "end_date": end_date,
        "is_current": bool(is_current),
        "highlights": _unique_clean_strings(highlights)[:4],
    }


def _normalize_volunteering_entries(volunteering: Any, raw_text: str) -> list[dict[str, Any]]:
    if not isinstance(volunteering, list):
        return []

    fallback_orgs, fallback_locations = _extract_volunteering_org_and_locations(raw_text)
    output: list[dict[str, Any]] = []

    for idx, value in enumerate(volunteering):
        if not isinstance(value, str):
            continue
        entry = _parse_volunteering_line(value)

        if not entry.get("organization") and idx < len(fallback_orgs):
            entry["organization"] = fallback_orgs[idx]
        if not entry.get("location") and idx < len(fallback_locations):
            entry["location"] = fallback_locations[idx]

        if not any(
            entry.get(key)
            for key in ["role", "organization", "location", "start_date", "end_date"]
        ) and not entry.get("highlights"):
            continue
        output.append(entry)

    return output


def _stringify_volunteering_entries(entries: Any) -> list[str]:
    if not isinstance(entries, list):
        return []

    output: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        role = _clean_string(entry.get("role"))
        organization = _clean_string(entry.get("organization"))
        location = _clean_string(entry.get("location"))
        start_date = _clean_string(entry.get("start_date"))
        end_date = _clean_string(entry.get("end_date"))
        is_current = bool(entry.get("is_current"))
        highlights = entry.get("highlights") if isinstance(entry.get("highlights"), list) else []
        highlights_clean = [_clean_string(item) for item in highlights if _clean_string(item)]

        date_label = " - ".join(
            [
                part
                for part in [start_date, end_date or ("Present" if is_current else None)]
                if part
            ]
        )
        parts = [part for part in [role, organization, location, date_label] if part]
        if highlights_clean:
            parts.append("; ".join(highlights_clean[:3]))
        merged = _clean_string(" | ".join(parts))
        if merged:
            output.append(merged)

    return _unique_clean_strings(output)


def _count_date_ranges(text: str) -> int:
    return (
        len(DATE_RANGE_MONTH_PATTERN.findall(text))
        + len(DATE_RANGE_NUMERIC_PATTERN.findall(text))
        + len(DATE_RANGE_YEAR_PATTERN.findall(text))
    )


def _normalize_month_token(token: str | None) -> int | None:
    if not token:
        return None
    cleaned = token.strip().lower().rstrip(".")
    return MONTH_MAP.get(cleaned)


def _normalize_year_token(token: str | None) -> int | None:
    if not token:
        return None
    cleaned = token.strip()
    if not cleaned.isdigit():
        return None
    if len(cleaned) == 4:
        value = int(cleaned)
        if MIN_PLAUSIBLE_YEAR <= value <= (date.today().year + 1):
            return value
        return None
    if len(cleaned) == 2:
        value = int(cleaned)
        resolved = 2000 + value if value <= 30 else 1900 + value
        if MIN_PLAUSIBLE_YEAR <= resolved <= (date.today().year + 1):
            return resolved
        return None
    return None


def _normalize_date_token(token: str | None, *, is_end: bool) -> str | None:
    if not token:
        return None
    value = token.strip()
    if not value:
        return None

    if value.lower() in PRESENT_WORDS:
        return "Present"

    if re.fullmatch(r"\d{4}-\d{2}", value):
        return value
    if re.fullmatch(r"\d{4}", value):
        year = int(value)
        if MIN_PLAUSIBLE_YEAR <= year <= (date.today().year + 1):
            return value
        return None

    m = re.fullmatch(r"(?i)\s*(" + MONTH_NAME_PATTERN + r")\s*[’',/-]?\s*(\d{2,4})\s*", value)
    if m:
        month = _normalize_month_token(m.group(1))
        year = _normalize_year_token(m.group(2))
        if month and year:
            return f"{year:04d}-{month:02d}"

    m = re.fullmatch(r"\s*(\d{1,2})/(\d{4})\s*", value)
    if m:
        month = int(m.group(1))
        year = int(m.group(2))
        if 1 <= month <= 12:
            return f"{year:04d}-{month:02d}"

    m = re.search(r"\b(\d{4})\b", value)
    if m:
        year = int(m.group(1))
        if MIN_PLAUSIBLE_YEAR <= year <= (date.today().year + 1):
            return m.group(1)
        return None

    return None


def _extract_date_range_from_text(text: str) -> tuple[str | None, str | None, bool]:
    m = DATE_RANGE_MONTH_APOS_PATTERN.search(text)
    if m:
        start_year = _normalize_year_token(m.group("sy"))
        if start_year is None:
            return None, None, False
        start = _normalize_date_token(f"{m.group('smon')} {start_year}", is_end=False)
        if m.group("present"):
            return start, "Present", True
        end_year = _normalize_year_token(m.group("ey"))
        if end_year is None:
            return start, None, False
        end = _normalize_date_token(f"{m.group('emon')} {end_year}", is_end=True)
        return start, end, False

    m = DATE_RANGE_ISO_PATTERN.search(text)
    if m:
        start = _normalize_date_token(m.group("siso"), is_end=False)
        if m.group("present"):
            return start, "Present", True
        end = _normalize_date_token(m.group("eiso"), is_end=True)
        return start, end, False

    m = DATE_RANGE_MONTH_PATTERN.search(text)
    if m:
        start = _normalize_date_token(f"{m.group('smon')} {m.group('syear')}", is_end=False)
        if m.group("present"):
            return start, "Present", True
        end = _normalize_date_token(f"{m.group('emon')} {m.group('eyear')}", is_end=True)
        return start, end, False

    m = DATE_RANGE_NUMERIC_PATTERN.search(text)
    if m:
        start = _normalize_date_token(f"{m.group('sm')}/{m.group('sy')}", is_end=False)
        if m.group("present"):
            return start, "Present", True
        end = _normalize_date_token(f"{m.group('em')}/{m.group('ey')}", is_end=True)
        return start, end, False

    m = DATE_RANGE_YEAR_PATTERN.search(text)
    if m:
        start = _normalize_date_token(m.group("sy"), is_end=False)
        if m.group("present"):
            return start, "Present", True
        end = _normalize_date_token(m.group("ey"), is_end=True)
        return start, end, False

    return None, None, False


def _extract_experience_entries_from_text(text: str) -> list[dict[str, Any]]:
    lines = [line.strip() for line in _extract_work_experience_block(text).splitlines() if line.strip()]
    entries: list[dict[str, Any]] = []
    date_line_indexes = [
        idx
        for idx, line in enumerate(lines)
        if _extract_date_range_from_text(line) != (None, None, False)
    ]

    for pos, idx in enumerate(date_line_indexes):
        line = lines[idx]
        start_date, end_date, is_current = _extract_date_range_from_text(line)
        if not start_date and not end_date and not is_current:
            continue

        next_entry_idx = date_line_indexes[pos + 1] if pos + 1 < len(date_line_indexes) else len(lines)
        line_without_dates = _strip_date_range_from_text(line)
        client_company, client_location = _parse_client_company_location_from_line(line_without_dates)
        location = client_location or _extract_location_fragment(line_without_dates)
        company = client_company or _normalize_company_string(line_without_dates)
        if not company and location:
            org_from_loc, loc_from_loc = _split_org_and_region_from_line(location)
            if org_from_loc:
                company = org_from_loc
                location = loc_from_loc or location

        # When the date line is just "Location: X | Duration: ...", recover
        # company/title from neighboring lines.
        if not company and idx > 0:
            for back in (1, 2):
                prev_idx = idx - back
                if prev_idx < 0:
                    continue
                prev_line = _clean_string(lines[prev_idx])
                if not prev_line:
                    continue
                if _extract_date_range_from_text(prev_line) != (None, None, False):
                    continue
                if _looks_like_org_line(prev_line):
                    company = _normalize_company_string(prev_line)
                    break

        title = None
        is_location_duration_line = bool(
            re.search(r"\b(location|duration)\b", line, re.IGNORECASE)
        )
        lookahead_title, lookahead_location = _scan_role_and_location_after_date_line(
            lines,
            start_idx=idx + 1,
            end_idx=next_entry_idx,
        )
        if lookahead_location and not location:
            location = lookahead_location
        if lookahead_title:
            title = lookahead_title

        if is_location_duration_line and idx > 0:
            prev_line = lines[idx - 1]
            prev_line_clean = _clean_string(prev_line)
            if (
                prev_line_clean
                and len(prev_line_clean.split()) <= 14
                and not re.search(r"(location|duration|project|education|experience)", prev_line_clean, re.IGNORECASE)
                and not _looks_like_org_line(prev_line_clean)
            ):
                title = prev_line_clean

        if not title and idx + 1 < len(lines):
            next_line = lines[idx + 1]
            next_line_clean = _clean_string(next_line)
            if (
                next_line_clean
                and len(next_line_clean.split()) <= 10
                and not next_line_clean.endswith(".")
                and not re.search(r"(role and responsibilities|technologies|project|education)", next_line_clean, re.IGNORECASE)
                and not _looks_like_org_line(next_line_clean)
            ):
                title = next_line_clean

        if not title and idx > 0:
            prev_line = lines[idx - 1]
            prev_line_clean = _clean_string(prev_line)
            if (
                prev_line_clean
                and len(prev_line_clean.split()) <= 14
                and not re.search(r"(location|duration|project|education|experience)", prev_line_clean, re.IGNORECASE)
                and not _looks_like_org_line(prev_line_clean)
            ):
                title = prev_line_clean

        description_start = idx + 1
        if title and idx + 1 < len(lines):
            maybe_title_line = _clean_string(lines[idx + 1])
            if maybe_title_line and title == maybe_title_line:
                description_start = idx + 2

        description_lines: list[str] = []
        for desc_idx in range(description_start, next_entry_idx):
            desc_line = _clean_string(lines[desc_idx])
            if not desc_line:
                continue
            if re.fullmatch(r"(?i)(responsibilities|environment|project)\s*:?", desc_line):
                continue
            description_lines.append(desc_line)
        description = _trim_experience_description(" ".join(description_lines)) if description_lines else None

        entries.append(
            {
                "company": company,
                "title": title,
                "location": location,
                "start_date": start_date,
                "end_date": end_date,
                "is_current": bool(is_current),
                "employment_type": None,
                "description": description,
                "skills_used": [],
                "achievements": [],
            }
        )

    cleaned_entries = [
        item
        for item in entries
        if item.get("company") or item.get("title") or item.get("start_date") or item.get("end_date")
    ]
    return sort_experience_entries(cleaned_entries)


def _scan_role_and_location_after_date_line(
    lines: list[str],
    *,
    start_idx: int,
    end_idx: int,
) -> tuple[str | None, str | None]:
    title: str | None = None
    location: str | None = None

    hard_stop = re.compile(
        r"(?i)^\s*(project\s+description|responsibilities|environment|education|certifications?|skills?)\s*:?"
    )
    role_pattern = re.compile(r"(?i)^\s*role(?:\s*[\\/]\s*designation)?\s*:\s*(.+?)\s*$")
    location_pattern = re.compile(r"(?i)^\s*location\s*:\s*(.+?)\s*$")

    for raw in lines[start_idx : min(end_idx, start_idx + 8)]:
        line = _clean_string(raw)
        if not line:
            continue

        location_match = location_pattern.match(line)
        if location_match and not location:
            candidate_location = _extract_location_fragment(location_match.group(1)) or _clean_string(
                location_match.group(1).strip(" .")
            )
            if candidate_location and not _looks_like_bad_candidate_location(candidate_location):
                location = candidate_location
            continue

        role_match = role_pattern.match(line)
        if role_match and not title:
            candidate_title = _clean_string(role_match.group(1))
            if candidate_title and not _looks_like_org_line(candidate_title):
                title = candidate_title
            continue

        if hard_stop.match(line):
            break

    return title, location


def _extract_work_experience_block(text: str) -> str:
    lines = text.splitlines()
    start_idx: int | None = None
    end_idx: int | None = None

    for i, raw in enumerate(lines):
        line = raw.strip()
        if start_idx is None and re.fullmatch(
            r"(?i)(work experience|professional experience|professional profile|employment history|career history|work history|relevant experience|industry experience|consulting experience|experience)",
            line.rstrip(":"),
        ):
            start_idx = i + 1
            continue

        if start_idx is not None and re.fullmatch(
            r"(?i)(education|educational details|educational documents|skills|certifications|additional information|technical skills)",
            line.rstrip(":"),
        ):
            end_idx = i
            break

    if start_idx is None:
        # Gated fallback for resumes that enumerate jobs by repeated
        # "Client - ..." lines but lack a clean "Experience" section header.
        client_line_indexes = [
            i
            for i, raw in enumerate(lines)
            if re.match(r"(?i)^\s*client\s*[–\-:]", raw.strip())
        ]
        if len(client_line_indexes) >= 2:
            start_idx = client_line_indexes[0]
        else:
            return text
    if end_idx is None:
        end_idx = len(lines)
    return "\n".join(lines[start_idx:end_idx])


def estimate_experience_years_from_text(text: str) -> float | None:
    entries = _extract_experience_entries_from_text(text)
    return calculate_experience_years_from_entries(entries)


def count_date_ranges_in_text(text: str) -> int:
    return _count_date_ranges(text)


def _clean_education_date_string(value: Any) -> str | None:
    normalized = _clean_date_string(value)
    if normalized and re.fullmatch(r"\d{4}", normalized):
        return f"{normalized}-06"
    return normalized


def _trim_experience_description(value: Any, max_sentences: int = 20) -> str | None:
    cleaned = _clean_string(value)
    if not cleaned:
        return None

    # Remove noisy prefixed labels that often leak from OCR/LLM extraction.
    cleaned = re.sub(r"(?i)^\s*role\s*:\s*[^:]{0,120}?\s*(?=description\s*:)", "", cleaned).strip()
    cleaned = re.sub(r"(?i)^\s*description\s*:\s*", "", cleaned).strip()

    # Keep the core project/role description, not full responsibilities/environment dump.
    stop_match = re.search(r"(?i)\b(responsibilities|environment)\s*:", cleaned)
    if stop_match:
        cleaned = cleaned[: stop_match.start()].strip()

    # If still very long, keep only the first paragraph-like chunk.
    para_split = re.split(r"(?<=[.!?])\s+(?=[A-Z][a-z])", cleaned)
    if para_split:
        cleaned = para_split[0].strip()

    # Hard cap to keep concise per-role description.
    if len(cleaned) > 700:
        cleaned = cleaned[:700].rsplit(" ", 1)[0].strip() + "..."

    # Keep full sentences only, capped to a manageable size per experience block.
    sentences = [
        part.strip()
        for part in re.split(r"(?<=[.!?])\s+", cleaned)
        if part and part.strip()
    ]
    if len(sentences) <= max_sentences:
        return cleaned

    return " ".join(sentences[:max_sentences]).strip()


def normalize_resume_text(text: str) -> str:
    if not isinstance(text, str):
        return ""

    text = text.replace("\x00", " ")
    text = re.sub(r"\r\n?", "\n", text)

    # Merge likely broken PDF line wraps such as:
    # "Progressive Web" + "Apps" -> "Progressive Web Apps"
    lines = text.split("\n")
    merged_lines = []
    i = 0

    while i < len(lines):
        current = lines[i].strip()

        if i < len(lines) - 1:
            nxt = lines[i + 1].strip()

            if (
                current
                and nxt
                and len(current.split()) <= 3
                and len(nxt.split()) <= 2
                and not current.endswith(":")
                and not nxt.isupper()
                and not re.fullmatch(r"\d{4}(-\d{2})?", current)
                and not re.fullmatch(r"\d{4}(-\d{2})?", nxt)
            ):
                merged_lines.append(f"{current} {nxt}")
                i += 2
                continue

        merged_lines.append(current)
        i += 1

    text = "\n".join(merged_lines)

    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _clean_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = re.sub(r"\s+", " ", value).strip()
    return value or None


def _to_optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"yes", "true", "y"}:
            return True
        if lowered in {"no", "false", "n"}:
            return False
    return None


def _infer_willing_to_relocate_from_text(text: str) -> bool | None:
    raw = (text or "").lower()
    if not raw:
        return None

    negative_patterns = [
        r"\bnot willing to relocat(?:e|ion)\b",
        r"\bunwilling to relocat(?:e|ion)\b",
        r"\brelocat(?:ion|e)\s+(?:not available|not possible|cannot)\b",
        r"\bno relocation\b",
    ]
    positive_patterns = [
        r"\bwilling to relocat(?:e|ion)\b",
        r"\bopen to relocat(?:e|ion)\b",
        r"\bavailable for relocat(?:e|ion)\b",
        r"\bready to relocat(?:e|ion)\b",
        r"\brelocat(?:ion|e)\s+available\b",
    ]

    if any(re.search(pattern, raw, re.IGNORECASE) for pattern in negative_patterns):
        return False
    if any(re.search(pattern, raw, re.IGNORECASE) for pattern in positive_patterns):
        return True
    return None


def _postprocess_skills(skills: Any, certifications: Any, raw_text: str = "") -> list[str]:
    if not isinstance(skills, list):
        return []

    normalized_candidates: list[str] = []
    for value in skills:
        if not isinstance(value, str):
            continue
        normalized_candidates.extend(_split_skill_candidate(value))

    cert_names: list[str] = []
    if isinstance(certifications, list):
        for cert in certifications:
            if isinstance(cert, dict):
                name = _clean_string(cert.get("name"))
                if name:
                    cert_names.append(name.lower())
    dynamic_short_allowlist = _extract_dynamic_short_skill_allowlist(raw_text)

    filtered: list[str] = []
    for token in _unique_clean_strings(normalized_candidates):
        cleaned_token = _strip_skill_category_prefix(token)
        if not cleaned_token:
            continue
        cleaned_token = cleaned_token.strip(" \t\r\n.;:()[]{}")
        if not cleaned_token:
            continue
        cleaned_token = _normalize_composite_skill_token(cleaned_token)
        if not cleaned_token:
            continue

        lowered = cleaned_token.lower()
        if re.search(r"\b(certification|certified|certificate|credential)\b", lowered):
            continue
        if re.search(r"\b(fundamentals|associate|professional|mcp)\b", lowered):
            continue
        if lowered in {
            "programming languages",
            "j2ee technologies",
            "web technologies",
            "databases",
            "xml technologies",
            "web services",
            "methodologies",
            "operating systems",
            "application frameworks",
            "version control",
            "other tools",
            "tools",
            "ides",
            "application servers",
            "application",
            "web",
            "tests",
            "ci",
            "cd",
            "vcs",
            "back-end",
        }:
            continue
        if re.fullmatch(r"\d+(?:\.\d+|\.x|x)?", lowered):
            continue
        if _looks_like_non_skill_phrase(cleaned_token):
            continue
        if _is_generic_non_skill_token(cleaned_token):
            continue
        if _looks_like_sentence_fragment(cleaned_token):
            continue
        if not _should_keep_skill_token(cleaned_token, dynamic_short_allowlist):
            continue
        if cert_names and any(lowered == name or lowered in name or name in lowered for name in cert_names):
            continue
        filtered.append(cleaned_token)

    normalized = _unique_clean_strings(filtered)

    filtered_skills = []

    for skill in normalized:
        lowered = skill.lower().strip()

        if lowered in {
            "java 1",
            "adobe (cq5",
            "tools",
            "technologies",
            "environment",
        }:
            continue

        if lowered.endswith("("):
            continue

        if lowered.count("(") != lowered.count(")"):
            continue

        filtered_skills.append(skill)

    normalized = filtered_skills

    dedupe_map = {
        "core java": "java",
        "java/j2ee": "java",
        "aws cloud": "aws",
        "soap webservice": "soap",
        "soap webservices": "soap",
    }

    collapsed = []

    for skill in normalized:
        lowered = skill.lower().strip()
        collapsed_skill = dedupe_map.get(lowered, skill)

        if collapsed_skill not in collapsed:
            collapsed.append(collapsed_skill)

    normalized = collapsed

    return _unique_clean_strings(normalized)


def _extract_dynamic_short_skill_allowlist(raw_text: str) -> set[str]:
    allow: set[str] = set()
    if not raw_text:
        return allow

    section_patterns = [
        r"(?im)^\s*(technical skills?|tools(?:\s*&\s*environments?)?|tools|environment(?:\s*(?:\\|/)\s*tools)?|languages?)\s*:?\s*$",
    ]
    blocks: list[str] = []
    for pattern in section_patterns:
        for line in _extract_section_block(raw_text, pattern, max_lines=40):
            cleaned = _clean_string(line)
            if cleaned:
                blocks.append(cleaned)

    # Also reuse parsed environment lines to capture explicit short tokens.
    blocks.extend(_extract_environment_skills_from_text(raw_text))

    for line in blocks:
        for part in re.split(r"[,;|()/\s]+", line):
            tok = _clean_string(part)
            if not tok:
                continue
            lowered = tok.lower()
            compact = re.sub(r"[^a-z0-9+#.]", "", lowered)
            if not compact:
                continue
            if compact in {"c", "r", "js", "ts", "sql", "etl", "ui", "ux", "qa", "ai", "ml", "bi"}:
                allow.add(compact)
            if lowered in {"c#", "c++", ".net"}:
                allow.add(lowered)
    return allow


def _normalize_composite_skill_token(token: str) -> str | None:
    lowered = token.lower().strip()
    if not lowered:
        return None

    # Collapse composite "application server" phrase noise.
    if "application server" in lowered:
        if "weblogic" in lowered or "web logic" in lowered:
            return "WebLogic"
        if "jboss" in lowered:
            return "JBoss"
        if "tomcat" in lowered:
            return "Apache Tomcat"

    return token


def _strip_skill_category_prefix(value: str) -> str | None:
    cleaned = _clean_string(value)
    if not cleaned:
        return None

    stripped = re.sub(
        r"(?i)^\s*(programming languages?|j2ee technologies?|web technologies?|databases?|xml technologies?|web services?|methodologies?|operating systems?|application frameworks?|version control(?:\s+tools?)?|other tools?|tools?|ides?|application\/web server|environment|technologies used)\s*:\s*",
        "",
        cleaned,
    ).strip()
    stripped = re.sub(r"(?i)^\s*technolog(?:y|ies)\s+like\s+", "", stripped).strip()
    return stripped or None


def _remove_client_location_skill_leakage(skills: Any, raw_text: str) -> list[str]:
    if not isinstance(skills, list):
        return []

    blocked: set[str] = set()
    for line in raw_text.splitlines():
        text = _clean_string(line)
        if not text:
            continue
        client_match = re.match(r"(?i)^client\s*:\s*(.+)$", text)
        if client_match:
            client = _clean_string(client_match.group(1))
            if client:
                blocked.add(client.lower())
            continue
        location_match = re.match(r"(?i)^location\s*:\s*(.+)$", text)
        if location_match:
            loc = _clean_string(location_match.group(1))
            if loc:
                blocked.add(loc.lower())
                city = _clean_string(loc.split(",")[0])
                if city:
                    blocked.add(city.lower())

    cleaned_skills: list[str] = []
    for token in skills:
        if not isinstance(token, str):
            continue
        normalized = token.strip().lower()
        if not normalized:
            continue
        if normalized in blocked:
            continue
        cleaned_skills.append(token)
    return _unique_clean_strings(cleaned_skills)


def _looks_like_non_skill_phrase(token: str) -> bool:
    lowered = token.lower().strip()
    if not lowered:
        return True

    words = [w for w in re.split(r"\s+", lowered) if w]
    if len(words) >= 8:
        return True
    if len(token) > 60:
        return True

    if re.search(r"(?i)\b(responsibilities|developed|worked|involved|designed|implemented|managed|provided|participated|coordinated)\b", token):
        return True
    if re.search(r"(?i)\b(understanding|conducted|interviewed|maintaining|decision making|proposed|solution specifications|volume estimates)\b", token):
        return True
    if re.search(r"(?i)\b(for\s+payments|client relations|supporting strategy|business modeling|invitations to tender|company strategy)\b", token):
        return True
    if re.search(r"(?i)\b(analysis|information|knowledge|policies|policy|eligibility)\b", token) and len(words) >= 2:
        return True
    if re.search(r"(?i)\b(test planning|crm\s*&?\s*workflow|requirements specifications)\b", token):
        return True
    if re.search(r"(?i)\b(environment|technologies used|role)\b", token):
        return True
    if re.search(r"(?i)\b(jan\w*|feb\w*|mar\w*|apr\w*|may|jun\w*|jul\w*|aug\w*|sep\w*|sept\w*|oct\w*|nov\w*|dec\w*)\s*[-,]?\s*\d{2,4}\b", token):
        return True
    if re.search(r"(?i)\b(till date|present|current)\b", token):
        return True
    if re.search(r"\b(19|20)\d{2}\b", token):
        return True
    if re.search(r"(?i)\b(role\s*:|responsibilities\s*:)\b", token):
        return True
    if re.search(r"(?i)^\s*(client|location|project name)\s*:", token):
        return True
    if re.search(r"(?i)\b[A-Za-z .'-]+,\s*(?:[A-Z]{2}|[A-Za-z]+)\b", token):
        return True
    if len(words) >= 5 and not re.search(r"[+#./-]", token):
        return True
    if re.fullmatch(r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2}", token.strip()):
        lower_token = token.lower()
        tech_hints = {
            "power",
            "automate",
            "java",
            "spring",
            "oracle",
            "sql",
            "hibernate",
            "servlet",
            "maven",
            "jenkins",
            "kafka",
            "hadoop",
            "android",
            "react",
            "angular",
            "python",
            "scala",
            "aws",
            "agile",
            "struts",
            "jquery",
            "javascript",
            "typescript",
        }
        if not any(hint in lower_token for hint in tech_hints):
            return True
    if re.search(r"\b[A-Za-z]+\s*[,;]\s*[A-Za-z]+\s*[,;]\s*[A-Za-z]+\b", token):
        # likely sentence/list fragment rather than a single skill.
        return True

    return False


def _is_generic_non_skill_token(token: str) -> bool:
    lowered = token.lower().strip()
    if not lowered:
        return True

    generic_exact = {
        "professional experience",
        "technical skills",
        "educational documents",
        "role",
        "responsibilities",
        "responsibility",
        "client",
        "location",
        "project",
        "project name",
        "systems",
        "system",
        "management",
        "strong understanding",
        "understanding",
        "effective",
        "techniques",
        "best practices",
        "and networking",
        "over time",
        "defect",
        "ca",
        "sandiego",
        "sysintelliinc",
        "information",
        "knowledge",
        "policy",
        "eligibility",
        "education",
        "summary",
        "team",
        "using",
        "used",
        "worked",
        "developed",
        "responsible",
        "experienced",
        "project",
        "test",
        "sequence",
        "is a",
    }
    if lowered in generic_exact:
        return True

    if re.fullmatch(r"[A-Z]{2}", token.strip()):
        return True

    org_markers = {
        "department",
        "insurance",
        "bank",
        "university",
        "college",
        "hospital",
        "state health",
        "motors",
        "railroad",
    }
    if any(marker in lowered for marker in org_markers):
        return True

    connectors = {" of ", " and ", " for ", " with ", " in ", " to "}
    tech_hints = {
        "java",
        "spring",
        "oracle",
        "sql",
        "hibernate",
        "servlet",
        "maven",
        "jenkins",
        "kafka",
        "hadoop",
        "android",
        "react",
        "angular",
        "python",
        "scala",
        "aws",
        "rest",
        "soap",
        "j2ee",
        "jdbc",
        "struts",
        "jsp",
        "xml",
        "json",
    }
    if len(lowered.split()) >= 4 and any(conn in f" {lowered} " for conn in connectors):
        if not any(hint in lowered for hint in tech_hints):
            return True

    return False


def _looks_like_role_title(value: Any) -> bool:
    text = _clean_string(value)
    if not text:
        return False
    return bool(
        re.search(
            r"(?i)\b(sr\.?\s*)?(business systems? analyst|business analyst|data analyst|quality analyst|project manager|scrum master)\b",
            text,
        )
    )


def _looks_like_probable_job_title(value: Any) -> bool:
    text = _clean_string(value)
    if not text:
        return False
    if len(text.split()) > 10:
        return False
    return bool(
        re.search(
            r"(?i)\b(developer|engineer|analyst|manager|architect|consultant|administrator|coordinator|lead|scrum master|qa|tester|programmer)\b",
            text,
        )
    )


def _looks_like_sentence_fragment(token: str) -> bool:
    lowered = token.lower().strip()
    if not lowered:
        return True

    words = [w for w in lowered.split() if w]
    if len(words) >= 6:
        tech_hints = {
            "java", "spring", "oracle", "sql", "hibernate", "servlet", "maven", "jenkins",
            "kafka", "hadoop", "android", "react", "angular", "python", "scala", "aws",
            "rest", "soap", "j2ee", "jdbc", "struts", "jsp", "xml", "json", "objective-c",
        }
        if not any(h in lowered for h in tech_hints):
            return True

    if any(v in f" {lowered} " for v in {" using ", " used ", " worked ", " developed ", " designed ", " implemented ", " involved ", " reviewed "}):
        return True
    if lowered.endswith("."):
        return True
    return False


def _should_keep_skill_token(token: str, dynamic_short_allowlist: set[str] | None = None) -> bool:
    lowered = token.lower().strip()
    if not lowered:
        return False

    normalized = re.sub(r"[_/]+", " ", lowered)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    words = [w for w in re.split(r"\s+", normalized) if w]

    # compact short-token policy: keep only core technical abbreviations/symbolic langs.
    compact = re.sub(r"[^a-z0-9+#.]", "", normalized)
    short_allow = {"c", "r", "bi", "ui", "ux", "qa", "ai", "ml", "js", "ts", "sql", "etl"}
    if dynamic_short_allowlist:
        short_allow = short_allow.union(dynamic_short_allowlist)
    symbolic_short_allow = {"c#", "c++", ".net"}
    if len(compact) <= 2 and compact not in short_allow and normalized not in symbolic_short_allow:
        return False

    # Drop obvious prose leftovers and malformed fragments.
    if re.search(r"(?i)\b(is a|happy to assist|let me know|summary|project|team|responsible|experienced)\b", normalized):
        return False
    if re.fullmatch(r"[a-z]{1,2}", normalized):
        return False
    if len(words) >= 5 and not re.search(r"[0-9+#./-]", normalized):
        return False

    # High-confidence technical markers.
    tech_hints = (
        r"sql|oracle|postgres|mysql|mongodb|redis|snowflake|db2|"
        r"java|j2ee|python|javascript|typescript|c\+\+|c#|\.net|php|html|css|xml|json|"
        r"react|angular|vue|node|spring|hibernate|django|flask|"
        r"aws|azure|gcp|docker|kubernetes|jenkins|git|jira|confluence|"
        r"tableau|power\s*bi|power\s*apps|power\s*automate|informatica|ssis|ssas|ssrs|olap|qtp|mule|salesforce|apex|soql|wsdl|soap|rest|api|"
        r"agile|scrum|kanban|waterfall|rup|tdd|uat|erwin|visio|postman|sharepoint|eclipse|arcgis|mainframes?|hp\s*alm|hpqc|unix|linux|sybase"
    )
    if re.search(rf"(?i)\b({tech_hints})\b", normalized):
        return True

    # Allow explicit versioned/vendor-like technical tokens.
    if re.search(r"\b\d+(?:\.\d+)+\b", normalized):
        return True
    if re.search(r"(?i)\b(?:ms|ibm|oracle|aws|sap|adobe|apache)\b", normalized):
        return True

    # Keep likely explicit tool/product identifiers (e.g., MyCustomInternalTool).
    if (
        len(words) == 1
        and re.fullmatch(r"[A-Za-z][A-Za-z0-9_.+-]{4,}", token.strip())
        and re.search(r"[A-Z0-9_.+-]", token[1:])
    ):
        return True

    return False


def _skills_need_fallback(skills: Any) -> bool:
    if not isinstance(skills, list) or not skills:
        return True

    noisy = 0
    hard_noise = 0
    for item in skills:
        if not isinstance(item, str):
            noisy += 1
            continue
        if re.search(r"(?i)\b(role\s*:|responsibilities\s*:)\b", item):
            return True
        if re.search(r"(?i)\b(till date|present|current)\b", item):
            return True
        if re.search(r"(?i)\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)\s*\d{2,4}\b", item):
            return True
        if re.search(r"\b(19|20)\d{2}\b", item):
            return True
        if re.search(r"(?i)\b[A-Za-z .'-]+,\s*(?:[A-Z]{2}|[A-Za-z]+)\b", item):
            return True
        if _looks_like_non_skill_phrase(item):
            noisy += 1
            hard_noise += 1
        if _looks_like_sentence_fragment(item):
            noisy += 1
            hard_noise += 1

    ratio = noisy / float(len(skills))
    return ratio >= 0.20 or hard_noise >= 3


def _split_skill_candidate(value: str) -> list[str]:
    cleaned = _clean_string(value)
    if not cleaned:
        return []

    # First split by explicit separators.
    parts = [
        _clean_string(part)
        for part in re.split(r"\s*[|,;]\s*|\s+/\s+|\s+\band\b\s+|\s*&\s*", cleaned, flags=re.IGNORECASE)
    ]
    parts = [part for part in parts if part]
    if len(parts) > 1:
        return parts

    token = parts[0] if parts else cleaned

    # Recover merged LLM tokens (e.g., "JavaScript PowerShell Power Automate").
    known_patterns: list[tuple[str, str]] = [
        (r"\bpower\s+automate\b", "Power Automate"),
        (r"\bpowershell\b", "PowerShell"),
        (r"\bjavascript\b", "JavaScript"),
        (r"\btypescript\b", "TypeScript"),
        (r"\bsharepoint\s+designer\b", "SharePoint Designer"),
        (r"\bsharepoint\b", "SharePoint"),
        (r"\bhtml\b", "HTML"),
        (r"\bcss\b", "CSS"),
        (r"\bpython\b", "Python"),
        (r"\bsql\b", "SQL"),
        (r"\bpower\s+apps\b", "Power Apps"),
        (r"\bpower\s+bi\b", "Power BI"),
    ]

    matches: list[str] = []
    token_lower = token.lower()
    for pattern, label in known_patterns:
        if re.search(pattern, token_lower):
            matches.append(label)

    if len(matches) >= 2:
        return _unique_clean_strings(matches)

    return [token]


def _unique_clean_strings(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []

    for value in values:
        cleaned = _clean_string(value)
        if not cleaned:
            continue
        key = cleaned.lower()
        if key not in seen:
            seen.add(key)
            result.append(cleaned)

    return result


def _sanitize_skills_used(values: list[str]) -> list[str]:
    cleaned: list[str] = []
    for value in values:
        token = _clean_string(value)
        if not token:
            continue
        lower = token.lower()
        if re.search(r"(?i)\b(happy to assist|let me know|how can i help|i can help)\b", lower):
            continue
        if token.endswith(("!", "?")) and len(token.split()) >= 2:
            continue
        cleaned.append(token)
    return cleaned


def _normalize_phone_value(phone: Any, raw_text: str) -> str | None:
    parsed = _clean_string(phone)
    raw_phone = _extract_phone_from_text(raw_text)

    candidate = parsed or raw_phone
    if not candidate:
        return None

    parsed_digits = re.sub(r"\D", "", parsed) if parsed else ""
    raw_digits = re.sub(r"\D", "", raw_phone) if raw_phone else ""
    if (
        parsed
        and raw_phone
        and "+" not in parsed
        and "+" in raw_phone
        and parsed_digits
        and raw_digits.endswith(parsed_digits[-10:])
    ):
        candidate = raw_phone

    has_plus = candidate.strip().startswith("+")
    digits = re.sub(r"\D", "", candidate)
    if not digits:
        return None

    if has_plus:
        if len(digits) == 11 and digits.startswith("1"):
            return f"+1-{digits[1:4]}-{digits[4:7]}-{digits[7:]}"
        return f"+{digits}"

    if len(digits) == 10:
        return f"{digits[0:3]}-{digits[3:6]}-{digits[6:]}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+1-{digits[1:4]}-{digits[4:7]}-{digits[7:]}"

    return candidate


def _extract_phone_from_text(text: str) -> str | None:
    match = re.search(r"(\+?\d[\d()\-\s]{8,}\d)", text)
    if not match:
        return None
    return _clean_string(match.group(1))


def _extract_email_from_text(text: str) -> str | None:
    match = EMAIL_PATTERN.search(text or "")
    if not match:
        return None
    return _clean_string(match.group(0))


def _clean_date_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None

    value = value.strip()
    normalized = _normalize_date_token(value, is_end=False)
    if normalized:
        return normalized

    inferred_start, inferred_end, inferred_current = _extract_date_range_from_text(value)
    if inferred_current:
        return "Present"
    if inferred_start and not inferred_end:
        return inferred_start
    if inferred_end:
        return inferred_end
    return None


def _clean_experience_title(value: Any) -> str | None:
    title = _clean_string(value)
    if not title:
        return None
    title = re.sub(r"(?i)\s+responsibilities?\s*:?\s*$", "", title).strip(" :-")
    title = re.sub(r"(?i)^responsibilities?\s*:?\s*", "", title).strip(" :-")
    return _clean_string(title)


def _looks_like_month_or_date_fragment(value: Any) -> bool:
    text = _clean_string(value)
    if not text:
        return False
    lowered = text.lower().strip()
    lowered = re.sub(r"[^a-z0-9 ]+", " ", lowered)
    lowered = re.sub(r"\s+", " ", lowered).strip()
    if not lowered:
        return False
    month_words = set(MONTH_MAP.keys()) | {"present", "current", "currently", "till", "date", "to"}
    tokens = [tok for tok in lowered.split() if tok]
    if not tokens:
        return False
    if all(tok in month_words or re.fullmatch(r"\d{2,4}", tok) for tok in tokens):
        return True
    if re.fullmatch(r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*", lowered):
        return True
    return False


def _looks_like_education_artifact_experience_entry(entry: dict[str, Any]) -> bool:
    title = _clean_string(entry.get("title")) or ""
    company = _clean_string(entry.get("company")) or ""
    description = _clean_string(entry.get("description")) or ""
    merged = f"{title} {company} {description}".strip().lower()
    if not merged:
        return False

    has_edu_signal = bool(
        re.search(
            r"\b(educational documents|masters?|bachelors?|ph\.?d|diploma|university|college|school|campus)\b",
            merged,
        )
    )
    if not has_edu_signal:
        return False

    has_job_signal = bool(
        re.search(
            r"\b(developer|engineer|analyst|manager|architect|consultant|administrator|coordinator|lead|scrum|qa|tester|intern|director)\b",
            merged,
        )
    )
    if has_job_signal:
        return False

    # Strongly treat line-noise placeholders as malformed non-job rows.
    if company in {".", "-", "--"}:
        return True
    if _looks_like_month_or_date_fragment(company):
        return True
    if re.search(r"\b(university|college|school)\b", (title or "").lower()):
        return True
    return False




def _extract_title_from_description_prefix(value: Any) -> str | None:
    desc = _clean_string(value)
    if not desc:
        return None
    match = re.match(
        r"(?i)^\s*((?:sr\.?|senior)?\s*business(?:\s+systems|\s+quality)?\s+analyst(?:\s*/\s*project\s+coordinator|\s*/\s*scrum\s*master)?)\b",
        desc,
    )
    if not match:
        return None
    return _clean_experience_title(match.group(1))


def _parse_client_company_location_from_line(value: Any) -> tuple[str | None, str | None]:
    line = _clean_string(value)
    if not line or not re.match(r"(?i)^\s*client\s*:", line):
        return None, None

    body = re.sub(r"(?i)^\s*client\s*:\s*", "", line).strip()
    body = _strip_date_range_from_text(body)
    body = re.sub(r"\s*\([^)]*\)\s*$", "", body).strip(" |,-")
    if not body:
        return None, None

    parts = [part.strip() for part in body.split(",", 1)]
    if len(parts) == 1:
        return _clean_string(parts[0]), None
    company = _clean_string(parts[0])
    location = _clean_string(parts[1])
    if location:
        location = re.sub(r"\s*\([^)]*\)\s*$", "", location).strip(" |,-")
        location = _clean_string(location)
    return company, location


def _split_org_and_region_from_line(value: str) -> tuple[str | None, str | None]:
    text = _clean_string(value)
    if not text or "," not in text:
        return None, None
    parts = [part.strip() for part in text.split(",") if part.strip()]
    if len(parts) != 2:
        return None, None
    org, region = parts[0], parts[1]
    if not re.fullmatch(r"[A-Z]{2}", region):
        return None, None
    if not re.search(
        r"(?i)\b(bank|insurance|technologies|systems|solutions|investments|therapeutics|university|college|department|division)\b",
        org,
    ):
        return None, None
    return _clean_string(org), _clean_string(region)


def _extract_explicit_tech_mentions_from_text(text: str) -> list[str]:
    if not text:
        return []

    # Guarded fallback: only explicit, high-confidence technologies/tools.
    patterns: list[tuple[str, str]] = [
        (r"(?i)\bsql\b", "SQL"),
        (r"(?i)\bjira\b", "JIRA"),
        (r"(?i)\bms\s*visio\b", "MS Visio"),
        (r"(?i)\buml\b", "UML"),
        (r"(?i)\balm\b", "ALM"),
        (r"(?i)\bservicenow\b", "ServiceNow"),
        (r"(?i)\bconfluence\b", "Confluence"),
        (r"(?i)\bagile\b", "Agile"),
        (r"(?i)\bscrum\b", "Scrum"),
        (r"(?i)\bwaterfall\b", "Waterfall"),
        (r"(?i)\bsdlc\b", "SDLC"),
        (r"(?i)\buat\b", "UAT"),
        (r"(?i)\bbrd(?:s)?\b", "BRD"),
        (r"(?i)\bfrd(?:s)?\b", "FRD"),
        (r"(?i)\bfsd(?:s)?\b", "FSD"),
        (r"(?i)\btrd(?:s)?\b", "TRD"),
        (r"(?i)\btcd(?:s)?\b", "TCD"),
        (r"(?i)\bms\s*outlook\b", "MS Outlook"),
        (r"(?i)\bms\s*word\b", "MS Word"),
        (r"(?i)\bms\s*power\s*point\b", "MS PowerPoint"),
        (r"(?i)\bsharepoint\b", "SharePoint"),
        (r"(?i)\bwiki/?confluence\b", "Confluence"),
        (r"(?i)\bsaas\b", "SaaS"),
        (r"(?i)\bapi(?:'s|s)?\b", "API"),
    ]

    found: list[str] = []
    for pattern, label in patterns:
        if re.search(pattern, text):
            found.append(label)
    return _unique_clean_strings(found)


def sort_experience_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def sort_key(entry: dict[str, Any]) -> tuple[int, int, int]:
        is_current = 1 if entry.get("is_current") is True else 0
        end_rank = _date_sort_rank(entry.get("end_date"), present_high=True)
        start_rank = _date_sort_rank(entry.get("start_date"), present_high=False)
        return (is_current, end_rank, start_rank)

    return sorted(entries, key=sort_key, reverse=True)


def _date_sort_rank(value: Any, *, present_high: bool) -> int:
    if not isinstance(value, str):
        return -1
    if value == "Present":
        return 999999 if present_high else -1
    if re.fullmatch(r"\d{4}-\d{2}", value):
        y, m = value.split("-")
        return int(y) * 100 + int(m)
    if re.fullmatch(r"\d{4}", value):
        return int(value) * 100
    return -1


def derive_highest_degree(education_entries: list[dict[str, Any]]) -> str | None:
    best_degree = None
    best_rank = -1

    for entry in education_entries:
        degree = entry.get("degree")
        if not isinstance(degree, str):
            continue
        rank = _rank_degree(degree)
        if rank > best_rank:
            best_rank = rank
            best_degree = degree

    return best_degree


def _rank_degree(degree: str) -> int:
    normalized = degree.lower().strip()
    for key, rank in DEGREE_RANK.items():
        if key in normalized:
            return rank
    return 0


def derive_current_last_job(experience_entries: list[dict[str, Any]]) -> str | None:
    if not experience_entries:
        return None

    sorted_entries = sort_experience_entries(experience_entries)
    for entry in sorted_entries:
        title = entry.get("title")
        if isinstance(title, str) and title.strip():
            cleaned = title.strip()
            if re.match(r"(?i)^\s*(environment|environment\\tools|tools)\s*[:\\]", cleaned):
                continue
            if re.match(r"(?i)^\s*(technology|technologies|responsibilities|project description|client description)\s*:", cleaned):
                continue
            if re.search(r"(?i)\b(pmp\s*expiration|certification|pmp number)\b", cleaned):
                continue
            return cleaned
    return None


def _extract_specific_current_title(experience_entries: Any) -> str | None:
    if not isinstance(experience_entries, list):
        return None
    current_entries = [e for e in experience_entries if isinstance(e, dict) and e.get("is_current") is True]
    candidates = current_entries if current_entries else [e for e in experience_entries if isinstance(e, dict)]
    for entry in candidates:
        title = _clean_experience_title(entry.get("title"))
        if title:
            return title
    return None


def _should_prefer_specific_current_title(current_last_job: Any, candidate_title: str) -> bool:
    existing = _clean_experience_title(current_last_job)
    candidate = _clean_experience_title(candidate_title)
    if not candidate:
        return False
    if not existing:
        return True
    if existing.lower() == candidate.lower():
        return False

    existing_l = existing.lower()
    candidate_l = candidate.lower()
    generic_roles = {
        "business analyst",
        "senior business analyst",
        "sr business analyst",
        "sr. business analyst",
        "business systems analyst",
        "analyst",
    }
    if existing_l in generic_roles and len(candidate_l) > len(existing_l):
        return True
    if existing_l in candidate_l and ("," in candidate or "/" in candidate):
        return True
    return False


def calculate_experience_years_from_entries(entries: list[dict[str, Any]]) -> float | None:
    intervals: list[DateInterval] = []

    for entry in entries:
        interval = _entry_to_interval(entry)
        if interval:
            intervals.append(interval)

    if not intervals:
        return None

    merged = _merge_intervals(intervals)
    total_months = sum(_months_inclusive(iv.start, iv.end) for iv in merged)
    return round(total_months / 12.0, 1)


def _entry_to_interval(entry: dict[str, Any]) -> DateInterval | None:
    start = _parse_normalized_date(entry.get("start_date"), is_end=False)
    end = _parse_normalized_date(entry.get("end_date"), is_end=True)

    if entry.get("is_current") is True:
        end = date.today()

    if not start or not end:
        return None
    if end < start:
        return None

    return DateInterval(start=start, end=end)


def _parse_normalized_date(value: Any, *, is_end: bool) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None

    value = value.strip()

    if value == "Present":
        return date.today()

    if re.fullmatch(r"\d{4}-\d{2}", value):
        year, month = map(int, value.split("-"))
        if year < 1950 or year > (date.today().year + 1):
            return None
        if not (1 <= month <= 12):
            return None
        if is_end:
            last_day = calendar.monthrange(year, month)[1]
            return date(year, month, last_day)
        return date(year, month, 1)

    if re.fullmatch(r"\d{4}", value):
        year = int(value)
        if year < 1950 or year > (date.today().year + 1):
            return None
        return date(year, 12, 31) if is_end else date(year, 1, 1)

    return None


def _merge_intervals(intervals: list[DateInterval]) -> list[DateInterval]:
    if not intervals:
        return []

    intervals = sorted(intervals, key=lambda x: x.start)
    merged = [intervals[0]]

    for current in intervals[1:]:
        last = merged[-1]
        if current.start <= last.end:
            merged[-1] = DateInterval(
                start=last.start,
                end=max(last.end, current.end),
            )
        else:
            merged.append(current)

    return merged


def _months_inclusive(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + (end.month - start.month) + 1


def derive_seniority_level(current_last_job: str | None) -> str | None:
    if not current_last_job:
        return None

    title = current_last_job.lower()
    if any(x in title for x in ["principal", "staff", "director", "head", "vp", "vice president"]):
        return "Principal+"
    if any(x in title for x in ["lead", "manager"]):
        return "Lead/Manager"
    if "senior" in title:
        return "Senior"
    if any(x in title for x in ["associate", "junior", "intern"]):
        return "Junior/Associate"
    return "Mid"


def derive_primary_domain(
    current_last_job: str | None,
    entries: list[dict[str, Any]],
    skills: list[str],
) -> str | None:
    parts = [current_last_job or ""]
    parts.extend(entry.get("title") or "" for entry in entries if isinstance(entry, dict))
    parts.extend(skills if isinstance(skills, list) else [])
    text = " ".join(parts).lower()

    role_text_parts = [current_last_job or ""]
    role_text_parts.extend(entry.get("title") or "" for entry in entries if isinstance(entry, dict))
    role_text = " ".join(role_text_parts).lower()
    if re.search(r"\b(scrum master|business systems? analyst|business analyst|product owner)\b", role_text):
        return "Business Analysis / Agile Delivery"

    rules = [
        ("Mobile Engineering", ["ios", "android", "flutter", "react native", "mobile"]),
        (
            "Backend Engineering",
            [
                "backend",
                "api developer",
                "server-side",
                "microservices",
                "java",
                "j2ee",
                "spring",
                "hibernate",
                "servlet",
                "jdbc",
                "golang",
                "go",
                "php",
                "rails",
            ],
        ),
        ("Frontend Engineering", ["frontend", "ui engineer", "react", "angular", "vue", "css"]),
        ("Data Engineering", ["data engineer", "etl", "spark", "airflow", "warehouse"]),
        ("ML/AI Engineering", ["llm", "machine learning", "ml engineer", "rag", "bedrock", "llamaindex", "openai api", "anthropic"]),
        ("DevOps/Platform", ["devops", "platform", "terraform", "kubernetes", "ci/cd"]),
    ]

    for label, keywords in rules:
        if any(keyword in text for keyword in keywords):
            return label

    return None

def _extract_company_location_title_date_next_line_entries(text: str) -> list[dict[str, Any]]:
    """Recover experience rows formatted as:
    Company, City, State Job Title
    Month YYYY - Month YYYY
    """
    if not isinstance(text, str) or not text.strip():
        return []

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    entries: list[dict[str, Any]] = []

    title_pattern = re.compile(
        r"(?i)\b(Full\s+Stack\s+Java\s+Developer|Software\s+Engineer|Java\s+Developer|J2EE\s+Developer|Junior\s+Java\s+Developer|Sr\.?\s+Java\s+Developer|Senior\s+Java\s+Developer|JAVA/J2EE\s+Developer)\b"
    )

    stop_header_pattern = re.compile(
        r"(?i)^\s*(responsibilities|environment|technical\s+skills|education|summary|professional\s+experience)\s*:"
    )

    for idx, line in enumerate(lines[:-1]):
        next_line = lines[idx + 1]
        start_date, end_date, is_current = _extract_date_range_from_text(next_line)
        if not (start_date or end_date or is_current):
            continue
        if stop_header_pattern.match(line):
            continue

        title_match = title_pattern.search(line)
        if not title_match:
            continue

        before_title = line[: title_match.start()].strip(" ,-–—")
        title = _clean_experience_title(title_match.group(1))
        if not before_title or not title:
            continue

        parts = [part.strip() for part in before_title.split(",") if part.strip()]
        company = None
        location = None

        if len(parts) >= 3:
            company = ", ".join(parts[:-2]).strip()
            location = f"{parts[-2]}, {parts[-1]}"
        elif len(parts) == 2:
            company = parts[0]
            location = parts[1]
        else:
            company = before_title

        company = _normalize_company_string(company)
        location = _clean_string(location)
        if not company:
            continue
        if location and not _looks_like_location_text(location):
            location = None

        description_lines: list[str] = []
        for detail in lines[idx + 2 :]:
            if title_pattern.search(detail):
                break
            if _extract_date_range_from_text(detail) != (None, None, False):
                break
            if re.match(r"(?i)^\s*(environment|education|technical\s+skills|professional\s+experience)\s*:", detail):
                break
            if re.match(r"(?i)^\s*responsibilities\s*:", detail):
                continue
            description_lines.append(detail)

        entries.append(
            {
                "company": company,
                "title": title,
                "location": location,
                "start_date": start_date,
                "end_date": end_date,
                "is_current": is_current,
                "employment_type": None,
                "description": _trim_experience_description(" ".join(description_lines)),
                "skills_used": [],
                "achievements": [],
            }
        )

    return sort_experience_entries(entries)
