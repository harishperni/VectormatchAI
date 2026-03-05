import os
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app.db.models import Candidate, Resume


UPLOAD_DIR = Path(os.getenv("RESUME_UPLOAD_DIR", "storage/resumes"))


def _safe_candidate_name(filename: str) -> str:
    stem = Path(filename).stem.strip()
    return stem if stem else "Unknown Candidate"


def create_resume_entry(
    db: Session,
    *,
    original_filename: str,
    mime_type: str | None,
    file_url: str,
) -> tuple[Candidate, Resume]:
    candidate = Candidate(
        id=uuid.uuid4(),
        full_name=_safe_candidate_name(original_filename),
    )
    resume = Resume(
        id=uuid.uuid4(),
        candidate_id=candidate.id,
        source_filename=original_filename,
        file_url=file_url,
        mime_type=mime_type,
        parse_status="pending",
    )
    db.add(candidate)
    db.add(resume)
    db.flush()
    return candidate, resume


def save_resume_file(file_bytes: bytes, original_filename: str) -> tuple[str, str]:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    extension = Path(original_filename).suffix.lower() or ".bin"
    file_id = f"{uuid.uuid4()}{extension}"
    target = UPLOAD_DIR / file_id
    target.write_bytes(file_bytes)
    return str(target), target.as_posix()
