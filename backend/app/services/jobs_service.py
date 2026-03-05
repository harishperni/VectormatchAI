import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Job, User
from app.schemas.jobs import JobCreate, JobUpdate

DEFAULT_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def get_or_create_default_user(db: Session) -> User:
    user = db.get(User, DEFAULT_USER_ID)
    if user:
        return user

    user = User(
        id=DEFAULT_USER_ID,
        name="Default Recruiter",
        email="recruiter@local.dev",
        role="recruiter",
    )
    db.add(user)
    db.flush()
    return user


def create_job(db: Session, payload: JobCreate) -> Job:
    owner = get_or_create_default_user(db)
    job = Job(
        id=uuid.uuid4(),
        created_by=owner.id,
        title=payload.title,
        description=payload.description,
        location=payload.location,
        min_experience_years=payload.min_experience_years,
        required_skills=payload.required_skills,
        nice_to_have_skills=payload.nice_to_have_skills,
        domain_tags=payload.domain_tags,
        status="active",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def list_jobs(db: Session) -> list[Job]:
    rows = db.execute(select(Job).order_by(Job.created_at.desc())).scalars().all()
    return list(rows)


def get_job(db: Session, job_id: uuid.UUID) -> Job | None:
    return db.get(Job, job_id)


def update_job(db: Session, job: Job, payload: JobUpdate) -> Job:
    job.location = payload.location
    db.add(job)
    db.commit()
    db.refresh(job)
    return job
