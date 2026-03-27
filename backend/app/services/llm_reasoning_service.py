from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

OPENAI_API_BASE_URL = os.getenv("OPENAI_API_BASE_URL", "https://api.openai.com/v1")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_REASONING_MODEL = os.getenv("OPENAI_REASONING_MODEL", "gpt-4.1-mini")
OPENAI_TIMEOUT_SECONDS = int(os.getenv("OPENAI_TIMEOUT_SECONDS", "60"))
OPENAI_MAX_RETRIES = int(os.getenv("OPENAI_MAX_RETRIES", "2"))


def _post_chat_completions(payload: dict[str, Any]) -> dict[str, Any] | None:
    if not OPENAI_API_KEY:
        logger.warning("[LLM_REASONING] OPENAI_API_KEY is not set; skipping OpenAI call")
        return None

    url = f"{OPENAI_API_BASE_URL.rstrip('/')}/chat/completions"
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OPENAI_API_KEY}",
        },
        method="POST",
    )
    for attempt in range(1, OPENAI_MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(request, timeout=OPENAI_TIMEOUT_SECONDS) as response:
                raw = response.read().decode("utf-8")
                payload_json = json.loads(raw)
                logger.info(
                    "[LLM_REASONING] OpenAI call succeeded model=%s attempt=%s",
                    payload.get("model", "unknown"),
                    attempt,
                )
                return payload_json
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", errors="ignore")[:500]
            except Exception:
                detail = str(exc)
            logger.error("[LLM_REASONING] OpenAI HTTPError attempt=%s: %s", attempt, detail)
            return None
        except urllib.error.URLError as exc:
            logger.error("[LLM_REASONING] OpenAI URLError attempt=%s: %s", attempt, exc)
        except TimeoutError:
            logger.error("[LLM_REASONING] OpenAI request timed out attempt=%s", attempt)
        except json.JSONDecodeError:
            logger.error("[LLM_REASONING] OpenAI returned non-JSON response attempt=%s", attempt)
            return None

        if attempt < OPENAI_MAX_RETRIES:
            time.sleep(0.4 * attempt)
    return None


def _safe_json(value: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            return parsed
        return None
    except json.JSONDecodeError:
        return None


def _clamp_0_100(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(max(0.0, min(100.0, number)), 2)


def _safe_string_list(value: Any, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    output: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        cleaned = " ".join(item.strip().split())
        if cleaned:
            output.append(cleaned)
        if len(output) >= limit:
            break
    return output


def _safe_evidence_snippets(value: Any, *, limit: int) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    snippets: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        claim = item.get("claim")
        evidence = item.get("evidence")
        if not isinstance(claim, str) or not isinstance(evidence, str):
            continue
        claim_text = " ".join(claim.strip().split())
        evidence_text = " ".join(evidence.strip().split())
        if not claim_text or not evidence_text:
            continue
        snippets.append(
            {
                "label": claim_text[:120],
                "text": evidence_text[:320],
            }
        )
        if len(snippets) >= limit:
            break
    return snippets


def _normalize_reasoning_payload(
    raw: dict[str, Any],
    *,
    resume_text: str,
    matched_skills: list[str],
    missing_skills: list[str],
    base_score: float,
) -> dict[str, Any]:
    rubric = raw.get("rubric")
    score_breakdown = raw.get("score_breakdown")
    if not isinstance(rubric, dict):
        rubric = {}
    if not isinstance(score_breakdown, dict):
        score_breakdown = {}

    semantic = _clamp_0_100(rubric.get("semantic_fit"))
    if semantic is None:
        semantic = _clamp_0_100(score_breakdown.get("semantic"))
    skill = _clamp_0_100(rubric.get("skill_fit"))
    if skill is None:
        skill = _clamp_0_100(score_breakdown.get("skill"))
    experience = _clamp_0_100(rubric.get("experience_fit"))
    if experience is None:
        experience = _clamp_0_100(score_breakdown.get("experience"))
    domain = _clamp_0_100(rubric.get("domain_fit"))
    if domain is None:
        domain = _clamp_0_100(score_breakdown.get("domain"))

    normalized_breakdown = {
        "semantic": semantic if semantic is not None else 0.0,
        "skill": skill if skill is not None else 0.0,
        "experience": experience if experience is not None else 0.0,
        "domain": domain if domain is not None else 0.0,
    }

    reasons = _safe_string_list(raw.get("top_reasons") or raw.get("reasons"), limit=3)
    strengths = _safe_string_list(raw.get("strengths"), limit=5)
    summary = raw.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        summary = " | ".join(reasons) if reasons else "Reasoning generated from structured rubric."
    summary = " ".join(summary.strip().split())[:600]

    evidence_snippets = _safe_evidence_snippets(raw.get("evidence_spans"), limit=5)
    if not evidence_snippets:
        fallback = " ".join((resume_text or "").strip().split())[:280]
        if fallback:
            evidence_snippets = [{"label": "Resume evidence", "text": fallback}]

    llm_score = _clamp_0_100(raw.get("overall_score"))
    if llm_score is None:
        llm_score = _clamp_0_100(raw.get("llm_score"))
    if llm_score is None:
        llm_score = _clamp_0_100(base_score)

    llm_confidence = _clamp_0_100(raw.get("overall_confidence"))
    if llm_confidence is None:
        llm_confidence = _clamp_0_100(raw.get("llm_confidence"))

    confidence_reasoning = raw.get("confidence_reasoning")
    if not isinstance(confidence_reasoning, str):
        confidence_reasoning = None

    model_matched = _safe_string_list(raw.get("matched_skills"), limit=8)
    model_missing = _safe_string_list(raw.get("missing_skills"), limit=8)

    return {
        "score_breakdown": normalized_breakdown,
        "rubric_scores": {
            "semantic_fit": normalized_breakdown["semantic"],
            "skill_fit": normalized_breakdown["skill"],
            "experience_fit": normalized_breakdown["experience"],
            "domain_fit": normalized_breakdown["domain"],
        },
        "matched_skills": model_matched or matched_skills[:8],
        "missing_skills": model_missing or missing_skills[:8],
        "summary": summary,
        "strengths": strengths,
        "confidence_reasoning": confidence_reasoning,
        "top_reasons": reasons,
        "evidence_snippets": evidence_snippets,
        "llm_score": llm_score,
        "llm_confidence": llm_confidence,
    }


def generate_candidate_reasoning(
    *,
    job_title: str,
    job_description: str,
    resume_text: str,
    matched_skills: list[str],
    missing_skills: list[str],
    score: float,
) -> dict[str, Any] | None:
    system_prompt = (
        "You are an ATS recruiter copilot. Return only valid JSON. Use this exact shape:\n"
        "{"
        '"rubric":{"semantic_fit":0-100,"skill_fit":0-100,"experience_fit":0-100,"domain_fit":0-100},'
        '"overall_score":0-100,'
        '"overall_confidence":0-100,'
        '"matched_skills":["..."],'
        '"missing_skills":["..."],'
        '"reasons":["..."],'
        '"summary":"...",'
        '"strengths":["..."],'
        '"confidence_reasoning":"...",'
        '"evidence_spans":[{"claim":"...","evidence":"verbatim snippet from resume text"}]'
        "}\n"
        "Rules: evidence must be grounded in the provided resume text; no fabricated claims."
    )
    user_prompt = (
        f"Job Title: {job_title}\n"
        f"Job Description: {job_description[:2500]}\n"
        f"Resume Text: {resume_text[:2500]}\n"
        f"Matched Skills: {', '.join(matched_skills) if matched_skills else 'None'}\n"
        f"Missing Skills: {', '.join(missing_skills) if missing_skills else 'None'}\n"
        f"Score: {score}\n"
    )
    payload = {
        "model": OPENAI_REASONING_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {"type": "json_object"},
    }
    response = _post_chat_completions(payload)
    if not response:
        logger.warning("[LLM_REASONING] No usable response from OpenAI")
        return None
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        logger.warning("[LLM_REASONING] OpenAI response missing choices")
        return None
    message = choices[0].get("message", {})
    output = message.get("content")
    if not isinstance(output, str):
        logger.warning("[LLM_REASONING] OpenAI response missing message content")
        return None
    parsed = _safe_json(output)
    if not parsed:
        logger.warning("[LLM_REASONING] OpenAI content was not valid JSON object")
        return None
    logger.info("[LLM_REASONING] Parsed reasoning payload successfully")
    return _normalize_reasoning_payload(
        parsed,
        resume_text=resume_text,
        matched_skills=matched_skills,
        missing_skills=missing_skills,
        base_score=score,
    )
