from __future__ import annotations

import json
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import fitz
import psycopg
import redis
from docx import Document
from psycopg.types.json import Json

from app.llm_parse import (
    _build_experience_calculation,
    _extract_work_excerpt,
    extract_experience_entries_from_blocks,
    parse_resume_with_llm,
    reconcile_resume_parse_with_llm,
)
# Legacy fallback import:
# from app.llm_parse import normalize_resume_fields_with_llm, parse_resume_with_llm

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
INGESTION_QUEUE_KEY = os.getenv("INGESTION_QUEUE_KEY", "resume_ingestion_queue")
WORKER_DATABASE_URL = os.getenv("WORKER_DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ats")
ENABLE_LLM_PARSE = os.getenv("ENABLE_LLM_PARSE", "false").lower() == "true"
LLM_PARSE_ONLY = os.getenv("LLM_PARSE_ONLY", "false").lower() == "true"
USE_DOCLING_PARSER = os.getenv("USE_DOCLING_PARSER", "true").lower() == "true"

SKILL_KEYWORDS = [
    "python",
    "java",
    "javascript",
    "typescript",
    "react",
    "next.js",
    "servicenow",
    "itsm",
    "cmdb",
    "flow designer",
    "sql",
    "power bi",
    "tableau",
    "excel",
    "snowflake",
    "sharepoint",
]

EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_PATTERN = re.compile(r"(?:\+?\d[\d\s().-]{8,}\d)")
YEARS_OF_EXPERIENCE_PATTERN = re.compile(
    r"(?:(?:over|more\s+than|approximately|around|nearly)\s+)?"
    r"(?P<years>\d{1,2}(?:\.\d+)?)\s*\+?\s*"
    r"(?:years?|yrs?)\s+(?:of\s+)?(?:\w+\s+){0,3}?experience\b",
    re.IGNORECASE,
)
ALT_YEARS_OF_EXPERIENCE_PATTERN = re.compile(
    r"(?:for\s+)?(?:more\s+than|over|around|approximately|nearly)?\s*"
    r"(?P<years>\d{1,2}(?:\.\d+)?)\s*\+?\s*"
    r"(?:years?|yrs?)\b",
    re.IGNORECASE,
)
NO_SPONSOR_PATTERN = re.compile(r"(no\s+sponsorship|without\s+sponsorship)", re.IGNORECASE)
YES_SPONSOR_PATTERN = re.compile(r"(require[s]?\s+sponsorship|visa\s+sponsorship)", re.IGNORECASE)
LOCATION_LINE_PATTERN = re.compile(
    r"\b([A-Za-z .'-]+,\s*(?:[A-Z]{2}|[A-Za-z]+)(?:,\s*(?:USA|US|United States))?)\b"
)
ZIP_TRAIL_PATTERN = re.compile(r"\b\d{5}(?:-\d{4})?\b")
CONTACT_DELIM_PATTERN = re.compile(r"\s*[|•·]\s*")
MONTH_YEAR_RANGE_PATTERN = re.compile(
    r"\b(Jan|January|Feb|February|Mar|March|Apr|April|May|Jun|June|Jul|July|Aug|August|Sep|Sept|September|Oct|October|Nov|November|Dec|December)\s+(\d{4})\s*[-–]\s*(Present|Current|Now|"
    r"Jan|January|Feb|February|Mar|March|Apr|April|May|Jun|June|Jul|July|Aug|August|Sep|Sept|September|Oct|October|Nov|November|Dec|December)\s*(\d{4})?",
    re.IGNORECASE,
)
YEAR_RANGE_PATTERN = re.compile(
    r"\b(19\d{2}|20\d{2})\s*[-–]\s*(Present|Current|Now|19\d{2}|20\d{2})\b",
    re.IGNORECASE,
)
SECTION_HEADER_PATTERN = re.compile(
    r"^\s*(work experience|professional experience|experience|education)\s*:?\s*$",
    re.IGNORECASE,
)
SUMMARY_HEADER_PATTERN = re.compile(
    r"^\s*(summary|professional summary|profile|about me|career summary)\s*:?\s*$",
    re.IGNORECASE,
)

MONTH_MAP = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

US_STATE_NAME_TO_CODE = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "district of columbia": "DC",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID", "illinois": "IL",
    "indiana": "IN", "iowa": "IA", "kansas": "KS", "kentucky": "KY", "louisiana": "LA",
    "maine": "ME", "maryland": "MD", "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR",
    "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC", "south dakota": "SD",
    "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT", "virginia": "VA",
    "washington": "WA", "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
}
US_STATE_CODES = set(US_STATE_NAME_TO_CODE.values())
EXPLICIT_CLAIM_NOISE_WORDS = (
    "industry",
    "founded",
    "began",
    "since",
    "ago",
    "platform",
    "company",
)


def _month_index(year: int, month: int) -> int:
    return (year * 12) + month


def _merge_month_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not intervals:
        return []
    ordered = sorted(intervals, key=lambda item: item[0])
    merged = [ordered[0]]
    for start_idx, end_idx in ordered[1:]:
        last_start, last_end = merged[-1]
        if start_idx <= last_end:
            merged[-1] = (last_start, max(last_end, end_idx))
        else:
            merged.append((start_idx, end_idx))
    return merged


def _parse_end_year(value: str) -> int:
    if value.lower() in {"present", "current", "now"}:
        return datetime.now(UTC).year
    return int(value)


def _extract_explicit_experience_years_claim(text: str) -> float | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    search_lines = lines[:60]
    values: list[float] = []
    for line in search_lines:
        lowered = line.lower()
        matches = list(YEARS_OF_EXPERIENCE_PATTERN.finditer(line))
        if not matches and "summary" not in lowered and "objective" not in lowered:
            matches = [
                match
                for match in ALT_YEARS_OF_EXPERIENCE_PATTERN.finditer(line)
                if any(keyword in lowered for keyword in ("experience", "business analyst", "developer", "engineer", "analyst", "consultant", "architect", "administrator", "manager"))
            ]
        if not matches and any(noise in lowered for noise in EXPLICIT_CLAIM_NOISE_WORDS):
            continue
        for match in matches:
            try:
                values.append(float(match.group("years")))
            except ValueError:
                continue
    if not values:
        return None
    return round(max(values), 1)


def _extract_probable_full_name(text: str) -> str | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    header_window = lines[:8]
    has_contact_nearby = any(
        ("@" in line) or ("email" in line.lower()) or ("contact" in line.lower()) or ("phone" in line.lower())
        for line in header_window
    )
    for line in header_window:
        lowered = line.lower()
        if "@" in line or "email" in lowered or "contact" in lowered or "phone" in lowered:
            continue
        if any(token in lowered for token in ("summary", "experience", "education", "skills", "resume")):
            continue
        if any(token in lowered for token in ("certified", "certification", "scrum", "developer", "analyst", "master")):
            continue
        if not has_contact_nearby:
            continue
        word_count = len(line.split())
        if 2 <= word_count <= 5 and re.fullmatch(r"[A-Za-z .'-]+", line):
            return line
    return None


def _extract_professional_summary(text: str) -> str | None:
    lines = text.splitlines()
    collecting = False
    summary_lines: list[str] = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            if collecting and summary_lines:
                break
            continue
        if SUMMARY_HEADER_PATTERN.match(line):
            collecting = True
            continue
        if collecting and SECTION_HEADER_PATTERN.match(line):
            break
        if collecting:
            summary_lines.append(line)
            if len(summary_lines) >= 8:
                break
    if not summary_lines:
        return None
    return " ".join(summary_lines).strip()


def _extract_experience_years(text: str) -> tuple[float | None, str]:
    explicit_years = _extract_explicit_experience_years_claim(text)

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    in_work_section = False
    work_lines: list[str] = []
    for line in lines:
        header_match = SECTION_HEADER_PATTERN.match(line)
        if header_match:
            header = header_match.group(1).lower()
            if "work experience" in header or header == "experience" or "professional experience" in header:
                in_work_section = True
                continue
            if header == "education":
                in_work_section = False
                continue
        if in_work_section:
            work_lines.append(line)

    source_text = "\n".join(work_lines) if work_lines else text

    intervals: list[tuple[int, int]] = []
    for match in MONTH_YEAR_RANGE_PATTERN.findall(source_text):
        start_month_txt, start_year_txt, end_month_or_word, end_year_txt = match
        start_month = MONTH_MAP.get(start_month_txt.lower())
        if not start_month:
            continue
        start_year = int(start_year_txt)

        if end_month_or_word.lower() in {"present", "current", "now"}:
            end_month = datetime.now(UTC).month
            end_year = datetime.now(UTC).year
        else:
            end_month = MONTH_MAP.get(end_month_or_word.lower())
            if not end_month:
                continue
            end_year = int(end_year_txt) if end_year_txt else datetime.now(UTC).year

        start_idx = _month_index(start_year, start_month)
        end_idx = _month_index(end_year, end_month)
        if end_idx >= start_idx:
            intervals.append((start_idx, end_idx))

    for match in YEAR_RANGE_PATTERN.findall(source_text):
        start_year_txt, end_year_txt = match
        start_year = int(start_year_txt)
        end_year = _parse_end_year(end_year_txt)
        start_idx = _month_index(start_year, 1)
        end_idx = _month_index(end_year, 12)
        if end_idx >= start_idx:
            intervals.append((start_idx, end_idx))

    merged = _merge_month_intervals(intervals)
    total_months = sum((end - start) + 1 for start, end in merged)
    inferred_years = round(total_months / 12.0, 1) if total_months > 0 else None
    # Guardrail: reject suspiciously high explicit claims when date-derived value exists.
    if explicit_years is not None and inferred_years is not None:
        if explicit_years > (inferred_years + 6.0):
            return float(inferred_years), "inferred_dates_overrode_noisy_claim"
        return float(explicit_years), "explicit_preferred"
    if explicit_years is not None:
        return float(explicit_years), "explicit_preferred"
    if inferred_years is not None:
        return float(inferred_years), "inferred_from_dates"
    return None, "not_found"


def _normalize_us_location(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = " ".join(str(value).strip().split())
    cleaned = re.sub(r",?\s*(USA|US|United States)\b", "", cleaned, flags=re.IGNORECASE).strip(" ,")
    cleaned = ZIP_TRAIL_PATTERN.sub("", cleaned).strip(" ,")

    if "," not in cleaned:
        return None

    city_raw, state_raw = [part.strip() for part in cleaned.rsplit(",", 1)]
    if not city_raw or not state_raw:
        return None

    state_code = None
    state_upper = state_raw.upper()
    if state_upper in US_STATE_CODES:
        state_code = state_upper
    else:
        state_code = US_STATE_NAME_TO_CODE.get(state_raw.lower())

    if not state_code:
        return None

    city = " ".join(word.capitalize() for word in city_raw.split())
    return f"{city}, {state_code}"


def _extract_candidate_location_from_top(
    lines: list[str],
    *,
    email: str | None,
    phone: str | None,
) -> str | None:
    top_lines = lines[:35]

    # 1) Explicit location labels in top section.
    for line in top_lines:
        m = re.search(r"(?:^|\b)(?:location|based in|address)\s*[:\-]\s*(.+)$", line, flags=re.IGNORECASE)
        if m:
            normalized = _normalize_us_location(m.group(1))
            if normalized:
                return normalized

    # 2) Contact-header line near email/phone.
    for line in top_lines[:20]:
        has_email = bool(email and email in line)
        has_phone = bool(phone and phone in line)
        if not (has_email or has_phone):
            continue
        for part in CONTACT_DELIM_PATTERN.split(line):
            normalized = _normalize_us_location(part)
            if normalized:
                return normalized

    # 3) Generic city/state match only in likely header lines.
    for line in top_lines[:8]:
        match = LOCATION_LINE_PATTERN.search(line)
        if match:
            normalized = _normalize_us_location(match.group(1))
            if normalized:
                return normalized

    return None


def resolve_file_path(file_url: str) -> Path:
    raw = Path(file_url)
    if raw.is_absolute() and raw.exists():
        return raw

    repo_root = Path(__file__).resolve().parents[2]
    candidates = [
        repo_root / file_url,
        repo_root / "backend" / file_url,
        Path.cwd() / file_url,
    ]
    for item in candidates:
        if item.exists():
            return item
    return raw


def _text_looks_weak(text: str) -> bool:
    compact = (text or "").strip()
    return len(compact) < 300 or len(compact.split()) < 60


def _extract_with_unstructured(path: Path) -> str | None:
    try:
        from unstructured.partition.auto import partition
    except Exception:
        return None

    try:
        elements = partition(filename=str(path))
        parts = []
        for element in elements:
            value = getattr(element, "text", None)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
        combined = "\n".join(parts).strip()
        return combined if combined else None
    except Exception:
        return None


def _extract_with_docling(path: Path) -> str | None:
    try:
        from docling.document_converter import DocumentConverter
    except Exception:
        return None

    try:
        converter = DocumentConverter()
        result = converter.convert(str(path))
        document = getattr(result, "document", None)
        if document is None:
            return None

        if hasattr(document, "export_to_text"):
            text = document.export_to_text()
            if isinstance(text, str) and text.strip():
                return text

        if hasattr(document, "export_to_markdown"):
            markdown = document.export_to_markdown()
            if isinstance(markdown, str) and markdown.strip():
                return markdown
    except Exception:
        return None

    return None


def _parse_text_from_file_legacy(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        doc = fitz.open(path)
        text = "\n".join(page.get_text("text") for page in doc)
        if _text_looks_weak(text):
            fallback = _extract_with_unstructured(path)
            if fallback:
                return fallback
        return text

    if suffix == ".docx":
        doc = Document(path)
        lines = [para.text.strip() for para in doc.paragraphs if para.text.strip()]
        text = "\n".join(lines)
        if _text_looks_weak(text):
            fallback = _extract_with_unstructured(path)
            if fallback:
                return fallback
        return text

    text = path.read_text(encoding="utf-8", errors="ignore")
    if _text_looks_weak(text):
        fallback = _extract_with_unstructured(path)
        if fallback:
            return fallback
    return text


def parse_text_from_file(path: Path) -> str:
    # New primary parser: docling (when installed and enabled).
    if USE_DOCLING_PARSER and path.suffix.lower() in {".pdf", ".docx"}:
        docling_text = _extract_with_docling(path)
        if isinstance(docling_text, str) and docling_text.strip() and not _text_looks_weak(docling_text):
            return docling_text

    # Legacy parser backup (previous implementation).
    return _parse_text_from_file_legacy(path)


def extract_resume_features(text: str) -> dict[str, Any]:
    text_lower = text.lower()
    skills = [skill for skill in SKILL_KEYWORDS if skill in text_lower]
    emails = EMAIL_PATTERN.findall(text)
    phones = PHONE_PATTERN.findall(text)
    full_name = _extract_probable_full_name(text)
    professional_summary = _extract_professional_summary(text)
    explicit_claimed_years = _extract_explicit_experience_years_claim(text)

    # Heuristic only as fallback
    experience_years, experience_source = _extract_experience_years(text)
    work_excerpt = _extract_work_excerpt(text)
    experience_entries = extract_experience_entries_from_blocks(work_excerpt)
    experience_calculation = _build_experience_calculation(experience_entries)
    current_last_job = None
    if experience_entries:
        current_last_job = experience_entries[0].get("title")

    calculated_years = experience_calculation.get("total_years")
    if explicit_claimed_years is not None:
        experience_years = round(float(explicit_claimed_years), 1)
        experience_source = "explicit_claim_from_summary"
    elif isinstance(calculated_years, (int, float)):
        experience_years = round(float(calculated_years), 1)
        experience_source = "python_from_experience_entries"
    elif experience_source == "inferred_from_dates":
        # Raw date fallback is too noisy without structured role extraction.
        experience_years = None
        experience_source = "unreliable_raw_date_fallback"

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    candidate_location = _extract_candidate_location_from_top(
        lines,
        email=emails[0] if emails else None,
        phone=phones[0] if phones else None,
    )

    if "master" in text_lower:
        highest_degree = "Master's"
    elif "bachelor" in text_lower:
        highest_degree = "Bachelor's"
    elif "associate" in text_lower:
        highest_degree = "Associate's"
    elif "phd" in text_lower or "doctor" in text_lower:
        highest_degree = "PhD"
    else:
        highest_degree = None

    if NO_SPONSOR_PATTERN.search(text):
        sponsorship_required = False
    elif YES_SPONSOR_PATTERN.search(text):
        sponsorship_required = True
    else:
        sponsorship_required = None

    return {
        "full_name": full_name,
        "email": emails[0] if emails else None,
        "phone": phones[0] if phones else None,
        "linkedin_url": None,
        "github_url": None,
        "portfolio_url": None,
        "professional_summary": professional_summary,
        "skills": sorted(set(skills)),
        "languages": [],
        "education": [],
        "experience_years": experience_years,
        "experience_source": experience_source,
        "experience_years_claimed": explicit_claimed_years,
        "experience_years_calculated": calculated_years,
        "experience_years_final": experience_years,
        "experience_entries": experience_entries,
        "experience_calculation": experience_calculation,
        "highest_degree": highest_degree,
        "sponsorship_required": sponsorship_required,
        "distance_miles": None,
        "candidate_location": candidate_location,
        "current_last_job": current_last_job,
        "raw_text_quality": None,
        "parser_notes": [],
        "field_confidence": {},
    }


def _parse_quality_is_weak(parsed: dict[str, Any]) -> bool:
    missing_email = not parsed.get("email")
    missing_skills = not parsed.get("skills")
    missing_experience = parsed.get("experience_years") is None
    return (missing_email and missing_skills) or (missing_skills and missing_experience)


def _merge_llm_fields(parsed: dict[str, Any], llm_parsed: dict[str, Any]) -> dict[str, Any]:
    merged = dict(parsed)
    def _missing(value: Any) -> bool:
        return value is None or (isinstance(value, str) and not value.strip())

    for key in (
        "email",
        "phone",
        "highest_degree",
        "current_last_job",
        "sponsorship_required",
    ):
        if _missing(merged.get(key)) and not _missing(llm_parsed.get(key)):
            merged[key] = llm_parsed.get(key)

    # Python location is preferred for consistency; only fallback to LLM when missing.
    if not merged.get("candidate_location") and llm_parsed.get("candidate_location"):
        merged["candidate_location"] = llm_parsed.get("candidate_location")

    merged["candidate_location"] = _normalize_us_location(merged.get("candidate_location"))

    llm_skills = llm_parsed.get("skills")
    if isinstance(llm_skills, list) and llm_skills:
        combined = {*(merged.get("skills") or []), *(str(s).lower() for s in llm_skills)}
        merged["skills"] = sorted(combined)

    llm_final = llm_parsed.get("experience_years_final")
    llm_calc = llm_parsed.get("experience_years_calculated")
    llm_plain = llm_parsed.get("experience_years")

    current_experience = merged.get("experience_years")
    for value, source in (
        (llm_final, llm_parsed.get("experience_source")),
        (llm_calc, "python_from_experience_entries"),
        (llm_plain, llm_parsed.get("experience_source")),
    ):
        if value is llm_plain and current_experience is not None:
            # Do not let weak/free-form LLM guess override an existing numeric value.
            continue
        if isinstance(value, (int, float)):
            merged["experience_years"] = round(float(value), 1)
            merged["experience_source"] = source or "llm_preferred"
            break
        if isinstance(value, str):
            try:
                merged["experience_years"] = round(float(value), 1)
                merged["experience_source"] = source or "llm_preferred"
                break
            except ValueError:
                pass

    if llm_parsed.get("experience_years_claimed") is not None:
        merged["experience_years_claimed"] = llm_parsed.get("experience_years_claimed")
    if llm_parsed.get("experience_years_calculated") is not None:
        merged["experience_years_calculated"] = llm_parsed.get("experience_years_calculated")
    if llm_parsed.get("experience_years_final") is not None:
        merged["experience_years_final"] = llm_parsed.get("experience_years_final")
    llm_entries = llm_parsed.get("experience_entries")
    if isinstance(llm_entries, list) and llm_entries:
        merged["experience_entries"] = llm_entries

    return merged


def _finalize_llm_primary_parse(text: str, llm_parsed: dict[str, Any], python_parsed: dict[str, Any]) -> dict[str, Any]:
    finalized = dict(llm_parsed)

    for key in (
        "full_name",
        "email",
        "phone",
        "highest_degree",
        "candidate_location",
        "current_last_job",
        "sponsorship_required",
        "linkedin_url",
        "github_url",
        "portfolio_url",
        "professional_summary",
        "distance_miles",
        "raw_text_quality",
    ):
        if finalized.get(key) is None and python_parsed.get(key) is not None:
            finalized[key] = python_parsed.get(key)

    if not finalized.get("skills") and python_parsed.get("skills"):
        finalized["skills"] = python_parsed.get("skills", [])

    if not finalized.get("languages") and python_parsed.get("languages"):
        finalized["languages"] = python_parsed.get("languages", [])

    if not finalized.get("education") and python_parsed.get("education"):
        finalized["education"] = python_parsed.get("education", [])

    if not finalized.get("parser_notes") and python_parsed.get("parser_notes"):
        finalized["parser_notes"] = python_parsed.get("parser_notes", [])

    if not finalized.get("field_confidence") and python_parsed.get("field_confidence"):
        finalized["field_confidence"] = python_parsed.get("field_confidence", {})

    if not finalized.get("experience_entries") and python_parsed.get("experience_entries"):
        finalized["experience_entries"] = python_parsed.get("experience_entries", [])

    if finalized.get("experience_entries"):
        experience_calculation = _build_experience_calculation(finalized["experience_entries"])
        finalized["experience_calculation"] = experience_calculation
        calculated_years = experience_calculation.get("total_years")
        finalized["experience_years_calculated"] = calculated_years
        if finalized.get("current_last_job") is None and finalized["experience_entries"]:
            finalized["current_last_job"] = finalized["experience_entries"][0].get("title")
    else:
        finalized["experience_calculation"] = python_parsed.get("experience_calculation")
        finalized["experience_years_calculated"] = python_parsed.get("experience_years_calculated")

    if finalized.get("experience_years_claimed") is None:
        finalized["experience_years_claimed"] = python_parsed.get("experience_years_claimed")
    if finalized.get("experience_years_final") is None and finalized.get("experience_years_claimed") is not None:
        finalized["experience_years_final"] = finalized["experience_years_claimed"]

    if finalized.get("experience_years_claimed") is not None:
        finalized["experience_years"] = finalized["experience_years_claimed"]
        finalized["experience_years_final"] = finalized["experience_years_claimed"]
        finalized["experience_source"] = "explicit_claim_from_summary"
    elif finalized.get("experience_years_calculated") is not None:
        finalized["experience_years"] = finalized["experience_years_calculated"]
        finalized["experience_years_final"] = finalized["experience_years_calculated"]
        finalized["experience_source"] = "python_from_experience_entries"
    else:
        finalized["experience_years"] = python_parsed.get("experience_years")
        finalized["experience_years_final"] = python_parsed.get("experience_years_final")
        finalized["experience_source"] = python_parsed.get("experience_source")

    return finalized


def _experience_parse_diagnostics(text: str, parsed: dict[str, Any]) -> dict[str, Any]:
    calculation = parsed.get("experience_calculation")
    if isinstance(calculation, dict) and isinstance(calculation.get("roles"), list):
        roles = calculation["roles"]
        with_dates = sum(1 for role in roles if role.get("start_date") or role.get("end_date"))
        missing_dates = sum(1 for role in roles if not role.get("start_date") and not role.get("end_date"))
    else:
        entries = parsed.get("experience_entries")
        if not isinstance(entries, list):
            entries = []

        with_dates = 0
        missing_dates = 0
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if entry.get("start_date") or entry.get("end_date"):
                with_dates += 1
            else:
                missing_dates += 1

    yyyymm_detected = bool(
        re.search(r"\b\d{4}[-/.]\d{1,2}\s*[-–—]\s*(?:\d{4}[-/.]\d{1,2}|Present|Current|Now)\b", text, re.IGNORECASE)
    )

    return {
        "date_format_detected": ["yyyy_mm_range"] if yyyymm_detected else [],
        "experience_entry_count_with_dates": with_dates,
        "experience_entry_count_missing_dates": missing_dates,
    }


def mark_resume_failed(resume_id: str, error: str) -> None:
    with psycopg.connect(WORKER_DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE resumes
                SET parse_status = 'failed',
                    parse_error = %s
                WHERE id = %s::uuid
                """,
                (error[:1500], resume_id),
            )
        conn.commit()


def persist_parsed_resume(resume_id: str, text: str, parsed: dict[str, Any]) -> None:
    diagnostics = _experience_parse_diagnostics(text, parsed)
    with psycopg.connect(WORKER_DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT candidate_id FROM resumes WHERE id = %s::uuid", (resume_id,))
            result = cur.fetchone()
            if not result:
                raise ValueError(f"Resume not found: {resume_id}")
            candidate_id = result[0]

            cur.execute(
                """
                UPDATE resumes
                SET raw_text = %s,
                    parsed_json = %s,
                    skills_json = %s,
                    experience_years = %s,
                    parse_status = 'parsed',
                    parse_error = NULL
                WHERE id = %s::uuid
                """,
                (
                    text,
                    Json(
                        {
                            "full_name": parsed.get("full_name"),
                            "email": parsed.get("email"),
                            "phone": parsed.get("phone"),
                            "linkedin_url": parsed.get("linkedin_url"),
                            "github_url": parsed.get("github_url"),
                            "portfolio_url": parsed.get("portfolio_url"),
                            "professional_summary": parsed.get("professional_summary"),
                            "skills": parsed.get("skills", []),
                            "languages": parsed.get("languages", []),
                            "education": parsed.get("education", []),
                            "experience_years": parsed.get("experience_years"),
                            "experience_source": parsed.get("experience_source"),
                            "experience_years_claimed": parsed.get("experience_years_claimed"),
                            "experience_years_calculated": parsed.get("experience_years_calculated"),
                            "experience_years_final": parsed.get("experience_years_final"),
                            "experience_entries": parsed.get("experience_entries", []),
                            "experience_calculation": parsed.get("experience_calculation"),
                            "parse_diagnostics": diagnostics,
                            "highest_degree": parsed.get("highest_degree"),
                            "sponsorship_required": parsed.get("sponsorship_required"),
                            "distance_miles": parsed.get("distance_miles"),
                            "candidate_location": parsed.get("candidate_location"),
                            "current_last_job": parsed.get("current_last_job"),
                            "raw_text_quality": parsed.get("raw_text_quality"),
                            "parser_notes": parsed.get("parser_notes", []),
                            "field_confidence": parsed.get("field_confidence", {}),
                        }
                        ),
                    
                    Json(parsed.get("skills", [])),
                    parsed.get("experience_years"),
                    resume_id,
                ),
            )

            if parsed.get("email"):
                cur.execute(
                    """
                    SELECT id
                    FROM candidates
                    WHERE primary_email = %s
                      AND id <> %s::uuid
                    LIMIT 1
                    """,
                    (parsed["email"], candidate_id),
                )
                existing_owner = cur.fetchone()
            else:
                existing_owner = None

            safe_email = None if existing_owner else parsed.get("email")

            cur.execute(
                """
                UPDATE candidates
                SET full_name = COALESCE(full_name, %s),
                    primary_email = COALESCE(primary_email, %s),
                    phone = COALESCE(phone, %s),
                    location = COALESCE(location, %s),
                    linkedin_url = COALESCE(linkedin_url, %s)
                WHERE id = %s::uuid
                """,
                (
                    parsed.get("full_name"),
                    safe_email,
                    parsed.get("phone"),
                    parsed.get("candidate_location"),
                    parsed.get("linkedin_url"),
                    candidate_id,
                ),
            )
        conn.commit()


def run_ingestion_worker() -> None:
    client = redis.from_url(REDIS_URL, decode_responses=True)
    print(f"Worker connected to Redis at {REDIS_URL}")
    print(f"Listening queue: {INGESTION_QUEUE_KEY}")

    while True:
        item = client.blpop(INGESTION_QUEUE_KEY, timeout=5)
        if not item:
            continue

        _, payload = item
        try:
            message = json.loads(payload)
            job_id = message.get("job_id")
            resume_id = message.get("resume_id")
            file_url = message.get("file_url")
            print(f"[INGEST] job={job_id} resume={resume_id} file={file_url}")

            resolved_path = resolve_file_path(file_url)
            text = parse_text_from_file(resolved_path)
            if not text.strip():
                raise ValueError("No extractable text found in resume")

            python_parsed = extract_resume_features(text)
            parsed = dict(python_parsed)

            if ENABLE_LLM_PARSE:
                llm_parsed = parse_resume_with_llm(text)
                if llm_parsed:
                    reconciled = reconcile_resume_parse_with_llm(
                        text,
                        llm_parsed=llm_parsed,
                        python_parsed=python_parsed,
                    )
                    parsed = _finalize_llm_primary_parse(text, reconciled or llm_parsed, python_parsed)
                    # Legacy hybrid flow kept for fallback:
                    # if LLM_PARSE_ONLY:
                    #     parsed = _merge_llm_fields({...}, llm_parsed)
                    # else:
                    #     parsed = _merge_llm_fields(parsed, llm_parsed)
                    # normalized = normalize_resume_fields_with_llm(text, parsed)
                    # if normalized:
                    #     parsed = _merge_llm_fields(parsed, normalized)
                else:
                    parsed = python_parsed

            print("==== FINAL PARSED BEFORE SAVE ====")
            print(json.dumps(parsed, indent=2, default=str))

            persist_parsed_resume(resume_id, text, parsed)
            time.sleep(0.2)
            print(f"[DONE] resume={resume_id}")

        except json.JSONDecodeError:
            print(f"[ERROR] invalid payload: {payload}")
        except Exception as exc:
            resume_id = None
            try:
                decoded = json.loads(payload)
                resume_id = decoded.get("resume_id")
            except Exception:
                pass

            print(f"[ERROR] ingestion failed for resume={resume_id}: {exc}")
            if resume_id:
                mark_resume_failed(str(resume_id), str(exc))


if __name__ == "__main__":
    run_ingestion_worker()
