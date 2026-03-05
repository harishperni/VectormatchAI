import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.rankings import CandidateActionRequest, ExplanationResponse, RankingListResponse
from app.services.jobs_service import DEFAULT_USER_ID, get_job
from app.services.ranking_service import (
    SCORING_VERSION,
    add_candidate_action,
    get_candidate_explanation,
    get_rankings_for_job,
    run_ranking_for_job,
)

router = APIRouter()


@router.post("/{job_id}/rank")
def trigger_rank(job_id: str, db: Session = Depends(get_db)) -> dict[str, str | int]:
    try:
        parsed_id = uuid.UUID(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid job_id format") from exc

    job = get_job(db, parsed_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    processed = run_ranking_for_job(db, job)
    return {
        "job_id": job_id,
        "status": "ranking_completed",
        "processed_resumes": processed,
        "scoring_version": SCORING_VERSION,
    }


@router.get("/{job_id}/rankings", response_model=RankingListResponse)
def get_rankings(
    job_id: str,
    min_score: float | None = Query(default=None, ge=0, le=100),
    min_experience: float | None = Query(default=None, ge=0),
    skill: str | None = Query(default=None),
    action: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    status: str | None = Query(default=None),
    highest_degree: str | None = Query(default=None),
    distance_max: float | None = Query(default=None, ge=0),
    sponsorship_required: bool | None = Query(default=None),
    total_experience_min: float | None = Query(default=None, ge=0),
    db: Session = Depends(get_db),
) -> RankingListResponse:
    try:
        parsed_id = uuid.UUID(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid job_id format") from exc

    if not get_job(db, parsed_id):
        raise HTTPException(status_code=404, detail="Job not found")
    items = get_rankings_for_job(
        db,
        parsed_id,
        min_score=min_score,
        min_experience=min_experience,
        skill=skill,
        action=action,
        keyword=keyword,
        status=status,
        highest_degree=highest_degree,
        distance_max=distance_max,
        sponsorship_required=sponsorship_required,
        total_experience_min=total_experience_min,
    )
    return RankingListResponse(job_id=job_id, count=len(items), items=items)


@router.get("/{job_id}/candidates/{candidate_id}/explanation", response_model=ExplanationResponse)
def get_explanation(job_id: str, candidate_id: str, db: Session = Depends(get_db)) -> ExplanationResponse:
    try:
        parsed_id = uuid.UUID(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid job_id format") from exc

    if not get_job(db, parsed_id):
        raise HTTPException(status_code=404, detail="Job not found")
    try:
        parsed_candidate_id = uuid.UUID(candidate_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid candidate_id format") from exc

    payload = get_candidate_explanation(db, parsed_id, parsed_candidate_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Explanation not found")
    return ExplanationResponse(**payload)


@router.post("/{job_id}/candidates/{candidate_id}/action")
def candidate_action(
    job_id: str,
    candidate_id: str,
    payload: CandidateActionRequest,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    valid_actions = {"viewed", "shortlisted", "rejected", "interviewed", "hired"}
    if payload.action not in valid_actions:
        raise HTTPException(status_code=400, detail="Invalid action value")

    try:
        parsed_job_id = uuid.UUID(job_id)
        parsed_candidate_id = uuid.UUID(candidate_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid UUID format") from exc

    if not get_job(db, parsed_job_id):
        raise HTTPException(status_code=404, detail="Job not found")

    row = add_candidate_action(
        db,
        job_id=parsed_job_id,
        candidate_id=parsed_candidate_id,
        action=payload.action,
        notes=payload.notes,
        created_by=DEFAULT_USER_ID,
    )
    return {
        "job_id": job_id,
        "candidate_id": candidate_id,
        "action": row.action,
        "status": "saved",
    }
