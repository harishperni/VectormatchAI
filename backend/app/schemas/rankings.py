from pydantic import BaseModel, Field


class RankingRow(BaseModel):
    candidate_id: str
    resume_id: str
    candidate_name: str
    candidate_type: str | None = None
    applied_at: str | None = None
    stage: str | None = None
    step: str | None = None
    current_last_job: str | None = None
    score: float
    confidence: float
    experience_years: float
    highest_degree: str | None = None
    distance_miles: float | None = None
    sponsorship_required: bool | None = None
    top_reasons: list[str]
    action_status: str | None = None


class RankingListResponse(BaseModel):
    job_id: str
    count: int
    items: list[RankingRow]


class ExplanationResponse(BaseModel):
    score_breakdown: dict[str, float]
    matched_skills: list[str]
    missing_skills: list[str]
    evidence_snippets: list[dict[str, str]]
    summary: str
    model_version: str
    scoring_version: str
    base_score: float | None = None
    llm_score: float | None = None
    final_score: float | None = None
    base_confidence: float | None = None
    llm_confidence: float | None = None
    final_confidence: float | None = None
    llm_used: bool = False
    confidence_reasoning: str | None = None
    strengths: list[str] = Field(default_factory=list)


class CandidateActionRequest(BaseModel):
    action: str
    notes: str | None = None
