from uuid import uuid4

from app.schemas.jobs import JobCreate, JobOut


jobs_store: dict[str, JobOut] = {}


MOCK_RANKINGS = [
    {
        "candidate_id": "8dfcc3e2-d7ea-4f00-9be8-fc7a2c8bcde0",
        "resume_id": "f10614c5-3b72-4707-a4a2-4ba7d97d6484",
        "candidate_name": "John Doe",
        "score": 92.4,
        "confidence": 87.1,
        "experience_years": 7.0,
        "top_reasons": [
            "Strong ServiceNow ITSM experience",
            "6+ years in similar role",
            "Healthcare domain overlap",
        ],
    },
    {
        "candidate_id": "6f4b06db-567e-487c-8048-afc5ea2b2ff6",
        "resume_id": "7234ba88-47d0-4fd2-bf36-308476235b58",
        "candidate_name": "Alice Lee",
        "score": 88.0,
        "confidence": 84.2,
        "experience_years": 6.0,
        "top_reasons": [
            "ServiceNow workflow automation",
            "Good JavaScript fundamentals",
            "Incident management experience",
        ],
    },
]


def create_job(payload: JobCreate) -> JobOut:
    job_id = str(uuid4())
    row = JobOut(id=job_id, **payload.model_dump())
    jobs_store[job_id] = row
    return row
