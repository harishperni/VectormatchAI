import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.rankings import (
    CandidateActionRequest,
    CandidateBulkActionRequest,
    EvaluationResponse,
    ExplanationResponse,
    GoldenDatasetPayload,
    GoldenDatasetResponse,
    InterviewTaskListResponse,
    InterviewTaskRow,
    InterviewTaskScheduleRequest,
    InterviewTaskStatusRequest,
    RankingDiffRow,
    RankingListResponse,
)
from app.services.evaluation_service import (
    get_recent_ranking_run_payloads,
    load_golden_dataset,
    save_golden_dataset,
    resolve_expected_ids,
)
from app.services.jobs_service import DEFAULT_USER_ID, get_job
from app.services.ranking_service import (
    SCORING_VERSION,
    add_candidate_action,
    clear_candidate_action,
    get_candidate_explanation,
    list_interview_tasks,
    get_rankings_for_job,
    run_ranking_for_job,
    schedule_interview_task,
    set_interview_task_status,
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
    valid_actions = {"viewed", "shortlisted", "rejected", "interviewed", "hired", "reset"}
    if payload.action not in valid_actions:
        raise HTTPException(status_code=400, detail="Invalid action value")

    try:
        parsed_job_id = uuid.UUID(job_id)
        parsed_candidate_id = uuid.UUID(candidate_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid UUID format") from exc

    if not get_job(db, parsed_job_id):
        raise HTTPException(status_code=404, detail="Job not found")

    if payload.action == "reset":
        cleared = clear_candidate_action(
            db, job_id=parsed_job_id, candidate_id=parsed_candidate_id
        )
        return {
            "job_id": job_id,
            "candidate_id": candidate_id,
            "action": "reset",
            "status": "cleared",
            "cleared_count": str(cleared),
        }

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


@router.post("/{job_id}/candidates/actions")
def bulk_candidate_action(
    job_id: str,
    payload: CandidateBulkActionRequest,
    db: Session = Depends(get_db),
) -> dict[str, str | int]:
    valid_actions = {"viewed", "shortlisted", "rejected", "interviewed", "hired", "reset"}
    if payload.action not in valid_actions:
        raise HTTPException(status_code=400, detail="Invalid action value")

    try:
        parsed_job_id = uuid.UUID(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid job_id format") from exc

    if not get_job(db, parsed_job_id):
        raise HTTPException(status_code=404, detail="Job not found")

    saved = 0
    skipped = 0
    for candidate_id in payload.candidate_ids:
        try:
            parsed_candidate_id = uuid.UUID(candidate_id)
        except ValueError:
            skipped += 1
            continue
        if payload.action == "reset":
            clear_candidate_action(
                db, job_id=parsed_job_id, candidate_id=parsed_candidate_id
            )
        else:
            add_candidate_action(
                db,
                job_id=parsed_job_id,
                candidate_id=parsed_candidate_id,
                action=payload.action,
                notes=payload.notes,
                created_by=DEFAULT_USER_ID,
            )
        saved += 1

    return {
        "job_id": job_id,
        "status": "saved" if payload.action != "reset" else "cleared",
        "saved_count": saved,
        "skipped_count": skipped,
    }


@router.get("/{job_id}/evaluation", response_model=EvaluationResponse)
def evaluate_job(
    job_id: str,
    top_k: int = Query(default=5, ge=1, le=50),
    db: Session = Depends(get_db),
) -> EvaluationResponse:
    try:
        parsed_job_id = uuid.UUID(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid job_id format") from exc

    if not get_job(db, parsed_job_id):
        raise HTTPException(status_code=404, detail="Job not found")

    rows = get_rankings_for_job(db, parsed_job_id)
    current_top = rows[:top_k]

    avg_score = round(sum(float(row["score"]) for row in rows) / len(rows), 2) if rows else 0.0
    avg_confidence = (
        round(sum(float(row["confidence"]) for row in rows) / len(rows), 2) if rows else 0.0
    )

    dataset = load_golden_dataset(job_id)
    expected_ids, expected_reference = resolve_expected_ids(dataset, rows)
    matched_expected = sum(1 for row in current_top if row["candidate_id"] in expected_ids)
    precision_at_k = None
    recall_at_k = None
    if expected_ids:
        precision_at_k = round((matched_expected / top_k) * 100.0, 2)
        recall_at_k = round((matched_expected / len(expected_ids)) * 100.0, 2)

    run_payloads = get_recent_ranking_run_payloads(db, parsed_job_id, limit=2)
    previous_index: dict[str, tuple[int, float]] = {}
    if len(run_payloads) >= 2:
        previous_top = run_payloads[1].get("top_candidates", [])
        if isinstance(previous_top, list):
            for item in previous_top:
                if isinstance(item, dict):
                    candidate_id = str(item.get("candidate_id") or "")
                    rank_value = item.get("rank")
                    score_value = item.get("score")
                    if candidate_id and isinstance(rank_value, int):
                        previous_index[candidate_id] = (
                            rank_value,
                            float(score_value) if isinstance(score_value, (int, float)) else 0.0,
                        )

    run_diff: list[RankingDiffRow] = []
    for idx, row in enumerate(current_top, start=1):
        prev = previous_index.get(row["candidate_id"])
        run_diff.append(
            RankingDiffRow(
                candidate_id=row["candidate_id"],
                candidate_name=row["candidate_name"],
                current_rank=idx,
                previous_rank=prev[0] if prev else None,
                score_delta=round(float(row["score"]) - prev[1], 2) if prev else None,
                top_reasons=row.get("top_reasons", []),
            )
        )

    return EvaluationResponse(
        job_id=job_id,
        top_k=top_k,
        current_count=len(rows),
        precision_at_k=precision_at_k,
        recall_at_k=recall_at_k,
        expected_total=len(expected_ids),
        matched_expected=matched_expected,
        expected_reference=expected_reference,
        score_summary={"average_score": avg_score, "average_confidence": avg_confidence},
        run_diff=run_diff,
    )


@router.get("/{job_id}/golden-dataset", response_model=GoldenDatasetResponse)
def get_golden_dataset(job_id: str, db: Session = Depends(get_db)) -> GoldenDatasetResponse:
    try:
        parsed_job_id = uuid.UUID(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid job_id format") from exc

    if not get_job(db, parsed_job_id):
        raise HTTPException(status_code=404, detail="Job not found")

    dataset = load_golden_dataset(job_id) or {}
    return GoldenDatasetResponse(
        job_id=job_id,
        expected_top_candidate_ids=dataset.get("expected_top_candidate_ids", []),
        expected_top_candidate_names=dataset.get("expected_top_candidate_names", []),
    )


@router.post("/{job_id}/golden-dataset", response_model=GoldenDatasetResponse)
def upsert_golden_dataset(
    job_id: str, payload: GoldenDatasetPayload, db: Session = Depends(get_db)
) -> GoldenDatasetResponse:
    try:
        parsed_job_id = uuid.UUID(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid job_id format") from exc

    if not get_job(db, parsed_job_id):
        raise HTTPException(status_code=404, detail="Job not found")

    try:
        stored = save_golden_dataset(
            job_id,
            {
                "expected_top_candidate_ids": payload.expected_top_candidate_ids,
                "expected_top_candidate_names": payload.expected_top_candidate_names,
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return GoldenDatasetResponse(
        job_id=job_id,
        expected_top_candidate_ids=stored.get("expected_top_candidate_ids", []),
        expected_top_candidate_names=stored.get("expected_top_candidate_names", []),
    )


@router.get("/{job_id}/tasks", response_model=InterviewTaskListResponse)
def get_interview_tasks(job_id: str, db: Session = Depends(get_db)) -> InterviewTaskListResponse:
    try:
        parsed_job_id = uuid.UUID(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid job_id format") from exc

    if not get_job(db, parsed_job_id):
        raise HTTPException(status_code=404, detail="Job not found")

    items = list_interview_tasks(db, job_id=parsed_job_id)
    return InterviewTaskListResponse(
        job_id=job_id,
        count=len(items),
        items=[InterviewTaskRow(**item) for item in items],
    )


@router.post("/{job_id}/tasks/interviews/{candidate_id}/schedule", response_model=InterviewTaskRow)
def schedule_interview(
    job_id: str,
    candidate_id: str,
    payload: InterviewTaskScheduleRequest,
    db: Session = Depends(get_db),
) -> InterviewTaskRow:
    try:
        parsed_job_id = uuid.UUID(job_id)
        parsed_candidate_id = uuid.UUID(candidate_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid UUID format") from exc

    if not get_job(db, parsed_job_id):
        raise HTTPException(status_code=404, detail="Job not found")

    try:
        row = schedule_interview_task(
            db,
            job_id=parsed_job_id,
            candidate_id=parsed_candidate_id,
            starts_at=payload.starts_at,
            ends_at=payload.ends_at,
            interviewer=payload.interviewer,
            notes=payload.notes,
            timezone_name=payload.timezone,
            meeting_link=payload.meeting_link,
            created_by=DEFAULT_USER_ID,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return InterviewTaskRow(**row)


@router.post("/{job_id}/tasks/interviews/{candidate_id}/status", response_model=InterviewTaskRow)
def update_interview_task_status(
    job_id: str,
    candidate_id: str,
    payload: InterviewTaskStatusRequest,
    db: Session = Depends(get_db),
) -> InterviewTaskRow:
    action = payload.action.strip().lower()
    action_to_status = {
        "complete": "completed",
        "cancel": "cancelled",
        "reopen": "pending",
    }
    status = action_to_status.get(action)
    if not status:
        raise HTTPException(status_code=400, detail="Invalid action. Use complete, cancel, or reopen.")

    try:
        parsed_job_id = uuid.UUID(job_id)
        parsed_candidate_id = uuid.UUID(candidate_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid UUID format") from exc

    if not get_job(db, parsed_job_id):
        raise HTTPException(status_code=404, detail="Job not found")

    try:
        row = set_interview_task_status(
            db,
            job_id=parsed_job_id,
            candidate_id=parsed_candidate_id,
            status=status,
            notes=payload.notes,
            created_by=DEFAULT_USER_ID,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return InterviewTaskRow(**row)
