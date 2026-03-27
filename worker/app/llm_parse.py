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
LLM_PARSE_TIMEOUT = int(os.getenv("LLM_PARSE_TIMEOUT_SECONDS", "60"))
LLM_PARSE_MAX_RETRIES = int(os.getenv("LLM_PARSE_MAX_RETRIES", "2"))

ATS_RESUME_SCHEMA_DESCRIPTION_V2 = """You are an expert resume parser.

Extract only information explicitly present in the resume text.
Do not infer, guess, or invent missing information.
If a field is not present, return null or [].
Return only valid JSON matching the exact schema.

Important rules:
- Extract contact info only if explicitly present.
- Extract skills from sections such as Skills, Key Skills, Technical Skills, Toolkit, Expertise.
- Extract projects from sections such as Projects, Personal Projects, Side Projects, Selected Projects.
- Keep URLs only if explicitly present in the resume text.
- Keep certifications only if explicitly present in the resume text.
- Do not add synthetic metadata, confidence scores, distances, or derived analytics.
- current_last_job must be the most recent job title only.
- highest_degree must align with the highest explicit degree found in education.
- Extract only professional experience into experience_entries.
- Keep achievements empty unless they are explicitly separated and clearly identifiable.
"""

ATS_RESUME_OUTPUT_SCHEMA_V2 = """{
  "full_name": null,
  "email": null,
  "phone": null,
  "candidate_location": null,
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
PRESENT_TOKEN_PATTERN = r"present|current|currently|now|today|ongoing|till(?:\s+(?:date|now))?|to\s+date"

URL_PATTERN = re.compile(r"https?://[^\s|,;]+", re.IGNORECASE)
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
            time.sleep(0.5 * attempt)

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

    return _normalize_llm_parse_output_v2(parsed, normalized_text)


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


def _normalize_llm_parse_output_v2(parsed: dict[str, Any], raw_text: str) -> dict[str, Any]:
    def clean(value: Any) -> str | None:
        return _clean_string(value)

    parsed = parsed if isinstance(parsed, dict) else {}

    result: dict[str, Any] = {
        "full_name": clean(parsed.get("full_name")),
        "email": clean(parsed.get("email")),
        "phone": clean(parsed.get("phone")),
        "candidate_location": clean(parsed.get("candidate_location")),
        "linkedin_url": clean(parsed.get("linkedin_url")),
        "github_url": clean(parsed.get("github_url")),
        "portfolio_url": clean(parsed.get("portfolio_url")),
        "professional_summary": clean(parsed.get("professional_summary")),
        "skills": _unique_clean_strings(parsed.get("skills", [])) if isinstance(parsed.get("skills"), list) else [],
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

    result["experience_entries"] = sort_experience_entries(result["experience_entries"])

    if len(result["experience_entries"]) <= 1 and _count_date_ranges(raw_text) >= 3:
        fallback_entries = _extract_experience_entries_from_text(raw_text)
        if len(fallback_entries) > len(result["experience_entries"]):
            result["experience_entries"] = sort_experience_entries(fallback_entries)

    result["projects"] = [item for item in result["projects"] if not _is_empty_project(item)]
    result["education"] = [item for item in result["education"] if not _is_empty_education(item)]

    environment_skills = _extract_environment_skills_from_text(raw_text)
    if not result["skills"] and _has_skills_section(raw_text):
        result["skills"] = _extract_skills_from_text(raw_text, result["experience_entries"])
    if environment_skills:
        result["skills"] = _unique_clean_strings([*result["skills"], *environment_skills])

    if not result["certifications"] and _has_certification_section(raw_text):
        result["certifications"] = _extract_certifications_from_text(raw_text)

    if result["professional_summary"] is None:
        result["professional_summary"] = _extract_professional_summary_from_text(raw_text)

    if result["candidate_location"] is None:
        for entry in result["experience_entries"]:
            location = entry.get("location")
            if isinstance(location, str) and location.strip():
                result["candidate_location"] = location.strip()
                break

    if result["highest_degree"] is None:
        result["highest_degree"] = derive_highest_degree(result["education"])

    if result["current_last_job"] is None:
        result["current_last_job"] = derive_current_last_job(result["experience_entries"])

    return result


def _normalize_education_entry_v2(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "institution": _clean_string(entry.get("institution")),
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

    return {
        "company": _clean_string(entry.get("company")),
        "title": _clean_string(entry.get("title")),
        "location": _clean_string(entry.get("location")),
        "start_date": start_date,
        "end_date": end_date,
        "is_current": inferred_is_current,
        "employment_type": _clean_string(entry.get("employment_type")),
        "description": _trim_experience_description(entry.get("description")),
        "skills_used": _unique_clean_strings(entry.get("skills_used", []))
        if isinstance(entry.get("skills_used"), list) else [],
        "achievements": _unique_clean_strings(entry.get("achievements", []))
        if isinstance(entry.get("achievements"), list) else [],
    }


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


def _extract_section_block(text: str, header_pattern: str, max_lines: int = 60) -> list[str]:
    lines = [line.strip() for line in text.splitlines()]
    in_section = False
    collected: list[str] = []

    for line in lines:
        if not in_section and re.search(header_pattern, line, re.IGNORECASE):
            in_section = True
            continue

        if not in_section:
            continue

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
        r"^\s*(technical\s+skill(?:-set|s)?|skills?|toolkit|expertise)\s*:?\s*$",
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
        r"(?i)^(environment|tech\s*stack|tools\s*used|technologies)\s*:"
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

    return _unique_clean_strings(skills)


def _extract_certifications_from_text(text: str) -> list[dict[str, Any]]:
    block = _extract_section_block(
        text,
        r"\b(certifications?|education\s*/\s*certi\w*\s*/\s*training)\b",
        max_lines=40,
    )
    if not block:
        return []

    certs: list[dict[str, Any]] = []
    for line in block:
        if not re.search(r"(certified|certification|csm|istqb|six sigma|ncfm|qtp|quality center)", line, re.IGNORECASE):
            continue
        name = _clean_string(re.sub(r"^[•*\-\s]+", "", line))
        if name:
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
        return int(cleaned)
    if len(cleaned) == 2:
        value = int(cleaned)
        return 2000 + value if value <= 30 else 1900 + value
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
        return value

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
        return m.group(1)

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

    for idx, line in enumerate(lines):
        start_date, end_date, is_current = _extract_date_range_from_text(line)
        if not start_date and not end_date and not is_current:
            continue

        company_part = re.split(r"\s+-\s+", line, maxsplit=1)[0].strip()
        location_match = re.search(r"\b([A-Za-z .'-]+,\s*(?:[A-Z]{2}|[A-Za-z]+))(?:\s*/\s*[A-Za-z .'-]+,\s*(?:[A-Z]{2}|[A-Za-z]+))*\b", company_part)
        location = _clean_string(location_match.group(1)) if location_match else None
        company = _clean_string(re.sub(r",\s*[A-Za-z .'-]+,\s*(?:[A-Z]{2}|[A-Za-z]+).*$", "", company_part))

        title = None
        if idx + 1 < len(lines):
            next_line = lines[idx + 1]
            if len(next_line.split()) <= 14 and not re.search(r"(role and responsibilities|technologies|project|education)", next_line, re.IGNORECASE):
                title = _clean_string(next_line)

        entries.append(
            {
                "company": company,
                "title": title,
                "location": location,
                "start_date": start_date,
                "end_date": end_date,
                "is_current": bool(is_current),
                "employment_type": None,
                "description": None,
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


def _extract_work_experience_block(text: str) -> str:
    lines = text.splitlines()
    start_idx: int | None = None
    end_idx: int | None = None

    for i, raw in enumerate(lines):
        line = raw.strip()
        if start_idx is None and re.fullmatch(
            r"(?i)(work experience|professional experience|employment history|career history|work history|relevant experience|industry experience|consulting experience|experience)",
            line.rstrip(":"),
        ):
            start_idx = i + 1
            continue

        if start_idx is not None and re.fullmatch(
            r"(?i)(education|skills|certifications|additional information|technical skills)",
            line.rstrip(":"),
        ):
            end_idx = i
            break

    if start_idx is None:
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
            return title.strip()
    return None


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
        if not (1 <= month <= 12):
            return None
        if is_end:
            last_day = calendar.monthrange(year, month)[1]
            return date(year, month, last_day)
        return date(year, month, 1)

    if re.fullmatch(r"\d{4}", value):
        year = int(value)
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

    rules = [
        ("Mobile Engineering", ["ios", "android", "flutter", "react native", "mobile"]),
        ("Frontend Engineering", ["frontend", "ui engineer", "react", "angular", "vue", "css"]),
        ("Backend Engineering", ["backend", "api developer", "server-side", "microservices", "golang", "go", "php", "rails"]),
        ("Data Engineering", ["data engineer", "etl", "spark", "airflow", "warehouse"]),
        ("ML/AI Engineering", ["llm", "machine learning", "ml engineer", "rag", "bedrock", "llamaindex", "openai api", "anthropic"]),
        ("DevOps/Platform", ["devops", "platform", "terraform", "kubernetes", "ci/cd"]),
    ]

    for label, keywords in rules:
        if any(keyword in text for keyword in keywords):
            return label

    return None
