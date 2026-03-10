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
LLM_PARSE_MODEL = os.getenv("OPENAI_PARSE_MODEL", "gpt-4.1-mini")
LLM_PARSE_TIMEOUT = int(os.getenv("LLM_PARSE_TIMEOUT_SECONDS", "60"))
LLM_PARSE_MAX_RETRIES = int(os.getenv("LLM_PARSE_MAX_RETRIES", "2"))

WORK_START_PATTERN = re.compile(
    r"^(work experience|professional experience|employment history|experience)\s*:?\s*$",
    re.IGNORECASE,
)

WORK_END_PATTERN = re.compile(
    r"^(education|certifications|projects|skills|publications|awards|activities)\s*:?\s*$",
    re.IGNORECASE,
)

SECTION_EXCLUDE_HEADERS = re.compile(
    r"^(skills|projects|certifications|education|publications|awards|activities)\b",
    re.IGNORECASE,
)

JOB_HEADER_PATTERN = re.compile(
    r"^(?P<company>.+?)\s*\|\s*(?P<title>.+?)$"
)

INLINE_JOB_PATTERN = re.compile(
    r"^(?P<company>.+?)\s*\|\s*(?P<title>.+?)\s+(?P<location>[^|]+?)\s*\|\s*(?P<dates>.+)$",
    re.IGNORECASE,
)

DATE_LOCATION_LINE_PATTERN = re.compile(
    r"^(?P<location>.+?)\s*\|\s*(?P<dates>.+)$",
    re.IGNORECASE,
)
CLIENT_LINE_PATTERN = re.compile(r"^Client:\s*(?P<company>.+?)\s*,\s*(?P<location>[A-Za-z]{2}|[A-Za-z .'-]+)\s+(?P<dates>.+)$", re.IGNORECASE)
ROLE_LINE_PATTERN = re.compile(r"^Role:\s*(?P<title>.+)$", re.IGNORECASE)

DATE_RANGE_PATTERNS = [
    re.compile(
        r"(?P<sy>\d{4})[-/.](?P<sm>\d{1,2})\s*[-–—to]+\s*(?:(?P<ey>\d{4})[-/.](?P<em>\d{1,2})|(?P<ep>Present|Current|Now|Today))",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?P<smon>[A-Za-z]{3,9})\s+(?P<syr>\d{4})\s*[-–—to]+\s*(?P<emon>[A-Za-z]{3,9}|Present|Current|Now|Today|Till(?:\s+Date)?)\s*(?P<eyr>\d{4})?",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?P<smo>\d{1,2})/(?P<syr>\d{4})\s*[-–—to]+\s*(?P<emo>\d{1,2}|Present|Current|Now|Today|Till(?:\s+Date)?)\s*/?(?P<eyr>\d{4})?",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?P<syr>\d{4})\s*[-–—to]+\s*(?P<eyr>\d{4}|Present|Current|Now|Today|Till(?:\s+Date)?)",
        re.IGNORECASE,
    ),
]

EXPLICIT_EXPERIENCE_PATTERN = re.compile(
    r"(?:(?:over|more\s+than|approximately|around|nearly)\s+)?"
    r"(?P<years>\d+(?:\.\d+)?)\s*\+?\s*"
    r"(?:years?|yrs?)"
    r"(?:\s+of)?(?:\s+\w+){0,6}?\s+experience",
    re.IGNORECASE,
)
EXPLICIT_NOISE_WORDS = (
    "industry",
    "company",
    "founded",
    "began",
    "since",
    "ago",
    "platform",
)

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

PRESENT_WORDS = {"present", "current", "now", "today", "till", "till date"}

DEGREE_KEYWORDS = {
    "bachelor", "master", "mba", "phd", "doctor", "b.tech", "m.tech",
    "b.s", "m.s", "bs", "ms", "bachelors", "masters"
}


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
                detail = exc.read().decode("utf-8", errors="ignore")[:1000]
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


def parse_resume_with_llm(text: str) -> dict[str, Any] | None:
    work_excerpt = _extract_work_excerpt(text)
    python_entries = extract_experience_entries_from_blocks(work_excerpt)
    claimed_years = _extract_explicit_experience_years(text)

    system_prompt = (
        "You are a strict resume parsing engine.\n"
        "Return ONLY valid JSON. No markdown. No explanation.\n\n"
        "Return EXACTLY this object shape:\n"
        "{\n"
        '  "email": string|null,\n'
        '  "phone": string|null,\n'
        '  "skills": string[],\n'
        '  "highest_degree": string|null,\n'
        '  "candidate_location": string|null,\n'
        '  "current_last_job": string|null,\n'
        '  "experience_years_claimed": number|null,\n'
        '  "experience_entries": [\n'
        "    {\n"
        '      "title": string|null,\n'
        '      "company": string|null,\n'
        '      "start_date": string|null,\n'
        '      "end_date": string|null,\n'
        '      "is_current": boolean,\n'
        '      "section": string|null,\n'
        '      "employment_type": string|null\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Rules:\n"
        "1) Do NOT calculate total experience from roles.\n"
        "2) Capture ALL professional experience roles present in the provided experience section.\n"
        "3) Do NOT omit older roles just because the resume is long.\n"
        "4) If many companies are present, include all of them in experience_entries.\n"
        "5) When company/title/location/date appear on one line, treat them as one role.\n"
        "6) Include internships only if they are part of professional work history.\n"
        "7) Exclude education, certifications, and training sections.\n"
        "8) Normalize dates as YYYY-MM, YYYY, or null.\n"
        "9) current_last_job must be title only.\n"
        "10) candidate_location must be US-only in format 'City, ST'; if uncertain or non-US, return null.\n"
        "11) Prefer extracting from the full raw resume text, not only the experience section.\n"
        "12) If dates are written as YYYY-MM to YYYY-MM, preserve them in normalized form."
    )

    header_excerpt = _extract_header_excerpt(text, max_lines=35)
    user_prompt = (
        f"Resume Header Excerpt (contact/details):\n{header_excerpt[:3000]}\n\n"
        f"Full Resume Text:\n{text[:24000]}\n\n"
        f"Work Experience Section:\n{work_excerpt[:12000]}\n\n"
        f"Python detected experience entries:\n"
        f"{json.dumps(python_entries[:100], ensure_ascii=False)}\n\n"
        f"Explicit claimed years detected by regex: {claimed_years}\n"
    )
    # Legacy prompt path kept for quick fallback:
    # user_prompt = (
    #     f"Resume Header Excerpt (contact/details):\n{header_excerpt[:3000]}\n\n"
    #     f"Work Experience Section:\n{work_excerpt[:20000]}\n\n"
    #     f"Python detected experience entries:\n"
    #     f"{json.dumps(python_entries[:100], ensure_ascii=False)}\n\n"
    #     f"Full Resume (truncated):\n{text[:12000]}"
    # )

    payload = {
        "model": LLM_PARSE_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
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

    parsed = _normalize_llm_parse_output(parsed, text)

    llm_entries = parsed.get("experience_entries", [])
    if not llm_entries and python_entries:
        parsed["experience_entries"] = python_entries

    parsed["experience_years_claimed"] = claimed_years
    parsed["experience_years_calculated"] = _calculate_experience_years_from_entries(parsed["experience_entries"])

    if parsed["experience_years_calculated"] is None:
        parsed["experience_years_calculated"] = _calculate_experience_years_from_raw_text(work_excerpt)

    final_years, source = _pick_final_experience_years(
        claimed=parsed.get("experience_years_claimed"),
        calculated=parsed.get("experience_years_calculated"),
    )

    parsed["experience_calculation"] = _build_experience_calculation(parsed["experience_entries"])
    parsed["experience_years_final"] = final_years
    parsed["experience_years"] = final_years
    parsed["experience_source"] = source
    return parsed


def normalize_resume_fields_with_llm(text: str, preliminary: dict[str, Any]) -> dict[str, Any] | None:
    work_excerpt = _extract_work_excerpt(text)
    python_entries = extract_experience_entries_from_blocks(work_excerpt)
    claimed_years = _extract_explicit_experience_years(text)
    header_excerpt = _extract_header_excerpt(text, max_lines=35)

    system_prompt = (
        "You normalize resume extraction output.\n"
        "Return ONLY valid JSON. No markdown.\n\n"
        "Return EXACTLY these keys:\n"
        "email, phone, skills, highest_degree, sponsorship_required, "
        "candidate_location, current_last_job, experience_years_claimed, experience_entries.\n\n"
        "Rules:\n"
        "1) skills must be unique canonical strings.\n"
        "2) current_last_job must be title only.\n"
        "3) sponsorship_required must be true, false, or null.\n"
        "4) Do NOT calculate total experience from dates.\n"
        "5) Preserve only real professional work history in experience_entries.\n"
        "6) Normalize dates strictly as 'YYYY-MM', 'YYYY', or null.\n"
        "7) candidate_location must be US-only in format 'City, ST'; if uncertain or non-US, return null."
    )

    user_prompt = (
        f"Resume Header Excerpt:\n{header_excerpt[:3000]}\n\n"
        f"Work Experience Excerpt:\n{work_excerpt[:40000]}\n\n"
        f"Python-detected experience entries from job blocks:\n"
        f"{json.dumps(python_entries[:100], ensure_ascii=False)}\n\n"
        f"Explicit claimed years detected by regex: {claimed_years}\n\n"
        f"Preliminary Parsed JSON:\n{json.dumps(preliminary, ensure_ascii=False)}"
    )

    payload = {
        "model": LLM_PARSE_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {"type": "json_object"},
    }

    response = _post_chat_completions(payload)
    if not response:
        logger.warning("[LLM_PARSE] No usable normalization response from OpenAI")
        return None

    parsed = _extract_json_from_openai_response(response)
    if not parsed:
        return None

    parsed = _normalize_llm_parse_output(parsed, text)
    parsed["experience_years_calculated"] = _calculate_experience_years_from_entries(parsed["experience_entries"])

    if parsed["experience_years_calculated"] is None:
        parsed["experience_years_calculated"] = _calculate_experience_years_from_raw_text(work_excerpt)

    final_years, source = _pick_final_experience_years(
        claimed=parsed.get("experience_years_claimed"),
        calculated=parsed.get("experience_years_calculated"),
    )

    parsed["experience_calculation"] = _build_experience_calculation(parsed["experience_entries"])
    parsed["experience_years_final"] = final_years
    parsed["experience_years"] = final_years
    parsed["experience_source"] = source
    return parsed


def reconcile_resume_parse_with_llm(
    text: str,
    *,
    llm_parsed: dict[str, Any],
    python_parsed: dict[str, Any],
) -> dict[str, Any] | None:
    discrepancies = _summarize_parse_discrepancies(llm_parsed=llm_parsed, python_parsed=python_parsed)
    if not discrepancies:
        return None

    system_prompt = (
        "You are a strict resume parsing validator.\n"
        "Return ONLY valid JSON. No markdown. No explanation.\n\n"
        "Use the full raw resume text as the source of truth.\n"
        "You are given two candidate parses: one from an LLM and one from Python heuristics.\n"
        "Resolve disparities and return ONE corrected final JSON object.\n\n"
        "Return EXACTLY this object shape:\n"
        "{\n"
        '  "email": string|null,\n'
        '  "phone": string|null,\n'
        '  "skills": string[],\n'
        '  "highest_degree": string|null,\n'
        '  "candidate_location": string|null,\n'
        '  "current_last_job": string|null,\n'
        '  "experience_years_claimed": number|null,\n'
        '  "experience_entries": [\n'
        "    {\n"
        '      "title": string|null,\n'
        '      "company": string|null,\n'
        '      "start_date": string|null,\n'
        '      "end_date": string|null,\n'
        '      "is_current": boolean,\n'
        '      "section": string|null,\n'
        '      "employment_type": string|null,\n'
        '      "location": string|null\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Rules:\n"
        "1) Prefer explicit summary years only when they clearly refer to total work experience.\n"
        "2) current_last_job must be title only.\n"
        "3) candidate_location must be US-only in format 'City, ST'; otherwise null.\n"
        "4) Exclude education/project-only entries from experience_entries.\n"
        "5) Normalize dates strictly as YYYY-MM, YYYY, or null.\n"
        "6) If one parser is clearly wrong and the raw text is clear, fix it."
    )
    user_prompt = (
        f"Full Resume Text:\n{text[:26000]}\n\n"
        f"LLM Parse:\n{json.dumps(llm_parsed, ensure_ascii=False)}\n\n"
        f"Python Validation Parse:\n{json.dumps(python_parsed, ensure_ascii=False)}\n\n"
        f"Detected Discrepancies:\n{json.dumps(discrepancies, ensure_ascii=False)}"
    )
    payload = {
        "model": LLM_PARSE_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {"type": "json_object"},
    }

    response = _post_chat_completions(payload)
    if not response:
        logger.warning("[LLM_PARSE] No usable reconciliation response from OpenAI")
        return None

    parsed = _extract_json_from_openai_response(response)
    if not parsed:
        return None

    parsed = _normalize_llm_parse_output(parsed, text)
    parsed["experience_years_calculated"] = _calculate_experience_years_from_entries(parsed["experience_entries"])
    if parsed["experience_years_calculated"] is None:
        parsed["experience_years_calculated"] = _calculate_experience_years_from_raw_text(_extract_work_excerpt(text))
    final_years, source = _pick_final_experience_years(
        claimed=parsed.get("experience_years_claimed"),
        calculated=parsed.get("experience_years_calculated"),
    )
    parsed["experience_calculation"] = _build_experience_calculation(parsed["experience_entries"])
    parsed["experience_years_final"] = final_years
    parsed["experience_years"] = final_years
    parsed["experience_source"] = source
    return parsed


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


def _summarize_parse_discrepancies(
    *,
    llm_parsed: dict[str, Any],
    python_parsed: dict[str, Any],
) -> dict[str, Any]:
    discrepancies: dict[str, Any] = {}
    for key in ("email", "phone", "highest_degree", "candidate_location", "current_last_job"):
        llm_value = llm_parsed.get(key)
        python_value = python_parsed.get(key)
        if llm_value != python_value:
            discrepancies[key] = {"llm": llm_value, "python": python_value}

    llm_claimed = llm_parsed.get("experience_years_claimed")
    py_claimed = python_parsed.get("experience_years_claimed")
    if llm_claimed != py_claimed:
        discrepancies["experience_years_claimed"] = {"llm": llm_claimed, "python": py_claimed}

    llm_calc = llm_parsed.get("experience_years_calculated")
    py_calc = python_parsed.get("experience_years_calculated")
    if llm_calc != py_calc:
        discrepancies["experience_years_calculated"] = {"llm": llm_calc, "python": py_calc}

    llm_entries = llm_parsed.get("experience_entries", [])
    python_entries = python_parsed.get("experience_entries", [])
    if isinstance(llm_entries, list) and isinstance(python_entries, list):
        if len(llm_entries) != len(python_entries):
            discrepancies["experience_entry_count"] = {"llm": len(llm_entries), "python": len(python_entries)}
        elif llm_entries != python_entries:
            discrepancies["experience_entries"] = {"llm": llm_entries[:5], "python": python_entries[:5]}

    return discrepancies


def _normalize_llm_parse_output(parsed: dict[str, Any], resume_text: str) -> dict[str, Any]:
    parsed["email"] = parsed.get("email") if isinstance(parsed.get("email"), str) else None
    parsed["phone"] = parsed.get("phone") if isinstance(parsed.get("phone"), str) else None
    parsed["highest_degree"] = parsed.get("highest_degree") if isinstance(parsed.get("highest_degree"), str) else None
    parsed["candidate_location"] = parsed.get("candidate_location") if isinstance(parsed.get("candidate_location"), str) else None
    parsed["current_last_job"] = parsed.get("current_last_job") if isinstance(parsed.get("current_last_job"), str) else None

    skills = parsed.get("skills", [])
    if not isinstance(skills, list):
        skills = []
    parsed["skills"] = _unique_clean_strings(skills)

    experience_entries = parsed.get("experience_entries", [])
    if not isinstance(experience_entries, list):
        experience_entries = []
    parsed["experience_entries"] = [
        _normalize_experience_entry(e)
        for e in experience_entries
        if isinstance(e, dict)
    ]

    claimed = parsed.get("experience_years_claimed")
    if isinstance(claimed, (int, float)):
        parsed["experience_years_claimed"] = round(float(claimed), 1)
    else:
        parsed["experience_years_claimed"] = _extract_explicit_experience_years(resume_text)

    sponsorship_required = parsed.get("sponsorship_required")
    if isinstance(sponsorship_required, bool) or sponsorship_required is None:
        parsed["sponsorship_required"] = sponsorship_required
    else:
        parsed["sponsorship_required"] = None

    return parsed


def _normalize_experience_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": _clean_string(entry.get("title")),
        "company": _clean_string(entry.get("company")),
        "start_date": _clean_date_string(entry.get("start_date")),
        "end_date": _clean_date_string(entry.get("end_date")),
        "is_current": bool(entry.get("is_current")) if entry.get("is_current") is not None else False,
        "section": _clean_string(entry.get("section")),
        "employment_type": _clean_string(entry.get("employment_type")),
        "location": _clean_string(entry.get("location") or entry.get("candidate_location_from_role")),
    }


def _pick_final_experience_years(claimed: float | None, calculated: float | None) -> tuple[float | None, str]:
    if claimed is not None:
        return round(claimed, 1), "explicit_claim_from_summary"

    if calculated is not None:
        return round(calculated, 1), "python_from_experience_entries"

    return None, "unavailable"


def extract_experience_entries_from_blocks(text: str) -> list[dict[str, Any]]:
    blocks = extract_job_blocks(text)
    entries: list[dict[str, Any]] = []

    for block in blocks:
        entry = _parse_single_job_block(block)
        if entry:
            entries.append(entry)

    return entries


def _parse_single_job_block(block: str) -> dict[str, Any] | None:
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    if not lines:
        return None

    company = None
    title = None
    location = None
    start_date = None
    end_date = None
    is_current = False

    first_line = lines[0]

    client_match = CLIENT_LINE_PATTERN.match(first_line)
    if client_match:
        company = client_match.group("company").strip()
        location = client_match.group("location").strip()
        interval_info = _extract_normalized_dates_from_text(client_match.group("dates"))
        if interval_info:
            start_date, end_date, is_current = interval_info

        for line in lines[1:5]:
            role_match = ROLE_LINE_PATTERN.match(line)
            if role_match:
                title = role_match.group("title").strip()
                break

    # Split only on pipe first
    pipe_parts = [p.strip() for p in first_line.split("|") if p.strip()]

    if not company and len(pipe_parts) >= 3:
        company = pipe_parts[0]

        # middle part may contain title + location mixed together
        middle = pipe_parts[1]
        dates_part = pipe_parts[2]

        interval_info = _extract_normalized_dates_from_text(dates_part)
        if interval_info:
            start_date, end_date, is_current = interval_info

        # Try to split title/location heuristically
        location_match = re.search(r"([A-Za-z .]+,\s*[A-Z]{2}|[A-Za-z .]+,\s*[A-Za-z]+)$", middle)
        if location_match:
            location = location_match.group(1).strip()
            title = middle[:location_match.start()].strip()
        else:
            title = middle.strip()

    elif not company and len(pipe_parts) == 2:
        company = pipe_parts[0]
        title = pipe_parts[1]

        # Check next lines for date/location
        for line in lines[1:3]:
            interval_info = _extract_normalized_dates_from_text(line)
            if interval_info and start_date is None:
                start_date, end_date, is_current = interval_info

            if "|" in line:
                subparts = [p.strip() for p in line.split("|") if p.strip()]
                for part in subparts:
                    if _extract_normalized_dates_from_text(part):
                        continue
                    if "," in part:
                        location = part
                        break

    if (not company and not title) and len(lines) >= 2:
        # Fallback for multiline layouts:
        # Title
        # Company
        # Location | Dates  OR  Dates
        first = lines[0]
        second = lines[1]
        candidate_date_line = None
        candidate_location = None

        for line in lines[1:4]:
            if _extract_normalized_dates_from_text(line):
                candidate_date_line = line
                break

        if candidate_date_line:
            company = second
            title = first
            if "|" in candidate_date_line:
                subparts = [p.strip() for p in candidate_date_line.split("|") if p.strip()]
                for part in subparts:
                    interval_info = _extract_normalized_dates_from_text(part)
                    if interval_info and start_date is None:
                        start_date, end_date, is_current = interval_info
                        continue
                    if "," in part and candidate_location is None:
                        candidate_location = part
            else:
                interval_info = _extract_normalized_dates_from_text(candidate_date_line)
                if interval_info:
                    start_date, end_date, is_current = interval_info

            location = candidate_location

    if not company and not title:
        return None

    return {
        "title": _clean_string(title),
        "company": _clean_string(company),
        "start_date": start_date,
        "end_date": end_date,
        "is_current": is_current,
        "section": "Experience",
        "employment_type": None,
        "candidate_location_from_role": _clean_string(location),
    }

def extract_job_blocks(text: str) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    blocks: list[str] = []
    i = 0

    while i < len(lines):
        line = lines[i]

        if SECTION_EXCLUDE_HEADERS.match(line):
            break

        if CLIENT_LINE_PATTERN.match(line):
            block_lines = [line]
            j = i + 1
            while j < len(lines):
                candidate = lines[j]

                if SECTION_EXCLUDE_HEADERS.match(candidate):
                    break

                if j > i and CLIENT_LINE_PATTERN.match(candidate):
                    break

                block_lines.append(candidate)
                j += 1

            blocks.append("\n".join(block_lines))
            i = j
            continue

        # Try inline single-line role first
        if _looks_like_role_line(line) and _find_date_line_nearby(lines, i) is not None:
            block_lines = [line]
            date_idx = _find_date_line_nearby(lines, i)

            # Add the date line if it is not the same line
            if date_idx is not None and date_idx != i:
                block_lines.append(lines[date_idx])

            j = max(i, (date_idx or i)) + 1

            while j < len(lines):
                candidate = lines[j]

                if SECTION_EXCLUDE_HEADERS.match(candidate):
                    break

                if _looks_like_new_job_start_relaxed(lines, j):
                    break

                block_lines.append(candidate)
                j += 1

            blocks.append("\n".join(block_lines))
            i = j
            continue

        # Fallback multiline role layout:
        # Title
        # Company
        # Location | Dates or Dates
        if _looks_like_multiline_job_start(lines, i):
            block_lines = [lines[i], lines[i + 1]]
            j = i + 2
            while j < len(lines):
                candidate = lines[j]

                if SECTION_EXCLUDE_HEADERS.match(candidate):
                    break

                if j > i + 2 and (_looks_like_new_job_start_relaxed(lines, j) or _looks_like_multiline_job_start(lines, j)):
                    break

                block_lines.append(candidate)
                j += 1

            blocks.append("\n".join(block_lines))
            i = j
            continue

        i += 1

    return blocks


def _looks_like_role_line(line: str) -> bool:
    # More tolerant than strict regex
    if "|" not in line:
        return False

    parts = [p.strip() for p in line.split("|") if p.strip()]
    if len(parts) < 2:
        return False

    # Usually company | title
    return True


def _find_date_line_nearby(lines: list[str], idx: int) -> int | None:
    # Search current line and next 2 lines for a date range
    for j in range(idx, min(idx + 3, len(lines))):
        if _line_contains_date_range(lines[j]):
            return j
    return None


def _looks_like_new_job_start_relaxed(lines: list[str], idx: int) -> bool:
    line = lines[idx]

    if SECTION_EXCLUDE_HEADERS.match(line):
        return True

    if _looks_like_role_line(line):
        nearby_date_idx = _find_date_line_nearby(lines, idx)
        if nearby_date_idx is not None:
            return True

    if CLIENT_LINE_PATTERN.match(line):
        return True

    if _looks_like_multiline_job_start(lines, idx):
        return True

    return False


def _looks_like_multiline_job_start(lines: list[str], idx: int) -> bool:
    if idx + 2 >= len(lines):
        return False

    first = lines[idx].strip()
    second = lines[idx + 1].strip()
    third = lines[idx + 2].strip()

    if SECTION_EXCLUDE_HEADERS.match(first) or SECTION_EXCLUDE_HEADERS.match(second):
        return False
    if "|" in first:
        return False
    if len(first.split()) > 8 or len(second.split()) > 10:
        return False
    if not _line_contains_date_range(third):
        return False
    return True

def _looks_like_role_line(line: str) -> bool:
    # More tolerant than strict regex
    if "|" not in line:
        return False

    parts = [p.strip() for p in line.split("|") if p.strip()]
    if len(parts) < 2:
        return False

    # Usually company | title
    return True


def _find_date_line_nearby(lines: list[str], idx: int) -> int | None:
    # Search current line and next 2 lines for a date range
    for j in range(idx, min(idx + 3, len(lines))):
        if _line_contains_date_range(lines[j]):
            return j
    return None


def _looks_like_new_job_start_relaxed(lines: list[str], idx: int) -> bool:
    line = lines[idx]

    if SECTION_EXCLUDE_HEADERS.match(line):
        return True

    if _looks_like_role_line(line):
        nearby_date_idx = _find_date_line_nearby(lines, idx)
        if nearby_date_idx is not None:
            return True

    return False

def _looks_like_new_job_start(lines: list[str], idx: int) -> bool:
    line = lines[idx]

    if INLINE_JOB_PATTERN.match(line):
        return True

    if JOB_HEADER_PATTERN.match(line) and idx + 1 < len(lines):
        next_line = lines[idx + 1]
        m = DATE_LOCATION_LINE_PATTERN.match(next_line)
        if m and _line_contains_date_range(m.group("dates")):
            return True

    return False


def _extract_normalized_dates_from_text(text: str) -> tuple[str | None, str | None, bool] | None:
    text = text.strip()

    for pattern in DATE_RANGE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue

        gd = match.groupdict()

        if gd.get("sy") and gd.get("sm"):
            s_year = int(gd["sy"])
            s_month = int(gd["sm"])
            if not (1 <= s_month <= 12):
                continue
            start = f"{s_year:04d}-{s_month:02d}"

            if (gd.get("ep") or "").lower() in PRESENT_WORDS:
                return start, None, True

            if gd.get("ey") and gd.get("em"):
                e_year = int(gd["ey"])
                e_month = int(gd["em"])
                if not (1 <= e_month <= 12):
                    continue
                end = f"{e_year:04d}-{e_month:02d}"
                return start, end, False

        if gd.get("smon") and gd.get("syr"):
            s_month = MONTH_MAP.get(gd["smon"].lower())
            s_year = int(gd["syr"])
            if not s_month:
                continue

            start = f"{s_year:04d}-{s_month:02d}"
            e_raw = (gd.get("emon") or "").lower()

            if e_raw in PRESENT_WORDS:
                return start, None, True

            e_month = MONTH_MAP.get(e_raw)
            e_year = int(gd["eyr"]) if gd.get("eyr") else s_year
            if e_month:
                end = f"{e_year:04d}-{e_month:02d}"
                return start, end, False

        if gd.get("smo") and gd.get("syr"):
            s_month = int(gd["smo"])
            s_year = int(gd["syr"])
            if not (1 <= s_month <= 12):
                continue

            start = f"{s_year:04d}-{s_month:02d}"
            e_raw = (gd.get("emo") or "").lower()

            if e_raw in PRESENT_WORDS:
                return start, None, True

            if e_raw.isdigit():
                e_month = int(e_raw)
                if not (1 <= e_month <= 12):
                    continue
                e_year = int(gd["eyr"]) if gd.get("eyr") else s_year
                end = f"{e_year:04d}-{e_month:02d}"
                return start, end, False

        if gd.get("syr") and gd.get("eyr") and not gd.get("smon") and not gd.get("smo"):
            s_year = int(gd["syr"])
            e_raw = gd["eyr"].lower()

            start = f"{s_year:04d}"
            if e_raw in PRESENT_WORDS:
                return start, None, True

            if e_raw.isdigit():
                end = f"{int(e_raw):04d}"
                return start, end, False

    return None


def _calculate_experience_years_from_entries(entries: list[dict[str, Any]]) -> float | None:
    intervals: list[DateInterval] = []

    for entry in entries:
        if _should_exclude_experience_entry(entry):
            logger.info("[EXP_CALC] Excluding entry: %s", entry)
            continue

        interval = _entry_to_interval(entry)
        if interval:
            intervals.append(interval)
            logger.info(
                "[EXP_CALC] Counted entry company=%s title=%s start=%s end=%s",
                entry.get("company"),
                entry.get("title"),
                entry.get("start_date"),
                entry.get("end_date") if entry.get("end_date") else "PRESENT",
            )
        else:
            logger.info("[EXP_CALC] Could not parse dates for entry: %s", entry)

    if not intervals:
        logger.info("[EXP_CALC] No valid intervals found")
        return None

    merged = _merge_intervals(intervals)
    total_months = sum(_months_inclusive(iv.start, iv.end) for iv in merged)
    years = round(total_months / 12.0, 1)

    logger.info("[EXP_CALC] merged_intervals=%s total_months=%s years=%s", merged, total_months, years)
    return years


def _build_experience_calculation(entries: list[dict[str, Any]]) -> dict[str, Any]:
    role_rows: list[dict[str, Any]] = []
    counted_intervals: list[DateInterval] = []

    for entry in entries:
        excluded = _should_exclude_experience_entry(entry)
        interval = None if excluded else _entry_to_interval(entry)
        months = _months_inclusive(interval.start, interval.end) if interval else None
        status = "counted" if interval else "excluded" if excluded else "missing_dates"
        reason = None
        if excluded:
            reason = "excluded_non_professional_entry"
        elif interval is None:
            reason = "missing_or_invalid_dates"

        if interval:
            counted_intervals.append(interval)

        role_rows.append(
            {
                "company": entry.get("company"),
                "title": entry.get("title"),
                "location": entry.get("location") or entry.get("candidate_location_from_role"),
                "start_date": entry.get("start_date"),
                "end_date": entry.get("end_date"),
                "is_current": bool(entry.get("is_current")),
                "status": status,
                "months_counted": months,
                "reason": reason,
            }
        )

    merged = _merge_intervals(counted_intervals) if counted_intervals else []
    merged_rows = [
        {
            "start_date": iv.start.isoformat(),
            "end_date": iv.end.isoformat(),
            "months": _months_inclusive(iv.start, iv.end),
        }
        for iv in merged
    ]
    total_months = sum(item["months"] for item in merged_rows)
    total_years = round(total_months / 12.0, 1) if total_months else None

    return {
        "roles": role_rows,
        "merged_intervals": merged_rows,
        "total_months": total_months,
        "total_years": total_years,
    }


def _calculate_experience_years_from_raw_text(text: str) -> float | None:
    intervals: list[DateInterval] = []

    for block in extract_job_blocks(text):
        interval = _extract_date_interval_from_block(block)
        if interval:
            intervals.append(interval)

    if not intervals:
        for line in text.splitlines():
            interval = _extract_date_interval_from_line(line)
            if interval:
                intervals.append(interval)

    if not intervals:
        return None

    merged = _merge_intervals(intervals)
    total_months = sum(_months_inclusive(iv.start, iv.end) for iv in merged)
    return round(total_months / 12.0, 1)


def _should_exclude_experience_entry(entry: dict[str, Any]) -> bool:
    text = " ".join(
        x for x in [
            entry.get("title"),
            entry.get("company"),
            entry.get("employment_type"),
            entry.get("section"),
        ]
        if isinstance(x, str)
    ).lower()

    if any(re.search(rf"\b{re.escape(keyword)}\b", text) for keyword in DEGREE_KEYWORDS):
        return True

    # Keep internships by default.
    # To exclude them, uncomment below:
    # if "intern" in text:
    #     return True

    if "volunteer" in text:
        return True
    if "teaching assistant" in text or "research assistant" in text or "graduate assistant" in text:
        return True

    return False


def _entry_to_interval(entry: dict[str, Any]) -> DateInterval | None:
    start = _parse_normalized_date(entry.get("start_date"), is_end=False)
    end = _parse_normalized_date(entry.get("end_date"), is_end=True)

    if entry.get("is_current"):
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

    if re.fullmatch(r"\d{4}-\d{2}", value):
        year, month = map(int, value.split("-"))
        if month < 1 or month > 12:
            return None
        if is_end:
            last_day = calendar.monthrange(year, month)[1]
            return date(year, month, last_day)
        return date(year, month, 1)

    if re.fullmatch(r"\d{4}", value):
        year = int(value)
        if is_end:
            return date(year, 12, 31)
        return date(year, 1, 1)

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


def _extract_explicit_experience_years(text: str) -> float | None:
    values: list[float] = []
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines[:60]:
        lowered = line.lower()
        matches = list(EXPLICIT_EXPERIENCE_PATTERN.finditer(line))
        if not matches and any(noise in lowered for noise in EXPLICIT_NOISE_WORDS):
            continue
        for match in matches:
            years_str = match.group("years")
            try:
                values.append(float(years_str))
            except ValueError:
                continue

    if not values:
        return None

    return round(max(values), 1)


def _extract_work_excerpt(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return text[:3000]

    start_idx = None
    end_idx = None

    # Find a real section header line
    for idx, line in enumerate(lines):
        if WORK_START_PATTERN.match(line):
            start_idx = idx + 1
            break

    if start_idx is None:
        # fallback: try to find an all-caps EXPERIENCE header
        for idx, line in enumerate(lines):
            normalized = re.sub(r"\s+", " ", line).strip().lower()
            if normalized in {
                "experience",
                "work experience",
                "professional experience",
                "employment history",
            }:
                start_idx = idx + 1
                break

    if start_idx is None:
        logger.warning("[LLM_PARSE] Could not find experience section header")
        return "\n".join(lines[:150])

    for idx in range(start_idx, len(lines)):
        if WORK_END_PATTERN.match(lines[idx]):
            end_idx = idx
            break

    if end_idx is None:
        end_idx = len(lines)

    excerpt = "\n".join(lines[start_idx:end_idx]).strip()
    if excerpt:
        return excerpt

    print("==== EXTRACT_WORK_EXCERPT START IDX ====", start_idx)
    print("==== EXTRACT_WORK_EXCERPT END IDX ====", end_idx)
    return "\n".join(lines[start_idx:start_idx + 150])


def _extract_header_excerpt(text: str, max_lines: int = 35) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    return "\n".join(lines[:max_lines])

def _line_contains_date_range(text: str) -> bool:
    return _extract_date_interval_from_line(text) is not None


def _extract_date_interval_from_block(block: str) -> DateInterval | None:
    for line in block.splitlines():
        interval = _extract_date_interval_from_line(line)
        if interval:
            return interval
    return None


def _extract_date_interval_from_line(line: str) -> DateInterval | None:
    today = date.today()

    for pattern in DATE_RANGE_PATTERNS:
        match = pattern.search(line)
        if not match:
            continue

        gd = match.groupdict()

        if gd.get("smon") and gd.get("syr"):
            s_month = MONTH_MAP.get(gd["smon"].lower())
            s_year = int(gd["syr"])
            if not s_month:
                continue

            e_raw = (gd.get("emon") or "").lower()
            if e_raw in PRESENT_WORDS:
                return DateInterval(date(s_year, s_month, 1), today)

            e_month = MONTH_MAP.get(e_raw)
            e_year = int(gd["eyr"]) if gd.get("eyr") else s_year
            if e_month:
                last_day = calendar.monthrange(e_year, e_month)[1]
                return DateInterval(date(s_year, s_month, 1), date(e_year, e_month, last_day))

        if gd.get("smo") and gd.get("syr"):
            s_month = int(gd["smo"])
            s_year = int(gd["syr"])
            if not (1 <= s_month <= 12):
                continue

            e_raw = (gd.get("emo") or "").lower()
            if e_raw in PRESENT_WORDS:
                return DateInterval(date(s_year, s_month, 1), today)

            if e_raw.isdigit():
                e_month = int(e_raw)
                if not (1 <= e_month <= 12):
                    continue
                e_year = int(gd["eyr"]) if gd.get("eyr") else s_year
                last_day = calendar.monthrange(e_year, e_month)[1]
                return DateInterval(date(s_year, s_month, 1), date(e_year, e_month, last_day))

        if gd.get("syr") and gd.get("eyr") and not gd.get("smon") and not gd.get("smo"):
            s_year = int(gd["syr"])
            e_raw = gd["eyr"].lower()
            if e_raw in PRESENT_WORDS:
                return DateInterval(date(s_year, 1, 1), today)
            if e_raw.isdigit():
                e_year = int(e_raw)
                return DateInterval(date(s_year, 1, 1), date(e_year, 12, 31))

    return None


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


def _clean_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = re.sub(r"\s+", " ", value).strip()
    return value or None


def _clean_date_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None

    value = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}", value):
        return value
    if re.fullmatch(r"\d{4}", value):
        return value
    return None
