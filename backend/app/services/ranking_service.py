from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from difflib import SequenceMatcher
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

from sqlalchemy import delete, desc, select
from sqlalchemy.orm import Session

from app.db.models import AuditLog, Candidate, Job, JobResume, Ranking, RecruiterAction, Resume
from app.services.embedding_service import (
    EMBEDDING_MODEL,
    cosine_similarity_percent,
    embed_text,
    get_or_create_job_embedding,
    get_or_create_resume_embedding,
)
from app.services.llm_reasoning_service import OPENAI_REASONING_MODEL, generate_candidate_reasoning
from app.services.location_service import distance_miles_between

SCORING_VERSION = "score_v8_structured_v1_work_mode_distance"
MODEL_VERSION = EMBEDDING_MODEL
LLM_TOP_K = int(os.getenv("LLM_TOP_K", "1000"))
ENABLE_LLM_SCORING = os.getenv("ENABLE_LLM_SCORING", "true").lower() == "true"
LLM_SCORE_WEIGHT = float(os.getenv("LLM_SCORE_WEIGHT", "0.2"))
LLM_CONFIDENCE_WEIGHT = float(os.getenv("LLM_CONFIDENCE_WEIGHT", "0.3"))
GPT_ONLY_RANKING = os.getenv("GPT_ONLY_RANKING", "false").lower() == "true"
ENABLE_SECTION_SEMANTIC = os.getenv("ENABLE_SECTION_SEMANTIC", "true").lower() == "true"
SEMANTIC_FULL_WEIGHT = float(os.getenv("SEMANTIC_FULL_WEIGHT", "0.45"))
SEMANTIC_SKILLS_WEIGHT = float(os.getenv("SEMANTIC_SKILLS_WEIGHT", "0.30"))
SEMANTIC_EXPERIENCE_WEIGHT = float(os.getenv("SEMANTIC_EXPERIENCE_WEIGHT", "0.20"))
SEMANTIC_PROJECTS_WEIGHT = float(os.getenv("SEMANTIC_PROJECTS_WEIGHT", "0.05"))

def _infer_job_seniority(job: Job) -> str:
    text = " ".join(
        part.strip()
        for part in [str(job.title or ""), str(job.description or "")]
        if str(part or "").strip()
    ).lower()

    if not text:
        return ""

    patterns = [
        ("principal+", [r"\bprincipal\b", r"\bstaff\b", r"\bdistinguished\b", r"\barchitect\b"]),
        ("lead/manager", [r"\blead\b", r"\bmanager\b", r"\bdirector\b", r"\bhead\b"]),
        ("senior", [r"\bsenior\b", r"\bsr\.?\b"]),
        ("mid", [r"\bmid\b", r"\bintermediate\b", r"\bii\b", r"\b2\b"]),
        ("junior/associate", [r"\bjunior\b", r"\bassociate\b", r"\bentry[- ]level\b", r"\bnew grad\b", r"\bintern\b", r"\btrainee\b"]),
    ]

    for label, regexes in patterns:
        if any(re.search(regex, text, re.IGNORECASE) for regex in regexes):
            return label

    return ""
INTERVIEW_TASK_EVENT = "interview_task_upsert"
INTERVIEW_TASK_STATUSES = {"pending", "scheduled", "completed", "cancelled"}

LOCATION_IN_TEXT_PATTERN = re.compile(
    r"(?:location|based in)\s*[:\-]\s*([A-Za-z .'-]+,\s*(?:[A-Z]{2}|[A-Za-z]+)(?:,\s*(?:USA|US|United States))?)",
    re.IGNORECASE,
)
CITY_STATE_PATTERN = re.compile(r"\b([A-Za-z .'-]+,\s*[A-Z]{2})\b")


@dataclass
class RankingComputation:
    semantic: float
    skill: float
    experience: float
    domain: float
    soft_skill: float
    managerial_skill: float
    distance_priority_bonus: float
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


def _resolve_candidate_location(
    parsed_json: dict[str, Any], candidate: Candidate, resume: Resume
) -> str | None:
    parsed_location = parsed_json.get("candidate_location")
    if isinstance(parsed_location, str) and parsed_location.strip():
        return parsed_location.strip()

    if candidate.location and candidate.location.strip():
        return candidate.location.strip()

    raw_text = resume.raw_text or ""
    match = LOCATION_IN_TEXT_PATTERN.search(raw_text)
    if match:
        return match.group(1).strip()

    fallback = CITY_STATE_PATTERN.search(raw_text)
    if fallback:
        return fallback.group(1).strip()

    return None


def _resolve_candidate_location_for_ranking(parsed_json: dict[str, Any], resume: Resume) -> str | None:
    parsed_location = parsed_json.get("candidate_location")
    if isinstance(parsed_location, str) and parsed_location.strip():
        return parsed_location.strip()

    raw_text = resume.raw_text or ""
    match = LOCATION_IN_TEXT_PATTERN.search(raw_text)
    if match:
        return match.group(1).strip()

    fallback = CITY_STATE_PATTERN.search(raw_text)
    if fallback:
        return fallback.group(1).strip()

    return None


def _normalize_skill_names(skills: list[str]) -> list[str]:
    alias_map = {
        "js": "javascript",
        "javascript": "javascript",
        "ts": "typescript",
        "react js": "react",
        "reactjs": "react",
        "node": "node js",
        "nodejs": "node js",
        "node js": "node js",
        "golang": "go",
        "postgres": "postgresql",
        "postgres sql": "postgresql",
        "aws amplify": "aws amplify",
        "aws bedrock": "aws bedrock",
        "open ai api": "openai api",
        "openai api": "openai api",
        "gcp": "gcp",
        "ci/cd": "ci/cd",
        "rag architecture": "rag architecture",
        "cloudflare pages": "cloudflare pages",
        "progressive web apps": "progressive web apps",
        "material ui": "material ui",
        "tailwind css": "tailwind css",
        "share point": "sharepoint",
        "sharepoint online": "sharepoint",
        "microsoft sharepoint": "sharepoint",
    }

    out: list[str] = []
    seen: set[str] = set()

    for skill in skills:
        raw = str(skill or "").strip()
        if not raw:
            continue
        normalized = re.sub(r"[^a-zA-Z0-9+#]+", " ", raw).strip().lower()
        normalized = re.sub(r"\s+", " ", normalized)
        normalized = alias_map.get(normalized, normalized)
        if normalized not in seen:
            seen.add(normalized)
            out.append(normalized)

    return out


def _skills_match(required_skill: str, candidate_skill: str) -> bool:
    if not required_skill or not candidate_skill:
        return False
    if required_skill == candidate_skill:
        return True

    req_tokens = set(required_skill.split())
    cand_tokens = set(candidate_skill.split())
    if not req_tokens or not cand_tokens:
        return False

    # Handles variants like "sharepoint online" vs "sharepoint".
    if req_tokens.issubset(cand_tokens) or cand_tokens.issubset(req_tokens):
        return True

    # Lightweight fuzzy match for close lexical variants that survive normalization.
    if len(required_skill) >= 5 and len(candidate_skill) >= 5:
        if SequenceMatcher(a=required_skill, b=candidate_skill).ratio() >= 0.88:
            return True

    return False


def _critical_required_skills(job: Job, required_skills: list[str]) -> set[str]:
    description = str(job.description or "")
    if not description.strip():
        return set()

    critical: set[str] = set()
    for skill in required_skills:
        skill_clean = str(skill).strip()
        if not skill_clean:
            continue
        escaped = re.escape(skill_clean)
        critical_patterns = [
            rf"(must have|required|mandatory)\s*[:\-]?\s*[^.\n]{{0,100}}\b{escaped}\b",
            rf"\b{escaped}\b[^.\n]{{0,100}}(must have|required|mandatory)",
        ]
        if any(re.search(pattern, description, re.IGNORECASE) for pattern in critical_patterns):
            critical.add(skill_clean.lower())
    return critical


def _extract_candidate_features(resume: Resume) -> dict[str, Any]:
    parsed = resume.parsed_json if isinstance(resume.parsed_json, dict) else {}

    top_skills = parsed.get("skills", [])
    top_skills = [str(s) for s in top_skills] if isinstance(top_skills, list) else []

    experience_entries = parsed.get("experience_entries", [])
    experience_entries = experience_entries if isinstance(experience_entries, list) else []

    projects = parsed.get("projects", [])
    projects = projects if isinstance(projects, list) else []

    certs = parsed.get("certifications", [])
    certs = certs if isinstance(certs, list) else []

    role_skills: list[str] = []
    role_titles: list[str] = []
    role_descriptions: list[str] = []

    for entry in experience_entries:
        if not isinstance(entry, dict):
            continue
        title = str(entry.get("title") or "").strip()
        if title:
            role_titles.append(title)

        desc = str(entry.get("description") or "").strip()
        if desc:
            role_descriptions.append(desc)

        skills_used = entry.get("skills_used", [])
        if isinstance(skills_used, list):
            role_skills.extend(str(s) for s in skills_used if s)

    project_tech: list[str] = []
    for project in projects:
        if not isinstance(project, dict):
            continue
        tech = project.get("technologies", [])
        if isinstance(tech, list):
            project_tech.extend(str(t) for t in tech if t)

    cert_names: list[str] = []
    for cert in certs:
        if isinstance(cert, dict) and cert.get("name"):
            cert_names.append(str(cert["name"]))

    fallback_skills = [str(skill) for skill in (resume.skills_json or [])] if isinstance(resume.skills_json, list) else []

    all_skills = _normalize_skill_names(top_skills + role_skills + project_tech + fallback_skills)

    return {
        "skills": all_skills,
        "titles": role_titles,
        "descriptions": role_descriptions,
        "projects": projects,
        "primary_domain": parsed.get("primary_domain"),
        "seniority_level": parsed.get("seniority_level"),
        "experience_years": resume.experience_years,
        "certifications": cert_names,
        "highest_degree": parsed.get("highest_degree"),
        "raw_text": resume.raw_text or "",
        "parsed_json": parsed,
    }


def _build_job_semantic_text(job: Job) -> str:
    required = ", ".join(str(skill).strip().lower() for skill in (job.required_skills or []) if skill)
    preferred = ", ".join(
        str(skill).strip().lower() for skill in (job.nice_to_have_skills or []) if skill
    )
    domains = ", ".join(str(tag).strip().lower() for tag in (job.domain_tags or []) if tag)
    parts = [
        f"job title: {str(job.title or '').strip().lower()}",
        f"Required Skills: {required}",
        f"Preferred Skills: {preferred}",
        f"Domain Tags: {domains}",
        f"Job Description: {str(job.description or '')[:2400].lower()}",
    ]
    return "\n".join(part for part in parts if part.strip())


def _build_resume_semantic_sections(candidate_features: dict[str, Any], resume_text: str) -> dict[str, str]:
    skills = candidate_features.get("skills", [])
    titles = candidate_features.get("titles", [])
    descriptions = candidate_features.get("descriptions", [])
    projects = candidate_features.get("projects", [])
    parsed_json = candidate_features.get("parsed_json", {})

    project_parts: list[str] = []
    if isinstance(projects, list):
        for item in projects[:3]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            desc = str(item.get("description") or "").strip()
            tech = item.get("technologies")
            tech_line = ", ".join(str(t) for t in tech[:6]) if isinstance(tech, list) else ""
            row = " | ".join(part for part in [name, desc, tech_line] if part)
            if row:
                project_parts.append(row)

    summary = str(parsed_json.get("professional_summary") or "").strip() if isinstance(parsed_json, dict) else ""
    current_job = str(parsed_json.get("current_last_job") or "").strip() if isinstance(parsed_json, dict) else ""

    return {
        "skills": ", ".join(str(skill).strip().lower() for skill in skills[:40])[:1800],
        "experience": "\n".join(
            [
                *(str(title).strip().lower() for title in titles[:6]),
                *(str(desc).strip().lower() for desc in descriptions[:3]),
            ]
        )[:2400],
        "projects": "\n".join(part.strip().lower() for part in project_parts)[:1600],
        "summary": " | ".join(part.strip().lower() for part in [summary, current_job] if part)[:1200],
        "full_text": str(resume_text or "")[:2600].lower(),
    }


def _weighted_section_semantic(
    job_vector: list[float], resume_sections: dict[str, str], base_semantic: float
) -> tuple[float, dict[str, float]]:
    components: dict[str, float] = {"full_text": _clamp_0_100(base_semantic)}
    weighted_total = components["full_text"] * SEMANTIC_FULL_WEIGHT
    weight_sum = SEMANTIC_FULL_WEIGHT

    section_weights = {
        "skills": SEMANTIC_SKILLS_WEIGHT,
        "experience": SEMANTIC_EXPERIENCE_WEIGHT,
        "projects": SEMANTIC_PROJECTS_WEIGHT,
    }

    for key, weight in section_weights.items():
        text = (resume_sections.get(key) or "").strip()
        if not text:
            continue
        try:
            section_vector = embed_text(text)
            section_score = cosine_similarity_percent(job_vector, section_vector)
        except Exception:
            continue
        components[key] = _clamp_0_100(section_score)
        weighted_total += components[key] * weight
        weight_sum += weight

    if weight_sum <= 0:
        return _clamp_0_100(base_semantic), components

    return _clamp_0_100(weighted_total / weight_sum), components


def _skill_score(job: Job, candidate_skills: list[str]) -> tuple[float, list[str], list[str]]:
    candidate_norm = _normalize_skill_names(candidate_skills)
    required = [str(skill).strip() for skill in (job.required_skills or []) if skill]
    preferred = [str(skill).strip() for skill in (job.nice_to_have_skills or []) if skill]
    required_norm = _normalize_skill_names(required)
    preferred_norm = _normalize_skill_names(preferred)

    matched_required: list[str] = []
    missing_required: list[str] = []
    for original, normalized in zip(required, required_norm):
        if any(_skills_match(normalized, candidate) for candidate in candidate_norm):
            matched_required.append(original)
        else:
            missing_required.append(original)

    matched_preferred: list[str] = []
    for original, normalized in zip(preferred, preferred_norm):
        if any(_skills_match(normalized, candidate) for candidate in candidate_norm):
            matched_preferred.append(original)

    critical_required = _critical_required_skills(job, required)
    matched_required_critical = [s for s in matched_required if s.lower() in critical_required]
    matched_required_regular = [s for s in matched_required if s.lower() not in critical_required]
    total_required_critical = sum(1 for s in required if s.lower() in critical_required)
    total_required_regular = max(0, len(required) - total_required_critical)

    if required:
        critical_ratio = (
            len(matched_required_critical) / total_required_critical if total_required_critical > 0 else 1.0
        )
        regular_ratio = (
            len(matched_required_regular) / total_required_regular if total_required_regular > 0 else 1.0
        )
        required_score = ((critical_ratio * 0.70) + (regular_ratio * 0.30)) * 100.0
    else:
        required_score = 100.0

    preferred_score = (len(matched_preferred) / len(preferred) * 100.0) if preferred else 100.0

    final = (required_score * 0.75) + (preferred_score * 0.25)

    if missing_required:
        critical_missing = sum(1 for s in missing_required if s.lower() in critical_required)
        regular_missing = max(0, len(missing_required) - critical_missing)
        penalty = (critical_missing * 12.0) + (regular_missing * 6.0)
        final -= min(35.0, penalty)

    return _clamp_0_100(final), matched_required + matched_preferred, missing_required


def _experience_years_score(min_years: float | None, resume_years: float | None) -> float:
    if min_years is None:
        return 100.0
    if resume_years is None or min_years <= 0:
        return 0.0

    ratio = resume_years / min_years
    if ratio >= 1.35:
        return 100.0
    if ratio >= 1.0:
        return _clamp_0_100(92.0 + ((ratio - 1.0) / 0.35) * 8.0)
    if ratio >= 0.8:
        return _clamp_0_100(75.0 + ((ratio - 0.8) / 0.2) * 17.0)
    if ratio >= 0.6:
        return _clamp_0_100(45.0 + ((ratio - 0.6) / 0.2) * 30.0)
    return _clamp_0_100(ratio * 60.0)


def _parse_ym_date(raw: object) -> datetime | None:
    text = str(raw or "").strip().lower()
    if not text:
        return None
    if text in {"present", "current", "now", "till now", "till date", "to date"}:
        return datetime.now(UTC)

    for fmt in ("%Y-%m", "%Y/%m", "%Y"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.replace(tzinfo=UTC)
        except ValueError:
            continue

    return None


def _entry_recency_weight(end_date: object) -> float:
    end_dt = _parse_ym_date(end_date)
    if not end_dt:
        return 0.75
    months_ago = max(
        0.0,
        (datetime.now(UTC).year - end_dt.year) * 12 + (datetime.now(UTC).month - end_dt.month),
    )
    if months_ago <= 24:
        return 1.0
    if months_ago <= 60:
        return 0.85
    return 0.70


def _experience_relevance_score(job: Job, parsed_json: dict[str, Any]) -> float:
    entries = parsed_json.get("experience_entries", [])
    if not isinstance(entries, list) or not entries:
        return 0.0

    required = [str(skill).lower() for skill in (job.required_skills or []) if skill]
    if not required:
        return 100.0

    preferred = [str(skill).lower() for skill in (job.nice_to_have_skills or []) if skill]
    title_keywords = [
        token
        for token in re.findall(r"[a-zA-Z][a-zA-Z0-9+.#-]{2,}", str(job.title or "").lower())
        if token not in {"senior", "lead", "manager", "engineer", "developer", "analyst", "specialist"}
    ]

    weighted_hits = 0.0
    total_weight = 0.0

    for entry in entries[:4]:
        if not isinstance(entry, dict):
            continue
        title = str(entry.get("title") or "").lower()
        desc = str(entry.get("description") or "").lower()
        skills_used = _normalize_skill_names([str(s) for s in (entry.get("skills_used") or []) if s])
        recency_weight = _entry_recency_weight(entry.get("end_date"))

        entry_score = 0.0
        for req in required:
            req_norm = _normalize_skill_names([req])[0] if _normalize_skill_names([req]) else req
            if req in title or req in desc or any(_skills_match(req_norm, s) for s in skills_used):
                entry_score += 1.0

        for pref in preferred:
            pref_norm = _normalize_skill_names([pref])[0] if _normalize_skill_names([pref]) else pref
            if pref in title or pref in desc or any(_skills_match(pref_norm, s) for s in skills_used):
                entry_score += 0.4

        if title_keywords:
            title_hits = sum(1 for token in title_keywords if token in title or token in desc)
            entry_score += min(1.0, title_hits / max(1, len(title_keywords)))

        weighted_hits += entry_score * recency_weight
        total_weight += (len(required) + (len(preferred) * 0.4) + 1.0) * recency_weight

    if total_weight <= 0:
        return 0.0

    return _clamp_0_100((weighted_hits / total_weight) * 100.0)


def _seniority_score(job: Job, parsed_json: dict[str, Any]) -> float:
    desired = _infer_job_seniority(job)
    actual = str(parsed_json.get("seniority_level") or "").lower().strip()

    if not desired:
        return 50.0
    if not actual:
        return 50.0
    if desired == actual:
        return 100.0

    order = {
        "junior/associate": 1,
        "mid": 2,
        "senior": 3,
        "lead/manager": 4,
        "principal+": 5,
    }

    if desired in order and actual in order:
        diff = abs(order[desired] - order[actual])
        return _clamp_0_100(100 - (diff * 25))

    return 60.0


def _experience_score(job: Job, resume: Resume, parsed_json: dict[str, Any]) -> float:
    years_score = _experience_years_score(
        float(job.min_experience_years) if job.min_experience_years is not None else None,
        float(resume.experience_years) if resume.experience_years is not None else None,
    )
    relevance_score = _experience_relevance_score(job, parsed_json)
    seniority_score = _seniority_score(job, parsed_json)

    return _clamp_0_100((years_score * 0.45) + (relevance_score * 0.40) + (seniority_score * 0.15))


def _domain_score(job: Job, parsed_json: dict[str, Any], resume_text: str) -> float:
    job_domains = [str(tag).lower() for tag in (job.domain_tags or []) if tag]
    if not job_domains:
        return 100.0

    candidate_domain = str(parsed_json.get("primary_domain") or "").lower().strip()
    if candidate_domain and any(tag in candidate_domain or candidate_domain in tag for tag in job_domains):
        return 100.0

    text = resume_text.lower()
    matches = sum(1 for tag in job_domains if tag in text)
    return _clamp_0_100((matches / len(job_domains)) * 100.0)


SOFT_SKILL_KEYWORDS: dict[str, set[str]] = {
    "communication": {"communication", "communicate", "presentation", "stakeholder", "interpersonal"},
    "collaboration": {"collaboration", "collaborate", "cross functional", "teamwork", "partnered"},
    "leadership": {"leadership", "led", "mentored", "coached", "ownership"},
    "problem_solving": {"problem solving", "troubleshooting", "analytical", "critical thinking"},
    "planning_execution": {"planning", "coordination", "organized", "prioritization", "execution"},
}

MANAGERIAL_KEYWORDS: set[str] = {
    "manager",
    "management",
    "lead",
    "team lead",
    "people management",
    "hiring",
    "mentoring",
    "coaching",
    "stakeholder management",
    "roadmap",
    "delivery ownership",
    "performance management",
    "budget",
    "resource planning",
    "program management",
    "project management",
}


def _build_job_requirement_text(job: Job) -> str:
    return " ".join(
        [
            str(job.title or ""),
            str(job.description or ""),
            " ".join(str(skill) for skill in (job.required_skills or []) if skill),
            " ".join(str(skill) for skill in (job.nice_to_have_skills or []) if skill),
        ]
    ).lower()


def _build_candidate_signal_text(candidate_features: dict[str, Any]) -> str:
    parsed_json = candidate_features.get("parsed_json", {})
    experience_entries = parsed_json.get("experience_entries", []) if isinstance(parsed_json, dict) else []

    chunks: list[str] = []
    chunks.extend(str(title) for title in candidate_features.get("titles", [])[:8])
    chunks.extend(str(desc) for desc in candidate_features.get("descriptions", [])[:8])
    chunks.extend(str(skill) for skill in candidate_features.get("skills", [])[:30])
    chunks.append(str(candidate_features.get("raw_text") or "")[:4000])
    if isinstance(experience_entries, list):
        for entry in experience_entries[:4]:
            if not isinstance(entry, dict):
                continue
            chunks.append(str(entry.get("title") or ""))
            chunks.append(str(entry.get("description") or ""))

    return " ".join(chunks).lower()


def _keyword_hit_count(text: str, keywords: set[str]) -> int:
    lowered = text.lower()
    return sum(1 for key in keywords if key in lowered)


def _soft_skill_score(job: Job, candidate_features: dict[str, Any]) -> float:
    job_text = _build_job_requirement_text(job)
    candidate_text = _build_candidate_signal_text(candidate_features)

    expected_groups = [
        group for group, terms in SOFT_SKILL_KEYWORDS.items() if any(term in job_text for term in terms)
    ]

    if not expected_groups:
        baseline_hits = sum(
            1
            for terms in SOFT_SKILL_KEYWORDS.values()
            if _keyword_hit_count(candidate_text, terms) > 0
        )
        return _clamp_0_100(50.0 + (baseline_hits * 10.0))

    matched_groups = sum(
        1
        for group in expected_groups
        if _keyword_hit_count(candidate_text, SOFT_SKILL_KEYWORDS[group]) > 0
    )
    ratio = matched_groups / max(1, len(expected_groups))
    score = (ratio * 100.0)

    missing = len(expected_groups) - matched_groups
    if missing > 0:
        score -= min(20.0, missing * 8.0)
    return _clamp_0_100(score)


def _managerial_skill_score(job: Job, candidate_features: dict[str, Any], parsed_json: dict[str, Any]) -> float:
    job_text = _build_job_requirement_text(job)
    candidate_text = _build_candidate_signal_text(candidate_features)
    desired_seniority = _infer_job_seniority(job)
    candidate_seniority = str(parsed_json.get("seniority_level") or "").lower().strip()

    expects_managerial = (
        desired_seniority in {"lead/manager", "principal+"}
        or any(keyword in job_text for keyword in MANAGERIAL_KEYWORDS)
    )

    managerial_hits = _keyword_hit_count(candidate_text, MANAGERIAL_KEYWORDS)
    title_hits = sum(
        1
        for title in candidate_features.get("titles", [])[:6]
        if any(tag in str(title).lower() for tag in {"lead", "manager", "head", "director"})
    )

    base = min(100.0, (managerial_hits * 10.0) + (title_hits * 20.0))
    if not expects_managerial:
        return _clamp_0_100(max(60.0, base))

    seniority_bonus = 0.0
    if candidate_seniority in {"lead/manager", "principal+"}:
        seniority_bonus = 12.0
    elif candidate_seniority == "senior":
        seniority_bonus = 6.0

    score = base + seniority_bonus
    if managerial_hits == 0 and title_hits == 0:
        score = max(20.0, score - 20.0)

    return _clamp_0_100(score)


def _distance_priority_bonus(job: Job, parsed_json: dict[str, Any], resume: Resume) -> float:
    work_mode = str(getattr(job, "work_mode", "remote") or "remote").lower().strip()
    willing_to_relocate = parsed_json.get("willing_to_relocate")
    willing: bool | None = willing_to_relocate if isinstance(willing_to_relocate, bool) else None

    distance_value = parsed_json.get("distance_miles")
    distance_miles: float | None = float(distance_value) if isinstance(distance_value, (int, float)) else None

    if distance_miles is None:
        job_location = _resolve_job_location(job)
        candidate_location = _resolve_candidate_location_for_ranking(parsed_json, resume)
        computed = distance_miles_between(job_location, candidate_location)
        if computed is not None:
            distance_miles = float(computed)

    if work_mode == "remote":
        if distance_miles is not None and distance_miles > 200 and willing is False:
            return -3.0
        return 0.0

    # For hybrid/in-person, prioritize either nearby candidates (<=50 miles)
    # or candidates explicitly willing to relocate.
    if distance_miles is None:
        if willing is True:
            return 7.0 if work_mode == "inperson" else 6.0
        if willing is False:
            return -8.0 if work_mode == "inperson" else -6.0
        return -4.0 if work_mode == "inperson" else -3.0

    if distance_miles <= 10:
        return 12.0
    if distance_miles <= 25:
        return 10.0
    if distance_miles <= 50:
        return 8.0

    if willing is True:
        if distance_miles <= 150:
            return 7.0 if work_mode == "inperson" else 6.0
        return 5.0 if work_mode == "inperson" else 4.0

    if willing is False:
        if distance_miles <= 100:
            return -6.0 if work_mode == "inperson" else -5.0
        if distance_miles <= 200:
            return -10.0 if work_mode == "inperson" else -8.0
        return -15.0 if work_mode == "inperson" else -12.0

    if distance_miles <= 100:
        return 1.0
    if distance_miles <= 200:
        return -3.0
    return -8.0 if work_mode == "inperson" else -6.0


def _confidence_score(
    parsed_json: dict[str, Any],
    resume_text: str,
    candidate_features: dict[str, Any],
    *,
    semantic: float,
    skill: float,
    experience: float,
    domain: float,
    soft_skill: float | None = None,
    managerial_skill: float | None = None,
) -> float:
    score = 20.0
    if resume_text.strip():
        score += 10.0
    if candidate_features.get("skills"):
        score += 10.0
    if candidate_features.get("titles"):
        score += 10.0
    if parsed_json.get("experience_entries"):
        score += 10.0
    if parsed_json.get("education"):
        score += 8.0
    if parsed_json.get("current_last_job"):
        score += 4.0
    if parsed_json.get("primary_domain"):
        score += 4.0

    signals = [semantic, skill, experience, domain]
    if soft_skill is not None:
        signals.append(soft_skill)
    if managerial_skill is not None:
        signals.append(managerial_skill)
    spread = max(signals) - min(signals)
    if spread <= 15:
        score += 18.0
    elif spread <= 30:
        score += 10.0
    elif spread <= 45:
        score += 5.0
    else:
        score -= 8.0

    if skill < 35 and experience < 35:
        score -= 8.0
    if semantic < 30 and domain < 30:
        score -= 6.0

    return _clamp_0_100(score)


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
    parsed_json = resume.parsed_json if isinstance(resume.parsed_json, dict) else {}
    candidate = _extract_candidate_features(resume)

    skill, matched_skills, missing_skills = _skill_score(job, candidate["skills"])
    experience = _experience_score(job, resume, parsed_json)
    domain = _domain_score(job, parsed_json, candidate["raw_text"])
    soft_skill = _soft_skill_score(job, candidate)
    managerial_skill = _managerial_skill_score(job, candidate, parsed_json)
    distance_bonus = _distance_priority_bonus(job, parsed_json, resume)

    final = _clamp_0_100(
        (semantic * 0.14) +
        (skill * 0.32) +
        (experience * 0.27) +
        (domain * 0.17) +
        (soft_skill * 0.05) +
        (managerial_skill * 0.05)
    )
    final = _clamp_0_100(final + distance_bonus)

    confidence = _confidence_score(
        parsed_json,
        candidate["raw_text"],
        candidate,
        semantic=semantic,
        skill=skill,
        experience=experience,
        domain=domain,
        soft_skill=soft_skill,
        managerial_skill=managerial_skill,
    )

    reasons: list[str] = []
    if matched_skills:
        reasons.append(f"Matched skills: {', '.join(matched_skills[:4])}")
    if resume.experience_years is not None:
        reasons.append(f"{float(resume.experience_years):.1f}+ years relevant experience")
    if parsed_json.get("primary_domain"):
        reasons.append(f"Primary domain: {parsed_json.get('primary_domain')}")
    elif domain >= 50:
        reasons.append("Relevant domain overlap found")
    if managerial_skill >= 70:
        reasons.append("Demonstrated leadership/managerial indicators")
    elif soft_skill >= 70:
        reasons.append("Strong soft-skill signals in experience")
    if distance_bonus >= 8:
        reasons.append("Strong location proximity for role mode")
    elif distance_bonus <= -8:
        reasons.append("Distance may impact on-site/hybrid suitability")

    if not reasons:
        reasons = ["Resume parsed with limited matching signals"]

    return RankingComputation(
        semantic=semantic,
        skill=skill,
        experience=experience,
        domain=domain,
        soft_skill=soft_skill,
        managerial_skill=managerial_skill,
        distance_priority_bonus=distance_bonus,
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
            "work_mode": getattr(job, "work_mode", "remote") or "remote",
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

    pending_rows: list[tuple[Resume, RankingComputation, dict[str, Any]]] = []
    job_embedding_vector: list[float] | None = None
    job_semantic_vector: list[float] | None = None
    try:
        job_embedding_vector = get_or_create_job_embedding(db, job).embedding
    except Exception:
        job_embedding_vector = None
    if ENABLE_SECTION_SEMANTIC:
        try:
            job_semantic_vector = embed_text(_build_job_semantic_text(job))
        except Exception:
            job_semantic_vector = None

    for resume in resumes:
        resume_sig = _resume_signature(resume)
        existing = existing_by_resume_id.get(resume.id)
        if _ranking_is_fresh(existing, expected_job_sig=job_sig, expected_resume_sig=resume_sig):
            continue

        candidate_features = _extract_candidate_features(resume)
        semantic_source = "token_overlap_fallback"
        semantic = _semantic_score_fallback(job.description or "", resume.raw_text or "")
        semantic_components: dict[str, float] = {"full_text": semantic}
        if job_embedding_vector:
            try:
                resume_embedding = get_or_create_resume_embedding(db, resume)
                semantic = cosine_similarity_percent(job_embedding_vector, resume_embedding.embedding)
                semantic_source = "embedding_cosine"
                semantic_components = {"full_text": _clamp_0_100(semantic)}

                if ENABLE_SECTION_SEMANTIC:
                    resume_sections = _build_resume_semantic_sections(
                        candidate_features,
                        resume.raw_text or "",
                    )
                    weighted_semantic, components = _weighted_section_semantic(
                        job_semantic_vector or job_embedding_vector,
                        resume_sections,
                        semantic,
                    )
                    semantic = weighted_semantic
                    semantic_components = components
                    semantic_source = "embedding_weighted_sections"
            except Exception:
                semantic = _semantic_score_fallback(job.description or "", resume.raw_text or "")
                semantic_source = "token_overlap_fallback"
                semantic_components = {"full_text": semantic}

        result = compute_ranking(job, resume, semantic)
        parsed_json = resume.parsed_json if isinstance(resume.parsed_json, dict) else {}
        evidence_snippets = []

        if parsed_json.get("current_last_job"):
            evidence_snippets.append(
                {"label": "Current title", "text": str(parsed_json.get("current_last_job"))[:320]}
            )
        if parsed_json.get("primary_domain"):
            evidence_snippets.append(
                {"label": "Primary domain", "text": str(parsed_json.get("primary_domain"))[:320]}
            )
        if parsed_json.get("skills"):
            evidence_snippets.append(
                {"label": "Top skills", "text": ", ".join(str(s) for s in parsed_json.get("skills", [])[:8])[:320]}
            )
        if not evidence_snippets:
            evidence_snippets = [{"label": "Resume excerpt", "text": (resume.raw_text or "")[:320]}]

        explanation_json: dict[str, Any] = {
            "score_breakdown": {
                "semantic": result.semantic,
                "skill": result.skill,
                "experience": result.experience,
                "domain": result.domain,
                "soft_skill": result.soft_skill,
                "managerial_skill": result.managerial_skill,
                "distance_priority_bonus": result.distance_priority_bonus,
            },
            "semantic_source": semantic_source,
            "semantic_components": semantic_components,
            "base_score": result.final,
            "base_confidence": result.confidence,
            "matched_skills": result.matched_skills,
            "missing_skills": result.missing_skills,
            "evidence_snippets": evidence_snippets,
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
                "soft_skill": result.soft_skill,
                "managerial_skill": result.managerial_skill,
                "distance_priority_bonus": result.distance_priority_bonus,
            }

        matched = llm_output.get("matched_skills")
        if isinstance(matched, list):
            merged_matched: list[str] = []
            seen_matched: set[str] = set()
            for item in [*result.matched_skills, *[str(v) for v in matched]]:
                value = str(item).strip()
                if not value:
                    continue
                key = value.lower()
                if key in seen_matched:
                    continue
                seen_matched.add(key)
                merged_matched.append(value)

            result.matched_skills = merged_matched[:8]
            explanation_json["matched_skills"] = result.matched_skills

        summary = llm_output.get("summary")
        strengths = llm_output.get("strengths")
        missing = llm_output.get("missing_skills")
        confidence_reasoning = llm_output.get("confidence_reasoning")
        top_reasons = llm_output.get("top_reasons")
        rubric_scores = llm_output.get("rubric_scores")
        evidence_snippets = llm_output.get("evidence_snippets")

        if isinstance(summary, str) and summary.strip():
            explanation_json["summary"] = summary.strip()
        if isinstance(strengths, list):
            explanation_json["strengths"] = [str(item) for item in strengths][:5]
        if isinstance(missing, list):
            merged_missing: list[str] = []
            seen_missing: set[str] = set()
            matched_keys = {str(item).strip().lower() for item in result.matched_skills}
            for item in [*result.missing_skills, *[str(v) for v in missing]]:
                value = str(item).strip()
                if not value:
                    continue
                key = value.lower()
                if key in matched_keys or key in seen_missing:
                    continue
                seen_missing.add(key)
                merged_missing.append(value)

            result.missing_skills = merged_missing[:8]
            explanation_json["missing_skills"] = result.missing_skills
        if isinstance(confidence_reasoning, str):
            explanation_json["confidence_reasoning"] = confidence_reasoning.strip()
        if isinstance(top_reasons, list):
            explanation_json["top_reasons"] = [str(item) for item in top_reasons][:3]
        if isinstance(rubric_scores, dict):
            explanation_json["rubric_scores"] = rubric_scores
        if isinstance(evidence_snippets, list):
            normalized_evidence: list[dict[str, str]] = []
            for item in evidence_snippets:
                if not isinstance(item, dict):
                    continue
                label = item.get("label")
                text = item.get("text")
                if isinstance(label, str) and isinstance(text, str) and label.strip() and text.strip():
                    normalized_evidence.append(
                        {"label": label.strip()[:120], "text": text.strip()[:320]}
                    )
            if normalized_evidence:
                explanation_json["evidence_snippets"] = normalized_evidence[:5]

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
        resume_skills = _normalize_skill_names(
            [str(item) for item in (resume.skills_json if isinstance(resume.skills_json, list) else [])]
        )
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

        candidate_location = _resolve_candidate_location(parsed_json, candidate, resume)
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
        willing_to_relocate = parsed_json.get("willing_to_relocate")
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
                "primary_domain": parsed_json.get("primary_domain"),
                "score": score,
                "confidence": float(ranking.confidence),
                "experience_years": experience_years,
                "highest_degree": degree if isinstance(degree, str) else None,
                "distance_miles": float(resume_distance) if isinstance(resume_distance, (float, int)) else None,
                "sponsorship_required": sponsorship if isinstance(sponsorship, bool) else None,
                "willing_to_relocate": willing_to_relocate if isinstance(willing_to_relocate, bool) else None,
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
        "rubric_scores": payload.get("rubric_scores", {}),
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
        "top_reasons": payload.get("top_reasons", []),
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


def _get_current_interview_task(
    db: Session,
    *,
    job_id: uuid.UUID,
    candidate_id: uuid.UUID,
) -> dict:
    current = next(
        (item for item in list_interview_tasks(db, job_id=job_id) if item["candidate_id"] == str(candidate_id)),
        None,
    )
    if current:
        return current
    return ensure_interview_task_for_candidate(
        db,
        job_id=job_id,
        candidate_id=candidate_id,
        created_by=None,
    )


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

    current = _get_current_interview_task(db, job_id=job_id, candidate_id=candidate_id)

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


def set_interview_task_status(
    db: Session,
    *,
    job_id: uuid.UUID,
    candidate_id: uuid.UUID,
    status: str,
    notes: str | None,
    created_by: uuid.UUID | None = None,
) -> dict:
    normalized = status.strip().lower()
    if normalized not in INTERVIEW_TASK_STATUSES:
        raise ValueError("Invalid task status")

    current = _get_current_interview_task(db, job_id=job_id, candidate_id=candidate_id)
    payload = {
        "task_id": str(current.get("task_id")),
        "candidate_id": str(candidate_id),
        "status": normalized,
        "title": current.get("title") or "Schedule interview",
        "interviewer": current.get("interviewer"),
        "notes": notes.strip() if notes and notes.strip() else current.get("notes"),
        "meeting_provider": current.get("meeting_provider") or "google_meet",
        "meeting_link": current.get("meeting_link"),
        "google_calendar_url": current.get("google_calendar_url"),
        "scheduled_start_at": current.get("scheduled_start_at"),
        "scheduled_end_at": current.get("scheduled_end_at"),
        "timezone": current.get("timezone") or "UTC",
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

    candidate_row = db.get(Candidate, candidate_id)
    candidate_name = candidate_row.full_name if candidate_row and candidate_row.full_name else "Candidate"
    return {
        **payload,
        "candidate_name": candidate_name,
        "candidate_email": candidate_row.primary_email if candidate_row else None,
        "created_at": current.get("created_at"),
        "updated_at": datetime.now(UTC).isoformat(),
    }
