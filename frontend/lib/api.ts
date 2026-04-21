export type Job = {
  id: string;
  title: string;
  description: string;
  location?: string | null;
  work_mode: "remote" | "hybrid" | "inperson";
  min_experience_years: number | null;
  job_hopper_short_tenure_months: number;
  job_hopper_min_short_stints: number;
  required_skills: string[];
  nice_to_have_skills: string[];
  domain_tags: string[];
};

export type RankingRow = {
  candidate_id: string;
  resume_id: string;
  candidate_name: string;
  candidate_type?: string | null;
  applied_at?: string | null;
  stage?: string | null;
  step?: string | null;
  current_last_job?: string | null;
  score: number;
  confidence: number;
  experience_years: number | null;
  highest_degree?: string | null;
  distance_miles?: number | null;
  sponsorship_required?: boolean | null;
  willing_to_relocate?: boolean | null;
  top_reasons: string[];
  action_status?: string | null;
  audit_flags?: string[];
  audit_summary?: string | null;
  audit_detail?: string[];
  knockout_status?: "qualified" | "disqualified" | string;
  knockout_reasons?: string[];
  anti_cheat_score?: number;
};

export type EvaluationDiffRow = {
  candidate_id: string;
  candidate_name: string;
  current_rank: number;
  previous_rank: number | null;
  score_delta: number | null;
  top_reasons: string[];
};

export type JobEvaluation = {
  job_id: string;
  top_k: number;
  current_count: number;
  precision_at_k: number | null;
  recall_at_k: number | null;
  expected_total: number;
  matched_expected: number;
  expected_reference: string | null;
  score_summary: {
    average_score: number;
    average_confidence: number;
  };
  run_diff: EvaluationDiffRow[];
};

export type ParsedResumeRow = {
  job_resume_id: string;
  candidate_id: string;
  resume_id: string;
  candidate_name: string;
  email: string | null;
  source_filename: string | null;
  parse_status: "pending" | "parsed" | "failed";
  experience_years: number | null;
  skills: string[];
  parse_error: string | null;
  parsed_json?: Record<string, unknown>;
  raw_text_preview?: string | null;
  uploaded_at: string | null;
};

type RankingListResponse = {
  job_id: string;
  count: number;
  items: RankingRow[];
};

type JobResumesResponse = {
  job_id: string;
  count: number;
  items: ParsedResumeRow[];
};

export type ExplanationSnippet = {
  label: string;
  text: string;
};

export type CandidateExplanation = {
  score_breakdown: Record<string, number>;
  rubric_scores?: {
    semantic_fit?: number;
    skill_fit?: number;
    experience_fit?: number;
    domain_fit?: number;
  };
  matched_skills: string[];
  missing_skills: string[];
  knockout_evaluation?: {
    overall_pass?: boolean;
    auto_reject?: boolean;
    failed_reasons?: string[];
    answers?: Array<{
      id?: string;
      question?: string;
      pass?: boolean;
      value?: string;
      assumed?: boolean;
    }>;
  };
  evidence_snippets: ExplanationSnippet[];
  summary: string;
  model_version: string;
  scoring_version: string;
  base_score?: number | null;
  llm_score?: number | null;
  final_score?: number | null;
  base_confidence?: number | null;
  llm_confidence?: number | null;
  final_confidence?: number | null;
  llm_used?: boolean;
  confidence_reasoning?: string | null;
  strengths?: string[];
  top_reasons?: string[];
  anti_cheat_score?: number;
  anti_cheat_flags?: string[];
  anti_cheat_breakdown?: Array<{
    rule?: string;
    points?: number;
    evidence?: string;
  }>;
};

export type InterviewTask = {
  task_id: string;
  candidate_id: string;
  candidate_name: string;
  candidate_email?: string | null;
  status: string;
  title: string;
  interviewer?: string | null;
  notes?: string | null;
  meeting_provider: string;
  meeting_link?: string | null;
  google_calendar_url?: string | null;
  scheduled_start_at?: string | null;
  scheduled_end_at?: string | null;
  timezone?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

export async function fetchJobs(): Promise<Job[]> {
  const response = await fetch(`${API_BASE}/api/v1/jobs`, {
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`Failed to fetch jobs: ${response.status}`);
  }
  return response.json();
}

export async function fetchJob(jobId: string): Promise<Job | null> {
  const response = await fetch(`${API_BASE}/api/v1/jobs/${jobId}`, {
    cache: "no-store",
  });
  if (response.status === 404) {
    return null;
  }
  if (!response.ok) {
    throw new Error(`Failed to fetch job ${jobId}: ${response.status}`);
  }
  return response.json();
}

export async function fetchRankings(
  jobId: string,
  filters?: {
    min_score?: number;
    min_experience?: number;
    skill?: string;
    action?: string;
    keyword?: string;
    status?: string;
    highest_degree?: string;
    distance_max?: number;
    sponsorship_required?: boolean;
    total_experience_min?: number;
    knockout_status?: string;
  }
): Promise<RankingRow[]> {
  const params = new URLSearchParams();
  if (filters?.min_score !== undefined) params.set("min_score", String(filters.min_score));
  if (filters?.min_experience !== undefined) {
    params.set("min_experience", String(filters.min_experience));
  }
  if (filters?.skill) params.set("skill", filters.skill);
  if (filters?.action) params.set("action", filters.action);
  if (filters?.keyword) params.set("keyword", filters.keyword);
  if (filters?.status) params.set("status", filters.status);
  if (filters?.highest_degree) params.set("highest_degree", filters.highest_degree);
  if (filters?.distance_max !== undefined) params.set("distance_max", String(filters.distance_max));
  if (filters?.sponsorship_required !== undefined) {
    params.set("sponsorship_required", String(filters.sponsorship_required));
  }
  if (filters?.total_experience_min !== undefined) {
    params.set("total_experience_min", String(filters.total_experience_min));
  }
  if (filters?.knockout_status) {
    params.set("knockout_status", filters.knockout_status);
  }

  const response = await fetch(
    `${API_BASE}/api/v1/jobs/${jobId}/rankings${params.toString() ? `?${params.toString()}` : ""}`,
    {
    cache: "no-store",
    }
  );
  if (response.status === 404) {
    return [];
  }
  if (!response.ok) {
    throw new Error(`Failed to fetch rankings for job ${jobId}: ${response.status}`);
  }

  const payload = (await response.json()) as RankingListResponse;
  return payload.items;
}

export async function fetchCandidateExplanation(
  jobId: string,
  candidateId: string
): Promise<CandidateExplanation | null> {
  const response = await fetch(
    `${API_BASE}/api/v1/jobs/${jobId}/candidates/${candidateId}/explanation`,
    {
      cache: "no-store",
    }
  );
  if (response.status === 404) {
    return null;
  }
  if (!response.ok) {
    throw new Error(
      `Failed to fetch candidate explanation for job ${jobId}, candidate ${candidateId}: ${response.status}`
    );
  }
  return response.json();
}

export async function fetchJobResumes(jobId: string): Promise<ParsedResumeRow[]> {
  const response = await fetch(`${API_BASE}/api/v1/jobs/${jobId}/resumes`, {
    cache: "no-store",
  });
  if (response.status === 404) {
    return [];
  }
  if (!response.ok) {
    throw new Error(`Failed to fetch resumes for job ${jobId}: ${response.status}`);
  }

  const payload = (await response.json()) as JobResumesResponse;
  return payload.items;
}

export async function fetchJobEvaluation(jobId: string, topK = 5): Promise<JobEvaluation | null> {
  const response = await fetch(`${API_BASE}/api/v1/jobs/${jobId}/evaluation?top_k=${topK}`, {
    cache: "no-store",
  });
  if (response.status === 404) {
    return null;
  }
  if (!response.ok) {
    throw new Error(`Failed to fetch evaluation for job ${jobId}: ${response.status}`);
  }
  return response.json();
}
