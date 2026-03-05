import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.db.models import AuditLog, Candidate, JobResume, Resume
from app.db.session import get_db
from app.schemas.jobs import JobCreate, JobOut
from app.services.ingestion_service import create_resume_entry, save_resume_file
from app.services.jobs_service import create_job, get_job, list_jobs
from app.services.queue_service import enqueue_resume_ingestion

router = APIRouter()


@router.post("", response_model=JobOut)
def create_job_handler(payload: JobCreate, db: Session = Depends(get_db)) -> JobOut:
    return create_job(db, payload)


@router.get("", response_model=list[JobOut])
def list_jobs_handler(db: Session = Depends(get_db)) -> list[JobOut]:
    return list_jobs(db)


@router.get("/{job_id}", response_model=JobOut)
def get_job_handler(job_id: str, db: Session = Depends(get_db)) -> JobOut:
    try:
        parsed_id = uuid.UUID(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid job_id format") from exc

    job = get_job(db, parsed_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/{job_id}/resumes/upload")
async def upload_resumes_handler(
    job_id: str,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        parsed_id = uuid.UUID(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid job_id format") from exc

    if not get_job(db, parsed_id):
        raise HTTPException(status_code=404, detail="Job not found")

    uploaded_items: list[dict[str, Any]] = []
    queued_count = 0

    for file in files:
        raw = await file.read()
        if not raw:
            continue

        saved_path, file_url = save_resume_file(raw, file.filename or "resume.bin")
        candidate, resume = create_resume_entry(
            db,
            original_filename=file.filename or "resume.bin",
            mime_type=file.content_type,
            file_url=file_url,
        )
        db.add(
            JobResume(
                id=uuid.uuid4(),
                job_id=parsed_id,
                candidate_id=candidate.id,
                resume_id=resume.id,
            )
        )
        queued = enqueue_resume_ingestion(parsed_id, resume.id, file_url)
        if queued:
            queued_count += 1

        db.add(
            AuditLog(
                id=uuid.uuid4(),
                entity_type="job",
                entity_id=parsed_id,
                event_type="resume_ingestion_queued" if queued else "resume_ingestion_queue_failed",
                payload={
                    "candidate_id": str(candidate.id),
                    "resume_id": str(resume.id),
                    "source_filename": file.filename,
                    "saved_path": saved_path,
                },
            )
        )

        uploaded_items.append(
            {
                "candidate_id": str(candidate.id),
                "resume_id": str(resume.id),
                "filename": file.filename,
                "queued": queued,
            }
        )

    db.commit()

    return {
        "job_id": job_id,
        "uploaded_count": len(uploaded_items),
        "queued_count": queued_count,
        "items": uploaded_items,
    }


@router.get("/{job_id}/ingestion-status")
def ingestion_status_handler(job_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        parsed_id = uuid.UUID(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid job_id format") from exc

    if not get_job(db, parsed_id):
        raise HTTPException(status_code=404, detail="Job not found")

    logs = db.execute(
        select(AuditLog).where(
            AuditLog.entity_type == "job",
            AuditLog.entity_id == parsed_id,
            AuditLog.event_type.in_(
                ["resume_ingestion_queued", "resume_ingestion_queue_failed"]
            ),
        )
    ).scalars().all()

    queued = 0
    queue_failed = 0
    for row in logs:
        if row.event_type == "resume_ingestion_queued":
            queued += 1
        elif row.event_type == "resume_ingestion_queue_failed":
            queue_failed += 1

    return {
        "job_id": job_id,
        "queued": queued,
        "queue_failed": queue_failed,
        "total_uploaded": len(logs),
    }


@router.get("/{job_id}/resumes")
def job_resumes_handler(job_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        parsed_id = uuid.UUID(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid job_id format") from exc

    if not get_job(db, parsed_id):
        raise HTTPException(status_code=404, detail="Job not found")

    rows = db.execute(
        select(JobResume, Resume, Candidate)
        .join(Resume, Resume.id == JobResume.resume_id)
        .join(Candidate, Candidate.id == JobResume.candidate_id)
        .where(JobResume.job_id == parsed_id)
        .order_by(desc(JobResume.created_at))
    ).all()

    items: list[dict[str, Any]] = []
    for link, resume, candidate in rows:
        parsed_json = resume.parsed_json if isinstance(resume.parsed_json, dict) else {}
        skills_json = resume.skills_json if isinstance(resume.skills_json, list) else []
        items.append(
            {
                "job_resume_id": str(link.id),
                "candidate_id": str(candidate.id),
                "resume_id": str(resume.id),
                "candidate_name": candidate.full_name or "Unknown Candidate",
                "email": candidate.primary_email or parsed_json.get("email"),
                "source_filename": resume.source_filename,
                "parse_status": resume.parse_status,
                "experience_years": float(resume.experience_years) if resume.experience_years is not None else None,
                "skills": [str(skill) for skill in skills_json],
                "parse_error": resume.parse_error,
                "uploaded_at": link.created_at.isoformat() if link.created_at else None,
            }
        )

    return {"job_id": job_id, "count": len(items), "items": items}
