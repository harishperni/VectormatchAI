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
        "You are an ATS recruiter copilot. Return only valid JSON with keys: "
        "score_breakdown (object with semantic, skill, experience, domain as numbers 0-100), "
        "matched_skills (array of strings), "
        "summary (string), strengths (array of strings), missing_skills (array of strings), "
        "confidence_reasoning (string), top_reasons (array of strings), "
        "llm_score (number 0-100), llm_confidence (number 0-100)."
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
    return parsed
