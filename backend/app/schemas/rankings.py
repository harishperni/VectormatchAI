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
    experience_years: float | None = None
    highest_degree: str | None = None
    distance_miles: float | None = None
    sponsorship_required: bool | None = None
    top_reasons: list[str]
    action_status: str | None = None
    audit_flags: list[str] = Field(default_factory=list)
    audit_summary: str | None = None
    audit_detail: list[str] = Field(default_factory=list)
    anti_cheat_score: float = 0.0


class RankingListResponse(BaseModel):
    job_id: str
    count: int
    items: list[RankingRow]


class ExplanationResponse(BaseModel):
    score_breakdown: dict[str, float]
    rubric_scores: dict[str, float] = Field(default_factory=dict)
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
    top_reasons: list[str] = Field(default_factory=list)
    anti_cheat_score: float = 0.0
    anti_cheat_flags: list[str] = Field(default_factory=list)
    anti_cheat_breakdown: list[dict[str, object]] = Field(default_factory=list)


class CandidateActionRequest(BaseModel):
    action: str
    notes: str | None = None


class CandidateBulkActionRequest(BaseModel):
    candidate_ids: list[str] = Field(default_factory=list)
    action: str
    notes: str | None = None


class RankingDiffRow(BaseModel):
    candidate_id: str
    candidate_name: str
    current_rank: int
    previous_rank: int | None = None
    score_delta: float | None = None
    top_reasons: list[str] = Field(default_factory=list)


class EvaluationResponse(BaseModel):
    job_id: str
    top_k: int
    current_count: int
    precision_at_k: float | None = None
    recall_at_k: float | None = None
    expected_total: int = 0
    matched_expected: int = 0
    expected_reference: str | None = None
    score_summary: dict[str, float]
    run_diff: list[RankingDiffRow] = Field(default_factory=list)


class GoldenDatasetPayload(BaseModel):
    expected_top_candidate_ids: list[str] = Field(default_factory=list)
    expected_top_candidate_names: list[str] = Field(default_factory=list)


class GoldenDatasetResponse(BaseModel):
    job_id: str
    expected_top_candidate_ids: list[str] = Field(default_factory=list)
    expected_top_candidate_names: list[str] = Field(default_factory=list)


class InterviewTaskRow(BaseModel):
    task_id: str
    candidate_id: str
    candidate_name: str
    candidate_email: str | None = None
    status: str
    title: str
    interviewer: str | None = None
    notes: str | None = None
    meeting_provider: str
    meeting_link: str | None = None
    google_calendar_url: str | None = None
    scheduled_start_at: str | None = None
    scheduled_end_at: str | None = None
    timezone: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class InterviewTaskListResponse(BaseModel):
    job_id: str
    count: int
    items: list[InterviewTaskRow] = Field(default_factory=list)


class InterviewTaskScheduleRequest(BaseModel):
    starts_at: str
    ends_at: str
    interviewer: str | None = None
    notes: str | None = None
    timezone: str | None = None
    meeting_link: str | None = None


class InterviewTaskStatusRequest(BaseModel):
    action: str
    notes: str | None = None
