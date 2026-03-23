from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlencode

from sqlalchemy import delete, desc, select
from sqlalchemy.orm import Session

from app.db.models import AuditLog, Candidate, Job, JobResume, Ranking, RecruiterAction, Resume
from app.services.embedding_service import (
    EMBEDDING_MODEL,
    cosine_similarity_percent,
    get_or_create_job_embedding,
    get_or_create_resume_embedding,
)
from app.services.llm_reasoning_service import OPENAI_REASONING_MODEL, generate_candidate_reasoning
from app.services.location_service import distance_miles_between
from app.services.scoring import weighted_score

SCORING_VERSION = "score_v3_embedding_semantic_gpt_only"
MODEL_VERSION = EMBEDDING_MODEL
LLM_TOP_K = int(os.getenv("LLM_TOP_K", "1000"))
ENABLE_LLM_SCORING = os.getenv("ENABLE_LLM_SCORING", "false").lower() == "true"
LLM_SCORE_WEIGHT = float(os.getenv("LLM_SCORE_WEIGHT", "0.2"))
LLM_CONFIDENCE_WEIGHT = float(os.getenv("LLM_CONFIDENCE_WEIGHT", "0.3"))
GPT_ONLY_RANKING = os.getenv("GPT_ONLY_RANKING", "true").lower() == "true"
INTERVIEW_TASK_EVENT = "interview_task_upsert"


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


LOCATION_IN_TEXT_PATTERN = re.compile(
    r"(?:location|based in)\s*[:\-]\s*([A-Za-z .'-]+,\s*(?:[A-Z]{2}|[A-Za-z]+)(?:,\s*(?:USA|US|United States))?)",
    re.IGNORECASE,
)
CITY_STATE_PATTERN = re.compile(r"\b([A-Za-z .'-]+,\s*[A-Z]{2})\b")


def _resolve_job_location(job: Job | None) -> str | None:
    if not job:
        return None
    if job.location and job.location.strip():
        return job.location.strip()
    description = job.description or ""
    match = LOCATION_IN_TEXT_PATTERN.search(description)
    if match:
        return match.group(1).strip()
    fallback = CITY_STATE_PATTERN.search(description)
    if fallback:
        return fallback.group(1).strip()
    return None


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


def _explainability_audit_flags(
    *,
    score: float,
    confidence: float,
    score_breakdown: dict[str, float],
    matched_skills: list[str],
    missing_skills: list[str],
) -> list[str]:
    flags: list[str] = []
    semantic = float(score_breakdown.get("semantic", 0.0))
    experience = float(score_breakdown.get("experience", 0.0))

    if score >= 80 and len(missing_skills) >= 2:
        flags.append("High score despite multiple missing skills")
    if semantic < 35 and score >= 75:
        flags.append("High final score but low semantic similarity")
    if confidence >= 95 and not matched_skills:
        flags.append("Very high confidence with weak skill evidence")
    if experience <= 10 and score >= 70:
        flags.append("Strong rank even though experience signal is weak")
    return flags


def _build_audit_summary(
    *,
    matched_skills: list[str],
    missing_skills: list[str],
    top_reasons: list[str],
    audit_flags: list[str],
) -> str:
    if audit_flags:
        return audit_flags[0]
    if matched_skills and missing_skills:
        return f"Matched {', '.join(matched_skills[:2])}; missing {', '.join(missing_skills[:2])}"
    if matched_skills:
        return f"Matched {', '.join(matched_skills[:3])}"
    if missing_skills:
        return f"Missing {', '.join(missing_skills[:3])}"
    if top_reasons:
        return str(top_reasons[0])
    return "Limited evidence"


def _build_audit_detail(
    *,
    matched_skills: list[str],
    missing_skills: list[str],
    top_reasons: list[str],
    summary: str | None,
) -> list[str]:
    detail: list[str] = []
    if matched_skills:
        detail.append(f"Matches: {', '.join(matched_skills[:4])}")
    if missing_skills:
        detail.append(f"Gaps: {', '.join(missing_skills[:4])}")
    if top_reasons:
        detail.extend(str(item) for item in top_reasons[:2])
    if summary and not detail:
        detail.append(summary.strip())
    return detail[:3]


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


def _stable_hash(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _job_signature(job: Job) -> str:
    return _stable_hash(
        {
            "title": job.title or "",
            "description": job.description or "",
            "required_skills": job.required_skills or [],
            "nice_to_have_skills": job.nice_to_have_skills or [],
            "min_experience_years": float(job.min_experience_years) if job.min_experience_years is not None else None,
            "domain_tags": job.domain_tags or [],
            "reasoning_model": OPENAI_REASONING_MODEL,
            "scoring_version": SCORING_VERSION,
            "gpt_only_ranking": GPT_ONLY_RANKING,
            "enable_llm_scoring": ENABLE_LLM_SCORING,
            "llm_score_weight": LLM_SCORE_WEIGHT,
            "llm_confidence_weight": LLM_CONFIDENCE_WEIGHT,
        }
    )


def _resume_signature(resume: Resume) -> str:
    return _stable_hash(
        {
            "raw_text": resume.raw_text or "",
            "skills_json": resume.skills_json if isinstance(resume.skills_json, list) else [],
            "experience_years": float(resume.experience_years) if resume.experience_years is not None else None,
            "parse_status": resume.parse_status or "",
            "parsed_json": resume.parsed_json if isinstance(resume.parsed_json, dict) else {},
        }
    )


def _ranking_is_fresh(
    ranking: Ranking | None,
    *,
    expected_job_sig: str,
    expected_resume_sig: str,
) -> bool:
    if not ranking:
        return False
    payload = ranking.explanation_json if isinstance(ranking.explanation_json, dict) else {}
    if payload.get("job_signature") != expected_job_sig:
        return False
    if payload.get("resume_signature") != expected_resume_sig:
        return False
    if payload.get("reasoning_model") != OPENAI_REASONING_MODEL:
        return False
    if payload.get("scoring_version") != SCORING_VERSION:
        return False
    return True


def run_ranking_for_job(db: Session, job: Job) -> int:
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
    job_sig = _job_signature(job)
    resume_ids = [resume.id for resume in resumes]

    existing_rankings = (
        db.execute(
            select(Ranking).where(
                Ranking.job_id == job.id,
                Ranking.scoring_version == SCORING_VERSION,
            )
        )
        .scalars()
        .all()
    )
    existing_by_resume_id: dict[uuid.UUID, Ranking] = {
        row.resume_id: row for row in existing_rankings if row.resume_id is not None
    }

    # Clean stale rankings for resumes no longer in parsed set.
    if resume_ids:
        db.execute(
            delete(Ranking).where(
                Ranking.job_id == job.id,
                Ranking.scoring_version == SCORING_VERSION,
                Ranking.resume_id.not_in(resume_ids),
            )
        )
    else:
        db.execute(
            delete(Ranking).where(
                Ranking.job_id == job.id,
                Ranking.scoring_version == SCORING_VERSION,
            )
        )

    pending_rows: list[tuple[Resume, RankingComputation, dict]] = []
    job_embedding_vector: list[float] | None = None
    try:
        job_embedding_vector = get_or_create_job_embedding(db, job).embedding
    except Exception:
        job_embedding_vector = None

    for resume in resumes:
        resume_sig = _resume_signature(resume)
        existing = existing_by_resume_id.get(resume.id)
        if _ranking_is_fresh(existing, expected_job_sig=job_sig, expected_resume_sig=resume_sig):
            continue

        semantic_source = "token_overlap_fallback"
        semantic = _semantic_score_fallback(job.description or "", resume.raw_text or "")
        if job_embedding_vector:
            try:
                resume_embedding = get_or_create_resume_embedding(db, resume)
                embedding_score = cosine_similarity_percent(job_embedding_vector, resume_embedding.embedding)
                semantic = embedding_score
                semantic_source = "embedding_cosine"
            except Exception:
                semantic = _semantic_score_fallback(job.description or "", resume.raw_text or "")
                semantic_source = "token_overlap_fallback"

        result = compute_ranking(job, resume, semantic)
        explanation_json: dict = {
            "score_breakdown": {
                "semantic": result.semantic,
                "skill": result.skill,
                "experience": result.experience,
                "domain": result.domain,
            },
            "semantic_source": semantic_source,
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
            "job_signature": job_sig,
            "resume_signature": resume_sig,
        }
        pending_rows.append((resume, result, explanation_json))

    # Apply LLM reasoning + scoring for all candidates (or capped by env).
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
        score_breakdown = llm_output.get("score_breakdown")
        if isinstance(score_breakdown, dict):
            semantic = _to_float(score_breakdown.get("semantic"))
            skill = _to_float(score_breakdown.get("skill"))
            experience = _to_float(score_breakdown.get("experience"))
            domain = _to_float(score_breakdown.get("domain"))
            if semantic is not None:
                result.semantic = _clamp_0_100(semantic)
            if skill is not None:
                result.skill = _clamp_0_100(skill)
            if experience is not None:
                result.experience = _clamp_0_100(experience)
            if domain is not None:
                result.domain = _clamp_0_100(domain)
            explanation_json["score_breakdown"] = {
                "semantic": result.semantic,
                "skill": result.skill,
                "experience": result.experience,
                "domain": result.domain,
            }

        matched = llm_output.get("matched_skills")
        if isinstance(matched, list):
            explanation_json["matched_skills"] = [str(item) for item in matched][:8]
            result.matched_skills = [str(item) for item in matched][:8]
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
            if GPT_ONLY_RANKING:
                result.final = llm_score
            elif ENABLE_LLM_SCORING:
                result.final = _clamp_0_100(
                    ((1.0 - LLM_SCORE_WEIGHT) * result.final) + (LLM_SCORE_WEIGHT * llm_score)
                )
        if llm_confidence is not None:
            llm_confidence = _clamp_0_100(llm_confidence)
            explanation_json["llm_confidence"] = llm_confidence
            if GPT_ONLY_RANKING:
                result.confidence = llm_confidence
            elif ENABLE_LLM_SCORING:
                result.confidence = _clamp_0_100(
                    ((1.0 - LLM_CONFIDENCE_WEIGHT) * result.confidence)
                    + (LLM_CONFIDENCE_WEIGHT * llm_confidence)
                )

        explanation_json["final_score"] = result.final
        explanation_json["final_confidence"] = result.confidence
        explanation_json["llm_used"] = True
        explanation_json["reasoning_model"] = OPENAI_REASONING_MODEL

    for resume, result, explanation_json in pending_rows:
        existing = existing_by_resume_id.get(resume.id)

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

    ranked_for_audit = sorted(pending_rows, key=lambda item: item[1].final, reverse=True)
    top_snapshot = []
    for rank, (resume, result, explanation_json) in enumerate(ranked_for_audit[:20], start=1):
        top_snapshot.append(
            {
                "rank": rank,
                "candidate_id": str(resume.candidate_id),
                "resume_id": str(resume.id),
                "score": result.final,
                "confidence": result.confidence,
                "top_reasons": explanation_json.get("top_reasons", []),
            }
        )
    avg_score = round(
        sum(item[1].final for item in ranked_for_audit) / len(ranked_for_audit), 2
    ) if ranked_for_audit else 0.0
    db.add(
        AuditLog(
            id=uuid.uuid4(),
            entity_type="job",
            entity_id=job.id,
            event_type="ranking_run_completed",
            payload={
                "processed_resumes": processed,
                "average_score": avg_score,
                "top_candidates": top_snapshot,
            },
        )
    )

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
    job = db.get(Job, job_id)
    job_location = _resolve_job_location(job)

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
        .where(
            Ranking.job_id == job_id,
            JobResume.job_id == job_id,
            Ranking.scoring_version == SCORING_VERSION,
        )
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
        matched_skills = payload.get("matched_skills", [])
        if not isinstance(matched_skills, list):
            matched_skills = []
        missing_skills = payload.get("missing_skills", [])
        if not isinstance(missing_skills, list):
            missing_skills = []
        resume_skills = [
            str(item).lower()
            for item in (resume.skills_json if isinstance(resume.skills_json, list) else [])
        ]
        candidate_action = action_by_candidate.get(str(ranking.candidate_id))
        experience_years = float(resume.experience_years) if resume.experience_years is not None else None
        score = float(ranking.score)

        if min_score is not None and score < min_score:
            continue
        if min_experience is not None and (experience_years is None or experience_years < min_experience):
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

        candidate_location = parsed_json.get("candidate_location") or candidate.location
        resume_distance = parsed_json.get("distance_miles")
        if not isinstance(resume_distance, (int, float)):
            computed_distance = distance_miles_between(job_location, candidate_location)
            if computed_distance is not None:
                resume_distance = computed_distance
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

        if total_experience_min is not None and (
            experience_years is None or experience_years < total_experience_min
        ):
            continue

        if status:
            status_l = status.lower()
            parse_status = (resume.parse_status or "").lower()
            action_status = (candidate_action or "").lower()
            if status_l == "review":
                pass
            elif status_l not in {parse_status, action_status}:
                continue

        audit_flags = _explainability_audit_flags(
            score=score,
            confidence=float(ranking.confidence),
            score_breakdown=payload.get("score_breakdown", {})
            if isinstance(payload.get("score_breakdown", {}), dict)
            else {},
            matched_skills=matched_skills,
            missing_skills=missing_skills,
        )
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
                "audit_flags": audit_flags,
                "audit_summary": _build_audit_summary(
                    matched_skills=matched_skills,
                    missing_skills=missing_skills,
                    top_reasons=reasons if isinstance(reasons, list) else [],
                    audit_flags=audit_flags,
                ),
                "audit_detail": _build_audit_detail(
                    matched_skills=matched_skills,
                    missing_skills=missing_skills,
                    top_reasons=reasons if isinstance(reasons, list) else [],
                    summary=payload.get("summary") if isinstance(payload.get("summary"), str) else None,
                ),
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
        .where(
            Ranking.job_id == job_id,
            Ranking.candidate_id == candidate_id,
            Ranking.scoring_version == SCORING_VERSION,
        )
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
    if action == "interviewed":
        ensure_interview_task_for_candidate(
            db,
            job_id=job_id,
            candidate_id=candidate_id,
            created_by=created_by,
        )
    db.commit()
    db.refresh(row)
    return row


def clear_candidate_action(db: Session, *, job_id: uuid.UUID, candidate_id: uuid.UUID) -> int:
    result = db.execute(
        delete(RecruiterAction).where(
            RecruiterAction.job_id == job_id,
            RecruiterAction.candidate_id == candidate_id,
        )
    )
    db.commit()
    return result.rowcount or 0


def _safe_uuid(value: object) -> uuid.UUID | None:
    if not isinstance(value, str):
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _to_iso(value: object) -> str | None:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return None


def _to_utc_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _google_calendar_url(
    *,
    title: str,
    details: str,
    start_at_utc: datetime,
    end_at_utc: datetime,
    location: str | None,
) -> str:
    query = {
        "action": "TEMPLATE",
        "text": title.strip() or "Interview",
        "details": details.strip() or "Interview session",
        "dates": f"{start_at_utc.strftime('%Y%m%dT%H%M%SZ')}/{end_at_utc.strftime('%Y%m%dT%H%M%SZ')}",
    }
    if location and location.strip():
        query["location"] = location.strip()
    return f"https://calendar.google.com/calendar/render?{urlencode(query)}"


def _read_interview_task_snapshots(db: Session, *, job_id: uuid.UUID) -> list[dict]:
    logs = (
        db.execute(
            select(AuditLog)
            .where(
                AuditLog.entity_type == "job",
                AuditLog.entity_id == job_id,
                AuditLog.event_type == INTERVIEW_TASK_EVENT,
            )
            .order_by(AuditLog.created_at.asc())
        )
        .scalars()
        .all()
    )

    snapshots_by_id: dict[str, dict] = {}
    for log in logs:
        payload = log.payload if isinstance(log.payload, dict) else {}
        task_id = payload.get("task_id")
        candidate_id = payload.get("candidate_id")
        if not isinstance(task_id, str) or not isinstance(candidate_id, str):
            continue

        existing = snapshots_by_id.get(task_id)
        if not existing:
            snapshots_by_id[task_id] = {
                "task_id": task_id,
                "candidate_id": candidate_id,
                "status": str(payload.get("status") or "pending"),
                "title": str(payload.get("title") or "Interview"),
                "interviewer": payload.get("interviewer"),
                "notes": payload.get("notes"),
                "meeting_provider": payload.get("meeting_provider") or "google_meet",
                "meeting_link": payload.get("meeting_link"),
                "google_calendar_url": payload.get("google_calendar_url"),
                "scheduled_start_at": payload.get("scheduled_start_at"),
                "scheduled_end_at": payload.get("scheduled_end_at"),
                "timezone": payload.get("timezone") or "UTC",
                "created_at": _to_iso(log.created_at),
                "updated_at": _to_iso(log.created_at),
            }
            continue

        existing.update(
            {
                "candidate_id": candidate_id,
                "status": str(payload.get("status") or existing.get("status") or "pending"),
                "title": payload.get("title") or existing.get("title") or "Interview",
                "interviewer": payload.get("interviewer"),
                "notes": payload.get("notes"),
                "meeting_provider": payload.get("meeting_provider") or existing.get("meeting_provider") or "google_meet",
                "meeting_link": payload.get("meeting_link"),
                "google_calendar_url": payload.get("google_calendar_url"),
                "scheduled_start_at": payload.get("scheduled_start_at"),
                "scheduled_end_at": payload.get("scheduled_end_at"),
                "timezone": payload.get("timezone") or existing.get("timezone") or "UTC",
                "updated_at": _to_iso(log.created_at),
            }
        )

    return sorted(
        snapshots_by_id.values(),
        key=lambda item: item.get("updated_at") or item.get("created_at") or "",
        reverse=True,
    )


def ensure_interview_task_for_candidate(
    db: Session,
    *,
    job_id: uuid.UUID,
    candidate_id: uuid.UUID,
    created_by: uuid.UUID | None = None,
) -> dict:
    current = [
        item
        for item in _read_interview_task_snapshots(db, job_id=job_id)
        if item.get("candidate_id") == str(candidate_id)
    ]
    if current and str(current[0].get("status") or "").lower() in {"pending", "scheduled"}:
        return current[0]

    task_id = str(uuid.uuid4())
    payload = {
        "task_id": task_id,
        "candidate_id": str(candidate_id),
        "status": "pending",
        "title": "Schedule interview",
        "interviewer": None,
        "notes": None,
        "meeting_provider": "google_meet",
        "meeting_link": None,
        "google_calendar_url": None,
        "scheduled_start_at": None,
        "scheduled_end_at": None,
        "timezone": "UTC",
    }
    db.add(
        AuditLog(
            id=uuid.uuid4(),
            entity_type="job",
            entity_id=job_id,
            event_type=INTERVIEW_TASK_EVENT,
            payload=payload,
            created_by=created_by,
        )
    )
    return payload


def list_interview_tasks(db: Session, *, job_id: uuid.UUID) -> list[dict]:
    snapshots = _read_interview_task_snapshots(db, job_id=job_id)
    candidate_ids = [
        parsed
        for parsed in (_safe_uuid(item.get("candidate_id")) for item in snapshots)
        if parsed is not None
    ]
    candidate_rows = (
        db.execute(select(Candidate).where(Candidate.id.in_(candidate_ids))).scalars().all()
        if candidate_ids
        else []
    )
    candidate_by_id = {str(candidate.id): candidate for candidate in candidate_rows}

    output: list[dict] = []
    for item in snapshots:
        candidate_id = str(item.get("candidate_id") or "")
        candidate = candidate_by_id.get(candidate_id)
        output.append(
            {
                "task_id": str(item.get("task_id") or ""),
                "candidate_id": candidate_id,
                "candidate_name": candidate.full_name if candidate and candidate.full_name else "Unknown Candidate",
                "candidate_email": candidate.primary_email if candidate else None,
                "status": str(item.get("status") or "pending"),
                "title": str(item.get("title") or "Schedule interview"),
                "interviewer": item.get("interviewer"),
                "notes": item.get("notes"),
                "meeting_provider": str(item.get("meeting_provider") or "google_meet"),
                "meeting_link": item.get("meeting_link"),
                "google_calendar_url": item.get("google_calendar_url"),
                "scheduled_start_at": item.get("scheduled_start_at"),
                "scheduled_end_at": item.get("scheduled_end_at"),
                "timezone": str(item.get("timezone") or "UTC"),
                "created_at": item.get("created_at"),
                "updated_at": item.get("updated_at"),
            }
        )
    return output


def schedule_interview_task(
    db: Session,
    *,
    job_id: uuid.UUID,
    candidate_id: uuid.UUID,
    starts_at: str,
    ends_at: str,
    interviewer: str | None,
    notes: str | None,
    timezone_name: str | None,
    meeting_link: str | None,
    created_by: uuid.UUID | None = None,
) -> dict:
    start_at = _to_utc_datetime(starts_at)
    end_at = _to_utc_datetime(ends_at)
    if not start_at or not end_at:
        raise ValueError("Invalid interview start/end date format")
    if end_at <= start_at:
        raise ValueError("Interview end must be after interview start")

    existing_tasks = list_interview_tasks(db, job_id=job_id)
    current = next((item for item in existing_tasks if item["candidate_id"] == str(candidate_id)), None)
    if not current:
        current = ensure_interview_task_for_candidate(
            db,
            job_id=job_id,
            candidate_id=candidate_id,
            created_by=created_by,
        )

    candidate_row = db.get(Candidate, candidate_id)
    candidate_name = candidate_row.full_name if candidate_row and candidate_row.full_name else "Candidate"
    title = f"Interview: {candidate_name}"
    details_parts = [
        f"Candidate: {candidate_name}",
        f"Interviewer: {interviewer.strip() if interviewer else 'TBD'}",
    ]
    if notes and notes.strip():
        details_parts.append(f"Notes: {notes.strip()}")

    calendar_url = _google_calendar_url(
        title=title,
        details="\n".join(details_parts),
        start_at_utc=start_at,
        end_at_utc=end_at,
        location=meeting_link.strip() if meeting_link else "Google Meet",
    )

    payload = {
        "task_id": str(current.get("task_id")),
        "candidate_id": str(candidate_id),
        "status": "scheduled",
        "title": "Interview scheduled",
        "interviewer": interviewer.strip() if interviewer else None,
        "notes": notes.strip() if notes else None,
        "meeting_provider": "google_meet",
        "meeting_link": meeting_link.strip() if meeting_link else None,
        "google_calendar_url": calendar_url,
        "scheduled_start_at": start_at.isoformat(),
        "scheduled_end_at": end_at.isoformat(),
        "timezone": timezone_name.strip() if timezone_name else "UTC",
    }
    db.add(
        AuditLog(
            id=uuid.uuid4(),
            entity_type="job",
            entity_id=job_id,
            event_type=INTERVIEW_TASK_EVENT,
            payload=payload,
            created_by=created_by,
        )
    )
    db.commit()

    refreshed = list_interview_tasks(db, job_id=job_id)
    matched = next((item for item in refreshed if item["task_id"] == payload["task_id"]), None)
    if matched:
        return matched
    return {
        **payload,
        "candidate_name": candidate_name,
        "candidate_email": candidate_row.primary_email if candidate_row else None,
        "created_at": None,
        "updated_at": datetime.now(UTC).isoformat(),
    }
