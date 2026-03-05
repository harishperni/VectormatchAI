from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
OLLAMA_TIMEOUT_SECONDS = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "20"))


def _post_generate(payload: dict[str, Any]) -> dict[str, Any] | None:
    url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/generate"
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=OLLAMA_TIMEOUT_SECONDS) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
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
    prompt = (
        "You are an ATS recruiter copilot. "
        "Return only valid JSON with keys: "
        "summary (string), strengths (array of strings), missing_skills (array of strings), "
        "confidence_reasoning (string), top_reasons (array of strings), "
        "llm_score (number 0-100), llm_confidence (number 0-100). "
        "Do not add markdown.\n\n"
        f"Job Title: {job_title}\n"
        f"Job Description: {job_description[:2500]}\n"
        f"Resume Text: {resume_text[:2500]}\n"
        f"Matched Skills: {', '.join(matched_skills) if matched_skills else 'None'}\n"
        f"Missing Skills: {', '.join(missing_skills) if missing_skills else 'None'}\n"
        f"Score: {score}\n"
    )
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
    }
    response = _post_generate(payload)
    if not response:
        return None
    output = response.get("response")
    if not isinstance(output, str):
        return None
    parsed = _safe_json(output)
    if not parsed:
        return None
    return parsed
