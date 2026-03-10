import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import delete, desc, select
from sqlalchemy.orm import Session

from app.db.models import (
    AuditLog,
    Candidate,
    JobResume,
    Ranking,
    RecruiterAction,
    Resume,
    ResumeEmbedding,
)
from app.db.session import get_db
from app.schemas.jobs import JobCreate, JobOut, JobUpdate
from app.services.ingestion_service import create_resume_entry, save_resume_file
from app.services.jobs_service import create_job, get_job, list_jobs, update_job
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


@router.patch("/{job_id}", response_model=JobOut)
def update_job_handler(job_id: str, payload: JobUpdate, db: Session = Depends(get_db)) -> JobOut:
    try:
        parsed_id = uuid.UUID(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid job_id format") from exc

    job = get_job(db, parsed_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return update_job(db, job, payload)


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

    rows = db.execute(
        select(Resume.parse_status)
        .join(JobResume, JobResume.resume_id == Resume.id)
        .where(JobResume.job_id == parsed_id)
    ).all()

    total_uploaded = len(rows)
    queued = sum(1 for (status,) in rows if status == "pending")
    queue_failed = sum(1 for (status,) in rows if status == "failed")

    return {
        "job_id": job_id,
        "queued": queued,
        "queue_failed": queue_failed,
        "total_uploaded": total_uploaded,
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
                "parsed_json": parsed_json,
                "raw_text_preview": (resume.raw_text or "")[:600],
                "uploaded_at": link.created_at.isoformat() if link.created_at else None,
            }
        )

    return {"job_id": job_id, "count": len(items), "items": items}


@router.get("/{job_id}/resumes/{resume_id}")
def job_resume_detail_handler(job_id: str, resume_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        parsed_job_id = uuid.UUID(job_id)
        parsed_resume_id = uuid.UUID(resume_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid UUID format") from exc

    if not get_job(db, parsed_job_id):
        raise HTTPException(status_code=404, detail="Job not found")

    row = db.execute(
        select(JobResume, Resume, Candidate)
        .join(Resume, Resume.id == JobResume.resume_id)
        .join(Candidate, Candidate.id == JobResume.candidate_id)
        .where(JobResume.job_id == parsed_job_id, JobResume.resume_id == parsed_resume_id)
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Resume not found for job")

    link, resume, candidate = row
    parsed_json = resume.parsed_json if isinstance(resume.parsed_json, dict) else {}
    return {
        "job_resume_id": str(link.id),
        "job_id": job_id,
        "resume_id": str(resume.id),
        "candidate_id": str(candidate.id),
        "candidate_name": candidate.full_name or "Unknown Candidate",
        "parse_status": resume.parse_status,
        "parse_error": resume.parse_error,
        "source_filename": resume.source_filename,
        "parsed_json": parsed_json,
        "raw_text": resume.raw_text or "",
        "created_at": resume.created_at.isoformat() if resume.created_at else None,
    }


@router.delete("/{job_id}/resumes/{resume_id}")
def delete_job_resume_handler(job_id: str, resume_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        parsed_job_id = uuid.UUID(job_id)
        parsed_resume_id = uuid.UUID(resume_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid UUID format") from exc

    if not get_job(db, parsed_job_id):
        raise HTTPException(status_code=404, detail="Job not found")

    row = db.execute(
        select(JobResume, Resume)
        .join(Resume, Resume.id == JobResume.resume_id)
        .where(JobResume.job_id == parsed_job_id, JobResume.resume_id == parsed_resume_id)
        .limit(1)
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Resume not found for job")

    link, resume = row
    candidate_id = resume.candidate_id

    rankings_deleted = db.execute(
        delete(Ranking).where(Ranking.job_id == parsed_job_id, Ranking.resume_id == parsed_resume_id)
    ).rowcount or 0
    links_deleted = db.execute(
        delete(JobResume).where(JobResume.job_id == parsed_job_id, JobResume.resume_id == parsed_resume_id)
    ).rowcount or 0

    resume_deleted = 0
    candidate_deleted = 0

    remaining_resume_links = db.execute(
        select(JobResume.id).where(JobResume.resume_id == parsed_resume_id).limit(1)
    ).first()
    if not remaining_resume_links:
        db.execute(delete(ResumeEmbedding).where(ResumeEmbedding.resume_id == parsed_resume_id))
        db.execute(delete(Ranking).where(Ranking.resume_id == parsed_resume_id))
        resume_deleted = db.execute(delete(Resume).where(Resume.id == parsed_resume_id)).rowcount or 0

        has_other_resumes = db.execute(
            select(Resume.id).where(Resume.candidate_id == candidate_id).limit(1)
        ).first()
        if not has_other_resumes:
            db.execute(delete(RecruiterAction).where(RecruiterAction.candidate_id == candidate_id))
            candidate_deleted = db.execute(
                delete(Candidate).where(Candidate.id == candidate_id)
            ).rowcount or 0

    db.add(
        AuditLog(
            id=uuid.uuid4(),
            entity_type="job",
            entity_id=parsed_job_id,
            event_type="resume_deleted",
            payload={
                "resume_id": str(parsed_resume_id),
                "candidate_id": str(candidate_id),
                "links_deleted": links_deleted,
                "rankings_deleted": rankings_deleted,
                "resume_deleted": resume_deleted,
                "candidate_deleted": candidate_deleted,
            },
        )
    )

    db.commit()

    return {
        "job_id": job_id,
        "resume_id": resume_id,
        "status": "deleted",
        "links_deleted": links_deleted,
        "rankings_deleted": rankings_deleted,
        "resume_deleted": resume_deleted,
        "candidate_deleted": candidate_deleted,
    }
