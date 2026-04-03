from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
import psycopg
import redis
from docx import Document
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.llm_parse import (
    calculate_experience_years_from_entries,
    count_date_ranges_in_text,
    derive_primary_domain,
    derive_seniority_level,
    estimate_experience_years_from_text,
    normalize_resume_text,
    parse_resume_with_ft_v2,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

DATABASE_URL = os.getenv("DATABASE_URL", "")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
INGESTION_QUEUE_KEY = os.getenv("INGESTION_QUEUE_KEY", "resume_ingestion_queue")

ENABLE_LLM_PARSE = os.getenv("ENABLE_LLM_PARSE", "true").lower() == "true"
USE_DOCLING_PARSER = os.getenv("USE_DOCLING_PARSER", "true").lower() == "true"

EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_PATTERN = re.compile(
    r"(?:(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}(?:x\d+)?)"
)

LOCATION_LINE_LABELS = {"location", "address", "city"}
SUMMARY_HEADERS = {
    "summary",
    "professional summary",
    "profile",
    "about me",
    "about",
    "career summary",
    "executive summary",
}

STRICT_EMPTY_OUTPUT = {
    "full_name": None,
    "email": None,
    "phone": None,
    "candidate_location": None,
    "willing_to_relocate": None,
    "linkedin_url": None,
    "github_url": None,
    "portfolio_url": None,
    "professional_summary": None,
    "skills": [],
    "languages": [],
    "highest_degree": None,
    "education": [],
    "current_last_job": None,
    "experience_entries": [],
    "projects": [],
    "certifications": [],
    "awards": [],
    "volunteering": [],
    "publications": [],
}


def get_db_connection():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set")
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


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
        parts: list[str] = []
        for element in elements:
            value = getattr(element, "text", None)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
        combined = "\n".join(parts).strip()
        return combined if combined else None
    except Exception:
        logger.exception("unstructured extraction failed for %s", path)
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
        logger.exception("docling extraction failed for %s", path)
        return None

    return None


def _parse_text_from_file_legacy(path: Path) -> str:
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        doc = fitz.open(path)
        try:
            text = "\n".join(page.get_text("text") for page in doc)
        finally:
            doc.close()

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
    if USE_DOCLING_PARSER and path.suffix.lower() in {".pdf", ".docx"}:
        docling_text = _extract_with_docling(path)
        if isinstance(docling_text, str) and docling_text.strip() and not _text_looks_weak(docling_text):
            return docling_text

    return _parse_text_from_file_legacy(path)


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
        if not has_contact_nearby:
            continue
        if 2 <= len(line.split()) <= 5 and re.fullmatch(r"[A-Za-z .'-]+", line):
            return line

    return None


def _extract_professional_summary(text: str) -> str | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for i, line in enumerate(lines[:40]):
        if line.lower() in SUMMARY_HEADERS:
            summary_lines: list[str] = []
            for candidate in lines[i + 1 : i + 6]:
                lower = candidate.lower()
                if lower in SUMMARY_HEADERS:
                    break
                if len(candidate.split()) <= 2 and candidate.isupper():
                    break
                if candidate.endswith(":"):
                    break
                summary_lines.append(candidate)
            if summary_lines:
                return " ".join(summary_lines).strip()

    for line in lines[:12]:
        if 8 <= len(line.split()) <= 40 and any(word in line.lower() for word in ("years", "experience", "specialist", "engineer", "developer", "architect")):
            return line.strip()

    return None


def _extract_candidate_location_from_top(lines: list[str], email: str | None, phone: str | None) -> str | None:
    header_window = lines[:12]

    for line in header_window:
        lowered = line.lower()

        if email and email in line:
            possible = line.replace(email, " ")
            if phone:
                possible = possible.replace(phone, " ")
            parts = [p.strip(" ·|-") for p in re.split(r"[·|]", possible) if p.strip(" ·|-")]
            for part in parts:
                if "," in part and "@" not in part and not re.search(r"\d{3}", part):
                    return part.strip()

        if any(label in lowered for label in LOCATION_LINE_LABELS):
            value = re.sub(r"^(location|address|city)\s*:\s*", "", line, flags=re.IGNORECASE).strip()
            if value:
                return value

    for line in header_window:
        if "," in line and "@" not in line and not re.search(r"\d{3}", line):
            return line.strip(" ·|-")

    return None


def extract_resume_features_fallback(text: str) -> dict[str, Any]:
    """
    Minimal strict fallback when the v2 model call fails.
    Intentionally conservative.
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    emails = EMAIL_PATTERN.findall(text)
    phones = PHONE_PATTERN.findall(text)

    parsed = dict(STRICT_EMPTY_OUTPUT)
    parsed["full_name"] = _extract_probable_full_name(text)
    parsed["email"] = emails[0] if emails else None
    parsed["phone"] = phones[0] if phones else None
    parsed["candidate_location"] = _extract_candidate_location_from_top(
        lines,
        email=emails[0] if emails else None,
        phone=phones[0] if phones else None,
    )
    parsed["professional_summary"] = _extract_professional_summary(text)

    return parsed


def build_final_payload(strict_parsed: dict[str, Any], normalized_text: str) -> dict[str, Any]:
    final_payload = dict(strict_parsed)

    parsed_experience_years = calculate_experience_years_from_entries(
        strict_parsed.get("experience_entries", [])
    )
    final_payload["experience_years"] = parsed_experience_years

    # Always compute timeline-based experience from raw work-history text and
    # keep the stronger value when LLM/structured output is incomplete.
    fallback_experience_years = estimate_experience_years_from_text(normalized_text)
    if fallback_experience_years is not None:
        if parsed_experience_years is None:
            final_payload["experience_years"] = fallback_experience_years
        elif (
            fallback_experience_years > parsed_experience_years
            and count_date_ranges_in_text(normalized_text) >= 2
        ):
            final_payload["experience_years"] = fallback_experience_years

    final_payload["primary_domain"] = derive_primary_domain(
        strict_parsed.get("current_last_job"),
        strict_parsed.get("experience_entries", []),
        strict_parsed.get("skills", []),
    )
    final_payload["seniority_level"] = derive_seniority_level(
        strict_parsed.get("current_last_job")
    )

    return final_payload


def _get_resume_columns(conn: psycopg.Connection) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'resumes'
            """
        )
        rows = cur.fetchall()
    return {row["column_name"] for row in rows}


def _get_candidate_columns(conn: psycopg.Connection) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'candidates'
            """
        )
        rows = cur.fetchall()
    return {row["column_name"] for row in rows}


def persist_parsed_resume(resume_id: str, raw_text: str, payload: dict[str, Any]) -> None:
    """
    Writes to your real schema:
    - resumes.raw_text
    - resumes.parsed_json
    - resumes.parse_status
    - resumes.parse_error

    Also writes skills_json / experience_years if those columns exist.
    """
    with get_db_connection() as conn:
        resume_columns = _get_resume_columns(conn)

        set_parts = [
            "raw_text = %(raw_text)s",
            "parsed_json = %(parsed_json)s",
            "parse_status = 'parsed'",
            "parse_error = NULL",
        ]

        params: dict[str, Any] = {
            "resume_id": resume_id,
            "raw_text": raw_text,
            "parsed_json": Jsonb(payload),
        }

        if "skills_json" in resume_columns:
            set_parts.append("skills_json = %(skills_json)s")
            params["skills_json"] = Jsonb(payload.get("skills", []))

        if "experience_years" in resume_columns:
            set_parts.append("experience_years = %(experience_years)s")
            params["experience_years"] = payload.get("experience_years")

        update_sql = f"""
            UPDATE resumes
            SET {", ".join(set_parts)}
            WHERE id = %(resume_id)s::uuid
        """

        with conn.cursor() as cur:
            cur.execute(update_sql, params)

            cur.execute(
                """
                SELECT candidate_id
                FROM resumes
                WHERE id = %s::uuid
                """,
                (resume_id,),
            )
            row = cur.fetchone()
            candidate_id = row["candidate_id"] if row and row.get("candidate_id") else None

            if candidate_id:
                candidate_columns = _get_candidate_columns(conn)

                assignments = []
                candidate_params: dict[str, Any] = {"candidate_id": candidate_id}

                if "full_name" in candidate_columns:
                    assignments.append("full_name = COALESCE(full_name, %(full_name)s)")
                    candidate_params["full_name"] = payload.get("full_name")

                if "phone" in candidate_columns:
                    assignments.append("phone = COALESCE(phone, %(phone)s)")
                    candidate_params["phone"] = payload.get("phone")

                if "location" in candidate_columns:
                    assignments.append("location = COALESCE(location, %(location)s)")
                    candidate_params["location"] = payload.get("candidate_location")

                if "linkedin_url" in candidate_columns:
                    assignments.append("linkedin_url = COALESCE(linkedin_url, %(linkedin_url)s)")
                    candidate_params["linkedin_url"] = payload.get("linkedin_url")

                if assignments:
                    candidate_sql = f"""
                        UPDATE candidates
                        SET {", ".join(assignments)}
                        WHERE id = %(candidate_id)s::uuid
                    """
                    cur.execute(candidate_sql, candidate_params)

        conn.commit()


def mark_resume_failed(resume_id: str, error_message: str) -> None:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE resumes
                SET parse_status = 'failed',
                    parse_error = %s
                WHERE id = %s::uuid
                """,
                (error_message[:2000], resume_id),
            )
        conn.commit()


def process_resume_text(text: str) -> dict[str, Any]:
    normalized_text = normalize_resume_text(text)

    strict_parsed: dict[str, Any] | None = None
    if ENABLE_LLM_PARSE:
        strict_parsed = parse_resume_with_ft_v2(normalized_text)

    if strict_parsed is None:
        logger.warning("V2 model parse failed; using strict fallback")
        strict_parsed = extract_resume_features_fallback(normalized_text)

    return build_final_payload(strict_parsed, normalized_text)


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

            if not resume_id or not file_url:
                raise ValueError("Payload must include resume_id and file_url")

            resolved_path = resolve_file_path(file_url)
            text = parse_text_from_file(resolved_path)
            if not text.strip():
                raise ValueError("No extractable text found in resume")

            final_payload = process_resume_text(text)

            print("==== FINAL PARSED BEFORE SAVE ====")
            print(json.dumps(final_payload, indent=2, ensure_ascii=False, default=str))

            persist_parsed_resume(str(resume_id), normalize_resume_text(text), final_payload)
            time.sleep(0.2)
            print(f"[DONE] resume={resume_id}")

        except json.JSONDecodeError:
            print(f"[ERROR] invalid payload: {payload}")
        except Exception as exc:
            failed_resume_id = None
            try:
                decoded = json.loads(payload)
                failed_resume_id = decoded.get("resume_id")
            except Exception:
                pass

            print(f"[ERROR] ingestion failed for resume={failed_resume_id}: {exc}")
            logger.exception("ingestion failed")
            if failed_resume_id:
                mark_resume_failed(str(failed_resume_id), str(exc))


if __name__ == "__main__":
    run_ingestion_worker()
