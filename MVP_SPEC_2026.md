# ATS AI Talent Intelligence - MVP Spec (2026)

## 1) Product Positioning

**Category**: Explainable AI Talent Intelligence Platform  
**Primary user**: Recruiter / Hiring manager  
**Core promise**: Faster, more accurate candidate discovery with transparent, auditable ranking.

## 2) MVP Goals (Phase 1)

1. Create jobs and define hiring criteria.
2. Upload resumes (PDF/DOCX) and auto-parse candidate profiles.
3. Rank candidates using hybrid relevance scoring.
4. Show explainable score breakdown with resume evidence.
5. Filter/search candidates and shortlist quickly.
6. Keep architecture low-cost (local-first, open-source-first).

Success targets (MVP):
- Time-to-shortlist reduced by >= 50% vs manual screening.
- Top-10 precision improves vs keyword-only baseline.
- 100% of ranked candidates have human-readable reason + evidence snippet.

## 3) Finalized MVP Feature Scope

### In scope
- Auth (recruiter login)
- Job CRUD
- Resume upload + parsing pipeline
- Candidate normalization + deduplication
- Embeddings + pgvector indexing
- Hybrid retrieval (semantic + keyword)
- Rule scoring (skills, experience, domain)
- Explainable ranking UI
- Filters + shortlist states
- Audit log (score version + explanation trace)

### Out of scope (post-MVP)
- Calendar integrations (Google/Outlook)
- Email ingestion workflows
- Full interview scheduling
- Multi-tenant enterprise SSO/SCIM
- Automated outreach campaigns

## 4) Tech Stack (Cost-Optimized)

### Frontend
- Next.js 15+ (App Router)
- Tailwind CSS
- shadcn/ui
- TanStack Table for ranking table

### Backend
- FastAPI
- Celery or Dramatiq for async jobs
- Redis (queue + cache)

### AI / NLP
- Parsing: PyMuPDF primary, DOCX parser, OCR fallback via unstructured
- Embeddings: sentence-transformers `all-MiniLM-L6-v2`
- Reranker (optional in MVP, recommended): `cross-encoder/ms-marco-MiniLM-L-6-v2`
- Reasoning LLM: Ollama (Mistral/Llama) with strict JSON output schema

### Data
- PostgreSQL 16 + pgvector
- S3-compatible storage (MinIO local for dev)

## 5) System Architecture (MVP)

1. Recruiter creates job.
2. Recruiter uploads resumes.
3. Async pipeline runs:
   - extract text
   - parse entities (name, email, skills, titles, companies, years)
   - store normalized profile
   - generate embeddings
4. On ranking request:
   - hybrid retrieve candidate set
   - compute weighted score
   - rerank top N (optional)
   - generate explanation for top K
5. UI shows ranked candidates + evidence + filters.

## 6) Scoring Design (Final)

### 6.1 Hard gates (applied first)
- Missing mandatory legal/work criteria -> candidate excluded.
- Missing all must-have skills -> either exclude or major penalty (configurable by recruiter).
- Experience below absolute minimum threshold -> exclude (configurable).

### 6.2 Weighted score

`final_score = 0.40*semantic + 0.30*skill + 0.20*experience + 0.10*domain`

Each component normalized to `[0,100]`.

### 6.3 Skill scoring
- Must-have matched: `+10`
- Nice-to-have matched: `+5`
- Must-have missing: `-15`
- Score clamped to `[0,100]` after normalization.

### 6.4 Confidence score
Separate confidence based on:
- parse quality
- document completeness
- model agreement (semantic vs rules consistency)

UI should always show both: `Match Score` and `Confidence`.

## 7) Explainability Contract

Every ranked result returns:
- score breakdown per component
- top matched skills
- missing must-have skills
- supporting evidence snippets from resume text
- reasoning model version + timestamp

No explanation should be returned without at least 1 evidence snippet.

## 8) Database Schema V2

```sql
-- users
CREATE TABLE users (
  id UUID PRIMARY KEY,
  name TEXT NOT NULL,
  email TEXT UNIQUE NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('admin','recruiter')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- jobs
CREATE TABLE jobs (
  id UUID PRIMARY KEY,
  created_by UUID NOT NULL REFERENCES users(id),
  title TEXT NOT NULL,
  description TEXT NOT NULL,
  location TEXT,
  employment_type TEXT,
  min_experience_years NUMERIC(4,1),
  required_skills JSONB NOT NULL DEFAULT '[]'::jsonb,
  nice_to_have_skills JSONB NOT NULL DEFAULT '[]'::jsonb,
  domain_tags JSONB NOT NULL DEFAULT '[]'::jsonb,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','paused','closed')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- candidates
CREATE TABLE candidates (
  id UUID PRIMARY KEY,
  full_name TEXT,
  primary_email TEXT,
  phone TEXT,
  location TEXT,
  linkedin_url TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX ux_candidates_primary_email ON candidates(primary_email) WHERE primary_email IS NOT NULL;

-- resumes
CREATE TABLE resumes (
  id UUID PRIMARY KEY,
  candidate_id UUID NOT NULL REFERENCES candidates(id),
  source_filename TEXT,
  file_url TEXT NOT NULL,
  mime_type TEXT,
  raw_text TEXT,
  parsed_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  skills_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  experience_years NUMERIC(4,1),
  parse_status TEXT NOT NULL DEFAULT 'pending' CHECK (parse_status IN ('pending','parsed','failed')),
  parse_error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- embeddings
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE resume_embeddings (
  resume_id UUID PRIMARY KEY REFERENCES resumes(id),
  embedding vector(384) NOT NULL,
  model_name TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE job_embeddings (
  job_id UUID PRIMARY KEY REFERENCES jobs(id),
  embedding vector(384) NOT NULL,
  model_name TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- rankings (versioned)
CREATE TABLE rankings (
  id UUID PRIMARY KEY,
  job_id UUID NOT NULL REFERENCES jobs(id),
  candidate_id UUID NOT NULL REFERENCES candidates(id),
  resume_id UUID NOT NULL REFERENCES resumes(id),
  score NUMERIC(5,2) NOT NULL,
  confidence NUMERIC(5,2) NOT NULL,
  semantic_score NUMERIC(5,2) NOT NULL,
  skill_score NUMERIC(5,2) NOT NULL,
  experience_score NUMERIC(5,2) NOT NULL,
  domain_score NUMERIC(5,2) NOT NULL,
  explanation_json JSONB NOT NULL,
  model_version TEXT NOT NULL,
  scoring_version TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_rankings_job_score ON rankings(job_id, score DESC);
CREATE UNIQUE INDEX ux_rankings_job_candidate_resume_version
  ON rankings(job_id, candidate_id, resume_id, scoring_version);

-- recruiter actions (feedback loop foundation)
CREATE TABLE recruiter_actions (
  id UUID PRIMARY KEY,
  job_id UUID NOT NULL REFERENCES jobs(id),
  candidate_id UUID NOT NULL REFERENCES candidates(id),
  action TEXT NOT NULL CHECK (action IN ('viewed','shortlisted','rejected','interviewed','hired')),
  notes TEXT,
  created_by UUID NOT NULL REFERENCES users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- audit logs
CREATE TABLE audit_logs (
  id UUID PRIMARY KEY,
  entity_type TEXT NOT NULL,
  entity_id UUID NOT NULL,
  event_type TEXT NOT NULL,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_by UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## 9) API Contracts (v1)

Base path: `/api/v1`

### Auth
- `POST /auth/login`
- `POST /auth/logout`
- `GET /auth/me`

### Jobs
- `POST /jobs`
- `GET /jobs`
- `GET /jobs/{job_id}`
- `PATCH /jobs/{job_id}`
- `DELETE /jobs/{job_id}`

### Resume Upload + Parse
- `POST /jobs/{job_id}/resumes/upload` (multi-file)
- `GET /jobs/{job_id}/ingestion-status`
- `POST /resumes/{resume_id}/reprocess`

### Ranking
- `POST /jobs/{job_id}/rank` (trigger ranking run)
- `GET /jobs/{job_id}/rankings?limit=50&offset=0&min_score=0&skills=python,react`
- `GET /jobs/{job_id}/candidates/{candidate_id}/explanation`

### Candidate
- `GET /candidates/{candidate_id}`
- `GET /candidates/{candidate_id}/resumes`
- `POST /jobs/{job_id}/candidates/{candidate_id}/action`

### Search / Filter
- `GET /jobs/{job_id}/search?q=servicenow&location=texas&exp_min=4`

## 10) Core Endpoint Response Shapes

### 10.1 Ranking row

```json
{
  "candidate_id": "uuid",
  "resume_id": "uuid",
  "candidate_name": "John Doe",
  "score": 92.4,
  "confidence": 87.1,
  "experience_years": 7.0,
  "top_reasons": [
    "Strong ServiceNow ITSM experience",
    "6+ years in similar role",
    "Healthcare domain overlap"
  ]
}
```

### 10.2 Explanation payload

```json
{
  "score_breakdown": {
    "semantic": 90.0,
    "skill": 95.0,
    "experience": 85.0,
    "domain": 80.0
  },
  "matched_skills": ["ServiceNow", "JavaScript", "ITSM"],
  "missing_skills": ["CMDB", "Flow Designer"],
  "evidence_snippets": [
    {
      "label": "ITSM experience",
      "text": "Implemented incident, change and request workflows in ServiceNow ITSM..."
    }
  ],
  "summary": "Candidate is a strong fit for core ServiceNow development...",
  "model_version": "mistral:7b-instruct-q4",
  "scoring_version": "score_v1.0"
}
```

## 11) UI/UX Blueprint (Screen-by-Screen)

### 11.1 Dashboard
- Job cards with:
  - Job title
  - # resumes processed / total
  - Last ranking run time
  - Quick actions: `View rankings`, `Upload resumes`

### 11.2 Job Detail + Rankings
- Sticky filter panel (left)
- Ranking table (right): Rank, Name, Score, Confidence, Experience, Top Reasons
- Bulk actions: shortlist/reject
- “Run Re-rank” button with model + scoring version tag

### 11.3 Candidate Profile
- Header: Name, score, confidence, status
- Tabs:
  - `Overview` (summary + score breakdown)
  - `Skills` (matched/missing)
  - `Evidence` (resume snippets)
  - `Timeline` (experience)
  - `Resume` (raw text/doc preview)
- Right rail:
  - recruiter actions
  - notes
  - change history

### 11.4 Design Direction (non-generic)
- Typography: `Space Grotesk` (headings), `Source Sans 3` (body)
- Color system: slate base + teal accent + amber warning
- Visuals: subtle gradient background + card depth + status chips
- Motion: staggered row reveal on ranking load; smooth filter transitions
- Mobile: stacked cards, collapsible filters, sticky shortlist CTA

## 12) Compliance and Responsible AI (MVP minimum)

- Always show “AI-assisted recommendation” notice.
- Provide human override for every recommendation.
- Log model/scoring version for each ranking event.
- Keep immutable audit logs for recruiter actions and score runs.
- Add bias check report placeholder endpoint for future enforcement.

## 13) 4-Week Execution Plan

### Week 1
- Repo bootstrap (Next.js + FastAPI)
- Auth + job CRUD
- Resume upload/storage + async parse worker
- PostgreSQL schema migration v1

### Week 2
- Embedding pipeline + pgvector integration
- Hybrid retrieval + scoring engine
- Ranking API + table UI

### Week 3
- Candidate detail + explanation panel
- Filters/search + shortlist actions
- Audit logs + version stamping

### Week 4
- LLM reasoning for top K
- Confidence calibration
- UX polish + end-to-end test pass
- Demo dataset + launch checklist

## 14) KPIs to Track from Day 1

- Time-to-shortlist per job
- Recruiter acceptance rate of top-10
- Re-rank frequency
- Parse failure rate
- Explanation coverage rate

## 15) Immediate Build Backlog (start now)

1. Initialize monorepo structure (`frontend`, `backend`, `worker`, `infra`).
2. Create DB migrations for schema v2 core tables.
3. Implement resume ingestion endpoint + queue worker skeleton.
4. Implement job ranking endpoint returning mock breakdown.
5. Build ranking table UI and candidate detail page with static mock first.

