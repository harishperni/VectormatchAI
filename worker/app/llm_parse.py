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
LLM_PARSE_MODEL = os.getenv("OPENAI_PARSE_MODEL", "gpt-4.1-mini")
LLM_PARSE_TIMEOUT = int(os.getenv("LLM_PARSE_TIMEOUT_SECONDS", "60"))
LLM_PARSE_MAX_RETRIES = int(os.getenv("LLM_PARSE_MAX_RETRIES", "2"))


def _post_chat_completions(payload: dict[str, Any]) -> dict[str, Any] | None:
    if not OPENAI_API_KEY:
        logger.warning("[LLM_PARSE] OPENAI_API_KEY is not set; skipping OpenAI call")
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
    for attempt in range(1, LLM_PARSE_MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(request, timeout=LLM_PARSE_TIMEOUT) as response:
                raw = response.read().decode("utf-8")
                payload_json = json.loads(raw)
                logger.info(
                    "[LLM_PARSE] OpenAI call succeeded model=%s attempt=%s",
                    payload.get("model", "unknown"),
                    attempt,
                )
                return payload_json
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", errors="ignore")[:500]
            except Exception:
                detail = str(exc)
            logger.error("[LLM_PARSE] OpenAI HTTPError attempt=%s: %s", attempt, detail)
            return None
        except urllib.error.URLError as exc:
            logger.error("[LLM_PARSE] OpenAI URLError attempt=%s: %s", attempt, exc)
        except TimeoutError:
            logger.error("[LLM_PARSE] OpenAI request timed out attempt=%s", attempt)
        except json.JSONDecodeError:
            logger.error("[LLM_PARSE] OpenAI returned non-JSON response attempt=%s", attempt)
            return None

        if attempt < LLM_PARSE_MAX_RETRIES:
            time.sleep(0.4 * attempt)
    return None


def parse_resume_with_llm(text: str) -> dict[str, Any] | None:
    system_prompt = (
        "You are a resume parsing engine. Return ONLY valid JSON with keys: "
        "email, phone, skills (array), experience_years (number or null), "
        "highest_degree, candidate_location, current_last_job. "
        "For experience_years, include only professional work experience and EXCLUDE education duration."
    )
    user_prompt = f"Resume Text:\n{text[:3500]}"
    payload = {
        "model": LLM_PARSE_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {"type": "json_object"},
    }
    response = _post_chat_completions(payload)
    if not response:
        logger.warning("[LLM_PARSE] No usable response from OpenAI")
        return None
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        logger.warning("[LLM_PARSE] OpenAI response missing choices")
        return None
    message = choices[0].get("message", {})
    output = message.get("content")
    if not isinstance(output, str):
        logger.warning("[LLM_PARSE] OpenAI response missing message content")
        return None
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError:
        logger.warning("[LLM_PARSE] OpenAI content was not valid JSON object")
        return None
    logger.info("[LLM_PARSE] Parsed resume payload successfully")
    return parsed if isinstance(parsed, dict) else None
