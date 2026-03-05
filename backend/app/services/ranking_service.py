from __future__ import annotations

import os
import uuid
from dataclasses import dataclass

from sqlalchemy import delete, desc, select
from sqlalchemy.orm import Session

from app.db.models import Candidate, Job, JobResume, Ranking, RecruiterAction, Resume
from app.services.embedding_service import (
    EMBEDDING_MODEL,
    cosine_similarity_percent,
    get_or_create_job_embedding,
    get_or_create_resume_embedding,
)
from app.services.llm_reasoning_service import OLLAMA_MODEL, generate_candidate_reasoning
from app.services.scoring import weighted_score

SCORING_VERSION = "score_v1.0"
MODEL_VERSION = EMBEDDING_MODEL
LLM_TOP_K = int(os.getenv("LLM_TOP_K", "5"))
ENABLE_LLM_SCORING = os.getenv("ENABLE_LLM_SCORING", "false").lower() == "true"
LLM_SCORE_WEIGHT = float(os.getenv("LLM_SCORE_WEIGHT", "0.2"))
LLM_CONFIDENCE_WEIGHT = float(os.getenv("LLM_CONFIDENCE_WEIGHT", "0.3"))


@dataclass
class RankingComputation:
    semantic: float
    skill: float
    experience: float
    domain: float
    final: float
    confidence: float
    matched_skills: list[str]
    missing_skills: list[str]
    reasons: list[str]


def _clamp_0_100(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 2)


def _to_float(value: object) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _semantic_score_fallback(job_description: str, resume_text: str) -> float:
    job_tokens = set((job_description or "").lower().split())
    resume_tokens = set((resume_text or "").lower().split())
    if not job_tokens:
        return 0.0
    overlap = job_tokens.intersection(resume_tokens)
    return round((len(overlap) / len(job_tokens)) * 100.0, 2)


def _skill_score(job: Job, resume_skills: list[str]) -> tuple[float, list[str], list[str]]:
    resume_set = {skill.lower() for skill in resume_skills}
    required = [skill for skill in (job.required_skills or []) if skill]
    nice = [skill for skill in (job.nice_to_have_skills or []) if skill]

    matched_required = [skill for skill in required if skill.lower() in resume_set]
    matched_nice = [skill for skill in nice if skill.lower() in resume_set]
    missing_required = [skill for skill in required if skill.lower() not in resume_set]

    raw = (len(matched_required) * 10) + (len(matched_nice) * 5) - (len(missing_required) * 15)
    max_raw = (len(required) * 10) + (len(nice) * 5)
    min_raw = -(len(required) * 15)
    if max_raw == min_raw:
        normalized = 50.0
    else:
        normalized = ((raw - min_raw) / (max_raw - min_raw)) * 100.0
    return round(max(0.0, min(100.0, normalized)), 2), matched_required + matched_nice, missing_required


def _experience_score(min_years: float | None, resume_years: float | None) -> float:
    if min_years is None:
        return 100.0
    if not resume_years or min_years <= 0:
        return 0.0
    ratio = (resume_years / min_years) * 100.0
    return round(max(0.0, min(100.0, ratio)), 2)


def _domain_score(domain_tags: list[str], resume_text: str) -> float:
    if not domain_tags:
        return 100.0
    text = resume_text.lower()
    matches = sum(1 for tag in domain_tags if tag.lower() in text)
    return round((matches / len(domain_tags)) * 100.0, 2)


def _confidence_score(resume: Resume, resume_text: str, skills: list[str]) -> float:
    score = 40.0
    if resume_text.strip():
        score += 25.0
    if skills:
        score += 20.0
    if resume.experience_years is not None:
        score += 15.0
    return round(min(100.0, score), 2)


def compute_ranking(job: Job, resume: Resume, semantic: float) -> RankingComputation:
    resume_text = resume.raw_text or ""
    resume_skills = [str(skill) for skill in (resume.skills_json or [])]
    skill, matched_skills, missing_skills = _skill_score(job, resume_skills)
    experience = _experience_score(
        float(job.min_experience_years) if job.min_experience_years is not None else None,
        float(resume.experience_years) if resume.experience_years is not None else None,
    )
    domain = _domain_score(job.domain_tags or [], resume_text)
    final = weighted_score(semantic=semantic, skill=skill, experience=experience, domain=domain)
    confidence = _confidence_score(resume, resume_text, resume_skills)

    reasons: list[str] = []
    if matched_skills:
        reasons.append(f"Matched skills: {', '.join(matched_skills[:3])}")
    if resume.experience_years is not None:
        reasons.append(f"{float(resume.experience_years):.1f}+ years experience detected")
    if domain >= 50:
        reasons.append("Relevant domain overlap found")
    if not reasons:
        reasons = ["Resume parsed with limited matching signals"]

    return RankingComputation(
        semantic=semantic,
        skill=skill,
        experience=experience,
        domain=domain,
        final=final,
        confidence=confidence,
        matched_skills=matched_skills,
        missing_skills=missing_skills,
        reasons=reasons[:3],
    )


def run_ranking_for_job(db: Session, job: Job) -> int:
    db.execute(delete(Ranking).where(Ranking.job_id == job.id))

    resumes = (
        db.execute(
            select(Resume)
            .join(JobResume, JobResume.resume_id == Resume.id)
            .where(
                JobResume.job_id == job.id,
                Resume.parse_status == "parsed",
                Resume.raw_text.is_not(None),
            )
            .order_by(Resume.created_at.desc())
        )
        .scalars()
        .all()
    )
    processed = 0
    job_embedding_row = None
    try:
        job_embedding_row = get_or_create_job_embedding(db, job)
    except Exception:
        # Keep ranking functional even if embedding model/deps are not ready.
        job_embedding_row = None

    pending_rows: list[tuple[Resume, RankingComputation, dict]] = []
    for resume in resumes:
        semantic = 0.0
        if job_embedding_row:
            try:
                resume_embedding_row = get_or_create_resume_embedding(db, resume)
                semantic = cosine_similarity_percent(
                    job_embedding_row.embedding, resume_embedding_row.embedding
                )
            except Exception:
                semantic = _semantic_score_fallback(job.description or "", resume.raw_text or "")
        else:
            semantic = _semantic_score_fallback(job.description or "", resume.raw_text or "")

        result = compute_ranking(job, resume, semantic)
        explanation_json: dict = {
            "score_breakdown": {
                "semantic": result.semantic,
                "skill": result.skill,
                "experience": result.experience,
                "domain": result.domain,
            },
            "base_score": result.final,
            "base_confidence": result.confidence,
            "matched_skills": result.matched_skills,
            "missing_skills": result.missing_skills,
            "evidence_snippets": [
                {
                    "label": "Resume excerpt",
                    "text": (resume.raw_text or "")[:320],
                }
            ],
            "summary": " | ".join(result.reasons),
            "top_reasons": result.reasons,
            "model_version": MODEL_VERSION,
            "scoring_version": SCORING_VERSION,
            "llm_used": False,
            "reasoning_model": "heuristic",
            "llm_score": None,
            "llm_confidence": None,
            "final_score": result.final,
            "final_confidence": result.confidence,
        }
        pending_rows.append((resume, result, explanation_json))

    # Apply LLM reasoning for top-K candidates by score.
    ranked_candidates = sorted(pending_rows, key=lambda item: item[1].final, reverse=True)
    for resume, result, explanation_json in ranked_candidates[: max(0, LLM_TOP_K)]:
        llm_output = generate_candidate_reasoning(
            job_title=job.title or "",
            job_description=job.description or "",
            resume_text=resume.raw_text or "",
            matched_skills=result.matched_skills,
            missing_skills=result.missing_skills,
            score=result.final,
        )
        if not llm_output:
            continue
        summary = llm_output.get("summary")
        strengths = llm_output.get("strengths")
        missing = llm_output.get("missing_skills")
        confidence_reasoning = llm_output.get("confidence_reasoning")
        top_reasons = llm_output.get("top_reasons")

        if isinstance(summary, str) and summary.strip():
            explanation_json["summary"] = summary.strip()
        if isinstance(strengths, list):
            explanation_json["strengths"] = [str(item) for item in strengths][:5]
        if isinstance(missing, list):
            explanation_json["missing_skills"] = [str(item) for item in missing][:8]
        if isinstance(confidence_reasoning, str):
            explanation_json["confidence_reasoning"] = confidence_reasoning.strip()
        if isinstance(top_reasons, list):
            explanation_json["top_reasons"] = [str(item) for item in top_reasons][:3]

        llm_score = _to_float(llm_output.get("llm_score"))
        llm_confidence = _to_float(llm_output.get("llm_confidence"))
        if llm_score is not None:
            llm_score = _clamp_0_100(llm_score)
            explanation_json["llm_score"] = llm_score
            if ENABLE_LLM_SCORING:
                result.final = _clamp_0_100(
                    ((1.0 - LLM_SCORE_WEIGHT) * result.final) + (LLM_SCORE_WEIGHT * llm_score)
                )
        if llm_confidence is not None:
            llm_confidence = _clamp_0_100(llm_confidence)
            explanation_json["llm_confidence"] = llm_confidence
            if ENABLE_LLM_SCORING:
                result.confidence = _clamp_0_100(
                    ((1.0 - LLM_CONFIDENCE_WEIGHT) * result.confidence)
                    + (LLM_CONFIDENCE_WEIGHT * llm_confidence)
                )

        explanation_json["final_score"] = result.final
        explanation_json["final_confidence"] = result.confidence
        explanation_json["llm_used"] = True
        explanation_json["reasoning_model"] = OLLAMA_MODEL

    for resume, result, explanation_json in pending_rows:
        existing = db.execute(
            select(Ranking).where(
                Ranking.job_id == job.id,
                Ranking.candidate_id == resume.candidate_id,
                Ranking.resume_id == resume.id,
                Ranking.scoring_version == SCORING_VERSION,
            )
        ).scalar_one_or_none()

        if existing:
            existing.score = result.final
            existing.confidence = result.confidence
            existing.semantic_score = result.semantic
            existing.skill_score = result.skill
            existing.experience_score = result.experience
            existing.domain_score = result.domain
            existing.explanation_json = explanation_json
            existing.model_version = MODEL_VERSION
        else:
            db.add(
                Ranking(
                    id=uuid.uuid4(),
                    job_id=job.id,
                    candidate_id=resume.candidate_id,
                    resume_id=resume.id,
                    score=result.final,
                    confidence=result.confidence,
                    semantic_score=result.semantic,
                    skill_score=result.skill,
                    experience_score=result.experience,
                    domain_score=result.domain,
                    explanation_json=explanation_json,
                    model_version=MODEL_VERSION,
                    scoring_version=SCORING_VERSION,
                )
            )
        processed += 1

    db.commit()
    return processed


def get_rankings_for_job(
    db: Session,
    job_id: uuid.UUID,
    *,
    min_score: float | None = None,
    min_experience: float | None = None,
    skill: str | None = None,
    action: str | None = None,
    keyword: str | None = None,
    status: str | None = None,
    highest_degree: str | None = None,
    distance_max: float | None = None,
    sponsorship_required: bool | None = None,
    total_experience_min: float | None = None,
) -> list[dict]:
    rows = db.execute(
        select(Ranking, Candidate, Resume)
        .join(Candidate, Candidate.id == Ranking.candidate_id)
        .join(Resume, Resume.id == Ranking.resume_id)
        .join(
            JobResume,
            (JobResume.job_id == Ranking.job_id)
            & (JobResume.candidate_id == Ranking.candidate_id)
            & (JobResume.resume_id == Ranking.resume_id),
        )
        .where(Ranking.job_id == job_id, JobResume.job_id == job_id)
        .order_by(desc(Ranking.score))
    ).all()

    latest_actions = db.execute(
        select(RecruiterAction)
        .where(RecruiterAction.job_id == job_id)
        .order_by(desc(RecruiterAction.created_at))
    ).scalars().all()
    action_by_candidate: dict[str, str] = {}
    for row in latest_actions:
        key = str(row.candidate_id)
        if key not in action_by_candidate:
            action_by_candidate[key] = row.action

    output: list[dict] = []
    for ranking, candidate, resume in rows:
        payload = ranking.explanation_json if isinstance(ranking.explanation_json, dict) else {}
        parsed_json = resume.parsed_json if isinstance(resume.parsed_json, dict) else {}
        reasons = payload.get("top_reasons", [])
        resume_skills = [
            str(item).lower()
            for item in (resume.skills_json if isinstance(resume.skills_json, list) else [])
        ]
        candidate_action = action_by_candidate.get(str(ranking.candidate_id))
        experience_years = float(resume.experience_years) if resume.experience_years is not None else 0.0
        score = float(ranking.score)

        if min_score is not None and score < min_score:
            continue
        if min_experience is not None and experience_years < min_experience:
            continue
        if skill and skill.lower() not in resume_skills:
            continue
        if action and (candidate_action or "").lower() != action.lower():
            continue
        if keyword:
            keyword_l = keyword.lower()
            haystack = " ".join(
                [
                    candidate.full_name or "",
                    resume.raw_text or "",
                    " ".join(reasons if isinstance(reasons, list) else []),
                ]
            ).lower()
            if keyword_l not in haystack:
                continue

        degree = parsed_json.get("highest_degree")
        if highest_degree and isinstance(degree, str):
            if highest_degree.lower() not in degree.lower():
                continue
        elif highest_degree and not isinstance(degree, str):
            continue

        resume_distance = parsed_json.get("distance_miles")
        if distance_max is not None:
            if isinstance(resume_distance, (int, float)):
                if float(resume_distance) > distance_max:
                    continue
            else:
                continue

        sponsorship = parsed_json.get("sponsorship_required")
        if sponsorship_required is not None:
            if isinstance(sponsorship, bool):
                if sponsorship != sponsorship_required:
                    continue
            else:
                continue

        if total_experience_min is not None and experience_years < total_experience_min:
            continue

        if status:
            status_l = status.lower()
            parse_status = (resume.parse_status or "").lower()
            action_status = (candidate_action or "").lower()
            if status_l == "review":
                pass
            elif status_l not in {parse_status, action_status}:
                continue

        output.append(
            {
                "candidate_id": str(ranking.candidate_id),
                "resume_id": str(ranking.resume_id),
                "candidate_name": candidate.full_name or "Unknown Candidate",
                "candidate_type": "External",
                "applied_at": resume.created_at.isoformat() if resume.created_at else None,
                "stage": "Review",
                "step": "Review",
                "current_last_job": parsed_json.get("current_last_job"),
                "score": score,
                "confidence": float(ranking.confidence),
                "experience_years": experience_years,
                "highest_degree": degree if isinstance(degree, str) else None,
                "distance_miles": float(resume_distance)
                if isinstance(resume_distance, (float, int))
                else None,
                "sponsorship_required": sponsorship if isinstance(sponsorship, bool) else None,
                "top_reasons": reasons[:3] if isinstance(reasons, list) else [],
                "action_status": candidate_action,
            }
        )
    return output


def get_candidate_explanation(
    db: Session, job_id: uuid.UUID, candidate_id: uuid.UUID
) -> dict | None:
    ranking = db.execute(
        select(Ranking)
        .join(
            JobResume,
            (JobResume.job_id == Ranking.job_id)
            & (JobResume.candidate_id == Ranking.candidate_id)
            & (JobResume.resume_id == Ranking.resume_id),
        )
        .where(Ranking.job_id == job_id, Ranking.candidate_id == candidate_id)
        .order_by(desc(Ranking.score), desc(Ranking.created_at))
    ).scalar_one_or_none()
    if not ranking:
        return None

    payload = ranking.explanation_json or {}
    model_version = payload.get("reasoning_model")
    if not isinstance(model_version, str):
        model_version = ranking.model_version
    return {
        "score_breakdown": payload.get(
            "score_breakdown",
            {
                "semantic": float(ranking.semantic_score),
                "skill": float(ranking.skill_score),
                "experience": float(ranking.experience_score),
                "domain": float(ranking.domain_score),
            },
        ),
        "matched_skills": payload.get("matched_skills", []),
        "missing_skills": payload.get("missing_skills", []),
        "evidence_snippets": payload.get("evidence_snippets", []),
        "summary": payload.get("summary", "No explanation available."),
        "model_version": model_version,
        "scoring_version": ranking.scoring_version,
        "base_score": payload.get("base_score"),
        "llm_score": payload.get("llm_score"),
        "final_score": payload.get("final_score", float(ranking.score)),
        "base_confidence": payload.get("base_confidence"),
        "llm_confidence": payload.get("llm_confidence"),
        "final_confidence": payload.get("final_confidence", float(ranking.confidence)),
        "llm_used": bool(payload.get("llm_used", False)),
        "confidence_reasoning": payload.get("confidence_reasoning"),
        "strengths": payload.get("strengths", []),
    }


def add_candidate_action(
    db: Session,
    *,
    job_id: uuid.UUID,
    candidate_id: uuid.UUID,
    action: str,
    notes: str | None,
    created_by: uuid.UUID,
) -> RecruiterAction:
    row = RecruiterAction(
        id=uuid.uuid4(),
        job_id=job_id,
        candidate_id=candidate_id,
        action=action,
        notes=notes,
        created_by=created_by,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
