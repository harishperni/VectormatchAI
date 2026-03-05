from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz
import psycopg
import redis
from docx import Document
from psycopg.types.json import Json

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
INGESTION_QUEUE_KEY = os.getenv("INGESTION_QUEUE_KEY", "resume_ingestion_queue")
WORKER_DATABASE_URL = os.getenv("WORKER_DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ats")

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
]

EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_PATTERN = re.compile(r"(?:\+?\d[\d\s().-]{8,}\d)")
YEARS_PATTERN = re.compile(r"(\d{1,2})(?:\+)?\s+years?", re.IGNORECASE)
NO_SPONSOR_PATTERN = re.compile(r"(no\s+sponsorship|without\s+sponsorship)", re.IGNORECASE)
YES_SPONSOR_PATTERN = re.compile(r"(require[s]?\s+sponsorship|visa\s+sponsorship)", re.IGNORECASE)
LOCATION_LINE_PATTERN = re.compile(
    r"\b([A-Za-z .'-]+,\s*(?:[A-Z]{2}|[A-Za-z]+)(?:,\s*(?:USA|US|United States))?)\b"
)
MONTH_YEAR_RANGE_PATTERN = re.compile(
    r"\b(Jan|January|Feb|February|Mar|March|Apr|April|May|Jun|June|Jul|July|Aug|August|Sep|Sept|September|Oct|October|Nov|November|Dec|December)\s+(\d{4})\s*[-–]\s*(Present|Current|Now|"
    r"Jan|January|Feb|February|Mar|March|Apr|April|May|Jun|June|Jul|July|Aug|August|Sep|Sept|September|Oct|October|Nov|November|Dec|December)\s*(\d{4})?",
    re.IGNORECASE,
)
YEAR_RANGE_PATTERN = re.compile(r"\b(19\d{2}|20\d{2})\s*[-–]\s*(Present|Current|Now|19\d{2}|20\d{2})\b", re.IGNORECASE)
SECTION_HEADER_PATTERN = re.compile(r"^\s*(work experience|professional experience|experience|education)\s*:?\s*$", re.IGNORECASE)

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


def _month_index(year: int, month: int) -> int:
    return (year * 12) + month


def _parse_end_year(value: str) -> int:
    if value.lower() in {"present", "current", "now"}:
        return datetime.utcnow().year
    return int(value)


def _extract_experience_years(text: str) -> tuple[float | None, str]:
    explicit = [int(value) for value in YEARS_PATTERN.findall(text)]
    explicit_years = max(explicit) if explicit else None

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

    total_months = 0
    for match in MONTH_YEAR_RANGE_PATTERN.findall(source_text):
        start_month_txt, start_year_txt, end_month_or_word, end_year_txt = match
        start_month = MONTH_MAP.get(start_month_txt.lower())
        if not start_month:
            continue
        start_year = int(start_year_txt)

        if end_month_or_word.lower() in {"present", "current", "now"}:
            end_month = datetime.utcnow().month
            end_year = datetime.utcnow().year
        else:
            end_month = MONTH_MAP.get(end_month_or_word.lower())
            if not end_month:
                continue
            end_year = int(end_year_txt) if end_year_txt else datetime.utcnow().year

        start_idx = _month_index(start_year, start_month)
        end_idx = _month_index(end_year, end_month)
        if end_idx >= start_idx:
            total_months += (end_idx - start_idx) + 1

    for match in YEAR_RANGE_PATTERN.findall(source_text):
        start_year_txt, end_year_txt = match
        start_year = int(start_year_txt)
        end_year = _parse_end_year(end_year_txt)
        start_idx = _month_index(start_year, 1)
        end_idx = _month_index(end_year, 12)
        if end_idx >= start_idx:
            total_months += (end_idx - start_idx) + 1

    inferred_years = round(total_months / 12.0, 1) if total_months > 0 else None
    if explicit_years is not None:
        # Prefer explicit self-reported years when present.
        return float(explicit_years), "explicit_preferred"
    if inferred_years is not None:
        return float(inferred_years), "inferred_from_dates"
    return None, "not_found"


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


def parse_text_from_file(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        doc = fitz.open(path)
        return "\n".join(page.get_text("text") for page in doc)

    if suffix == ".docx":
        doc = Document(path)
        lines = [para.text.strip() for para in doc.paragraphs if para.text.strip()]
        return "\n".join(lines)

    return path.read_text(encoding="utf-8", errors="ignore")


def extract_resume_features(text: str) -> dict[str, Any]:
    text_lower = text.lower()
    skills = [skill for skill in SKILL_KEYWORDS if skill in text_lower]
    emails = EMAIL_PATTERN.findall(text)
    phones = PHONE_PATTERN.findall(text)
    experience_years, experience_source = _extract_experience_years(text)

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    candidate_location = None
    for line in lines[:80]:
        match = LOCATION_LINE_PATTERN.search(line)
        if match:
            candidate_location = match.group(1)
            break

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
        "email": emails[0] if emails else None,
        "phone": phones[0] if phones else None,
        "skills": sorted(set(skills)),
        "experience_years": experience_years,
        "experience_source": experience_source,
        "highest_degree": highest_degree,
        "sponsorship_required": sponsorship_required,
        "distance_miles": None,
        "candidate_location": candidate_location,
        "current_last_job": None,
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
                            "email": parsed["email"],
                            "phone": parsed["phone"],
                            "skills": parsed["skills"],
                            "experience_years": parsed["experience_years"],
                            "experience_source": parsed["experience_source"],
                            "highest_degree": parsed["highest_degree"],
                            "sponsorship_required": parsed["sponsorship_required"],
                            "distance_miles": parsed["distance_miles"],
                            "candidate_location": parsed["candidate_location"],
                            "current_last_job": parsed["current_last_job"],
                        }
                    ),
                    Json(parsed["skills"]),
                    parsed["experience_years"],
                    resume_id,
                ),
            )

            if parsed["email"]:
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

            safe_email = None if existing_owner else parsed["email"]

            cur.execute(
                """
                UPDATE candidates
                SET primary_email = COALESCE(primary_email, %s),
                    phone = COALESCE(phone, %s),
                    location = COALESCE(location, %s)
                WHERE id = %s::uuid
                """,
                (safe_email, parsed["phone"], parsed["candidate_location"], candidate_id),
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

            parsed = extract_resume_features(text)
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
