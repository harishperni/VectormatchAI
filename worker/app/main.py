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
    _normalize_llm_parse_output_v2,
    _extract_certifications_from_text,
    _extract_education_from_text,
    _extract_environment_skills_from_text,
    _extract_experience_entries_from_text,
    _extract_full_name_from_top,
    _extract_professional_summary_from_text,
    _extract_skills_from_text,
    _extract_volunteering_from_text,
    _has_certification_section,
    _looks_like_bad_candidate_location,
    _looks_like_role_title,
    calculate_experience_years_from_entries,
    canonicalize_skill_tokens_with_unknowns,
    count_date_ranges_in_text,
    derive_highest_degree,
    derive_current_last_job,
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
    dsn = DATABASE_URL.strip()
    if dsn.startswith("postgresql+psycopg://"):
        dsn = dsn.replace("postgresql+psycopg://", "postgresql://", 1)
    return psycopg.connect(dsn, row_factory=dict_row)


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
    parsed["experience_entries"] = _extract_experience_entries_from_text(text)
    parsed["current_last_job"] = derive_current_last_job(parsed["experience_entries"])

    extracted_skills = _extract_skills_from_text(text, parsed["experience_entries"])
    env_skills = _extract_environment_skills_from_text(text)
    parsed["skills"] = list(dict.fromkeys([*extracted_skills, *env_skills]))

    parsed["certifications"] = _extract_certifications_from_text(text)
    parsed["volunteering"] = _extract_volunteering_from_text(text)
    parsed["professional_summary"] = _extract_professional_summary_from_text(text) or _extract_professional_summary(text)

    lowered = text.lower()
    if any(term in lowered for term in {"phd", "ph.d", "doctorate"}):
        parsed["highest_degree"] = "Doctorate"
    elif any(term in lowered for term in {"master", "m.s.", "ms", "m.sc", "mba", "m.tech"}):
        parsed["highest_degree"] = "Master"
    elif any(term in lowered for term in {"bachelor", "b.s.", "bs", "b.sc", "b.tech", "ba"}):
        parsed["highest_degree"] = "Bachelor"
    elif any(term in lowered for term in {"associate", "diploma"}):
        parsed["highest_degree"] = "Associate"

    return parsed


def _has_resume_section(text: str, names: tuple[str, ...]) -> bool:
    pattern = r"(?im)^\s*(?:%s)\s*:?\s*$" % "|".join(re.escape(item) for item in names)
    return bool(re.search(pattern, text))


def _needs_parse_recovery(parsed: dict[str, Any], normalized_text: str) -> bool:
    skills = parsed.get("skills", [])
    entries = parsed.get("experience_entries", [])
    has_skills = isinstance(skills, list) and len(skills) > 0
    has_entries = isinstance(entries, list) and len(entries) > 0

    if _has_resume_section(normalized_text, ("skills", "technical skills", "tools", "toolkit")) and not has_skills:
        return True
    if _has_resume_section(normalized_text, ("work experience", "professional experience", "experience")) and not has_entries:
        return True
    return False


def _merge_with_recovery(primary: dict[str, Any], recovered: dict[str, Any]) -> dict[str, Any]:
    merged = dict(primary)
    for key in (
        "skills",
        "experience_entries",
        "certifications",
        "volunteering",
        "projects",
        "education",
        "languages",
        "awards",
        "publications",
    ):
        primary_value = merged.get(key)
        if isinstance(primary_value, list) and primary_value:
            continue
        recovered_value = recovered.get(key)
        if isinstance(recovered_value, list) and recovered_value:
            merged[key] = recovered_value

    for key in (
        "professional_summary",
        "current_last_job",
        "highest_degree",
        "candidate_location",
        "email",
        "phone",
        "full_name",
    ):
        primary_value = merged.get(key)
        if isinstance(primary_value, str) and primary_value.strip():
            continue
        recovered_value = recovered.get(key)
        if isinstance(recovered_value, str) and recovered_value.strip():
            merged[key] = recovered_value

    return merged


def _parse_quality_score(parsed: dict[str, Any], normalized_text: str) -> float:
    score = 0.0

    if _clean_str(parsed.get("email")):
        score += 3.0
    if _clean_str(parsed.get("phone")):
        score += 2.0
    if _clean_str(parsed.get("full_name")):
        score += 2.0
    if _clean_str(parsed.get("professional_summary")):
        score += 1.0

    skills = parsed.get("skills", [])
    if isinstance(skills, list):
        score += min(len([s for s in skills if isinstance(s, str) and s.strip()]), 30) * 0.4

    entries = parsed.get("experience_entries", [])
    if isinstance(entries, list):
        score += min(len(entries), 15) * 1.0
        for entry in entries[:15]:
            if not isinstance(entry, dict):
                continue
            if _clean_str(entry.get("title")):
                score += 0.8
            if _clean_str(entry.get("company")):
                score += 0.8
            if _clean_str(entry.get("description")):
                score += 0.4

    current_job = _clean_str(parsed.get("current_last_job")) or ""
    if re.search(r"(?i)\b(pmp\s*expiration|certification|pmp number)\b", current_job):
        score -= 3.0
    if re.match(r"(?i)^\s*(technology|technologies|responsibilities|project description)\s*:", current_job):
        score -= 2.0

    if _has_resume_section(normalized_text, ("skills", "technical skills", "tools", "toolkit")):
        if not isinstance(skills, list) or len(skills) < 3:
            score -= 4.0
    if _has_resume_section(normalized_text, ("work experience", "professional experience", "experience")):
        if not isinstance(entries, list) or len(entries) < 2:
            score -= 4.0

    return score


def _clean_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _choose_best_parse_with_source(
    primary: dict[str, Any],
    recovered: dict[str, Any],
    normalized_text: str,
) -> tuple[str, dict[str, Any]]:
    merged = _merge_with_recovery(primary, recovered)
    candidates = [
        ("primary", primary, _parse_quality_score(primary, normalized_text)),
        ("merged", merged, _parse_quality_score(merged, normalized_text)),
        ("recovered", recovered, _parse_quality_score(recovered, normalized_text)),
    ]
    best_name, best_payload, best_score = max(candidates, key=lambda item: item[2])
    logger.info(
        "parse quality comparison primary=%.2f merged=%.2f recovered=%.2f selected=%s(%.2f)",
        candidates[0][2],
        candidates[1][2],
        candidates[2][2],
        best_name,
        best_score,
    )
    return best_name, best_payload


def _choose_best_parse(primary: dict[str, Any], recovered: dict[str, Any], normalized_text: str) -> dict[str, Any]:
    _, best_payload = _choose_best_parse_with_source(primary, recovered, normalized_text)
    return best_payload


def build_final_payload(strict_parsed: dict[str, Any], normalized_text: str) -> dict[str, Any]:
    if not isinstance(strict_parsed, dict):
        strict_parsed = {}
    # Always normalize before final enrichment so fallback/merge artifacts
    # do not override parser repairs (name/location/company/skills cleanup).
    final_payload = _normalize_llm_parse_output_v2(strict_parsed, normalized_text)

    if _looks_like_role_title(final_payload.get("full_name")):
        final_payload["full_name"] = _extract_full_name_from_top(normalized_text)

    if _looks_like_bad_candidate_location(final_payload.get("candidate_location")):
        final_payload["candidate_location"] = None
    if final_payload.get("candidate_location") is None:
        for entry in final_payload.get("experience_entries", []):
            if not isinstance(entry, dict):
                continue
            location = entry.get("location")
            if isinstance(location, str) and not _looks_like_bad_candidate_location(location):
                final_payload["candidate_location"] = location.strip()
                break
    else:
        # Prefer the current role's location when available and plausible.
        current_location = None
        for entry in final_payload.get("experience_entries", []):
            if not isinstance(entry, dict) or entry.get("is_current") is not True:
                continue
            location = entry.get("location")
            if isinstance(location, str) and not _looks_like_bad_candidate_location(location):
                current_location = location.strip()
                break
        if current_location and current_location != str(final_payload.get("candidate_location")):
            final_payload["candidate_location"] = current_location

    education = final_payload.get("education")
    if not isinstance(education, list) or not education:
        extracted_education = _extract_education_from_text(normalized_text)
        if extracted_education:
            final_payload["education"] = extracted_education
    if final_payload.get("education"):
        final_payload["highest_degree"] = derive_highest_degree(final_payload["education"])

    if _has_certification_section(normalized_text):
        extracted_certifications = _extract_certifications_from_text(normalized_text)
        existing_cert_names = {
            str(item.get("name") or "").strip().lower()
            for item in final_payload.get("certifications", [])
            if isinstance(item, dict)
        }
        for item in extracted_certifications:
            if not isinstance(item, dict):
                continue
            cert_name = str(item.get("name") or "").strip().lower()
            if cert_name and cert_name not in existing_cert_names:
                final_payload.setdefault("certifications", []).append(item)
                existing_cert_names.add(cert_name)

    raw_skills = final_payload.get("skills_raw")
    if not isinstance(raw_skills, list) or not raw_skills:
        raw_skills = final_payload.get("skills", []) if isinstance(final_payload.get("skills"), list) else []
    final_payload["skills_raw"] = [str(item) for item in raw_skills if isinstance(item, str)]
    canonical_skills, unknown_skills = canonicalize_skill_tokens_with_unknowns(final_payload["skills_raw"])
    final_payload["skills"] = canonical_skills
    final_payload["skills_unknown_tokens"] = unknown_skills

    parsed_experience_years = calculate_experience_years_from_entries(
        final_payload.get("experience_entries", [])
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
        final_payload.get("current_last_job"),
        final_payload.get("experience_entries", []),
        final_payload.get("skills", []),
    )
    final_payload["seniority_level"] = derive_seniority_level(
        final_payload.get("current_last_job")
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
    parse_source = "fallback"
    if ENABLE_LLM_PARSE:
        strict_parsed = parse_resume_with_ft_v2(normalized_text)

    if strict_parsed is None:
        logger.warning("V2 parse unavailable; using strict fallback")
        strict_parsed = extract_resume_features_fallback(normalized_text)
        parse_source = "fallback"
    else:
        recovered = extract_resume_features_fallback(normalized_text)
        if _needs_parse_recovery(strict_parsed, normalized_text):
            logger.warning("Sparse LLM parse detected; evaluating fallback recovery candidates")
        parse_source, strict_parsed = _choose_best_parse_with_source(strict_parsed, recovered, normalized_text)

    final_payload = build_final_payload(strict_parsed, normalized_text)
    final_payload["parse_source"] = parse_source
    return final_payload


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
