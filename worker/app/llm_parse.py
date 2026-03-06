from __future__ import annotations

import json
import logging
import os
import re
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

WORK_START_PATTERN = re.compile(
    r"(work experience|professional experience|employment history|experience)\s*:?",
    re.IGNORECASE,
)
WORK_END_PATTERN = re.compile(
    r"(education|certifications|projects|skills)\s*:?",
    re.IGNORECASE,
)


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
    work_excerpt = _extract_work_excerpt(text)
    system_prompt = (
        "You are a resume parsing engine. Return ONLY valid JSON with keys: "
        "email, phone, skills (array), experience_years (number or null), "
        "highest_degree, candidate_location, current_last_job. "
        "For experience_years, include only professional work experience and EXCLUDE education duration. "
        "current_last_job must be JOB TITLE ONLY (no company name, no location, no dates)."
    )
    user_prompt = (
        f"Resume Text:\n{text[:4500]}\n\n"
        f"Work Experience Section (preferred source for dates/titles):\n{work_excerpt[:2500]}"
    )
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


def _extract_work_excerpt(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return text[:2500]

    start_idx = 0
    end_idx = len(lines)
    for idx, line in enumerate(lines):
        if WORK_START_PATTERN.search(line):
            start_idx = idx + 1
            break
    for idx in range(start_idx + 1, len(lines)):
        if WORK_END_PATTERN.search(lines[idx]):
            end_idx = idx
            break

    excerpt = "\n".join(lines[start_idx:end_idx]).strip()
    if excerpt:
        return excerpt
    return "\n".join(lines[:120])
