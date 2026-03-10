# ATS Project Monorepo

## Structure
- `frontend` - Next.js recruiter UI
- `backend` - FastAPI API service
- `worker` - async ingestion/ranking workers
- `infra` - local infra config (docker compose, scripts)

## Quick start
1. Backend
   - `cd backend`
   - `python -m venv .venv && source .venv/bin/activate`
   - `pip install -r requirements.txt`
   - `python -m alembic upgrade head`
   - `uvicorn app.main:app --reload --port 8000`

2. Frontend
   - `cd frontend`
   - `npm install`
   - `npm run dev`
   - optional: set `NEXT_PUBLIC_API_BASE_URL` if backend is not on `http://localhost:8000`

3. Worker (queue consumer)
   - `cd worker`
   - `python -m venv .venv && source .venv/bin/activate`
   - `pip install -r requirements.txt`
   - `python -m app.main`

## One-command local startup
- Infra + migrations:
  - `make dev-up`
- Start backend + worker + frontend together:
  - `make dev-all`
- Stop infra:
  - `make infra-down`

## Resume ingestion test
- Upload one or more files:
  - `POST /api/v1/jobs/{job_id}/resumes/upload` (multipart form field: `files`)
- Check queue status:
  - `GET /api/v1/jobs/{job_id}/ingestion-status`
- Verify parsed output in DB (optional):
  - `docker exec -it ats-postgres psql -U postgres -d ats -c "select id, parse_status, experience_years, left(raw_text,120) from resumes order by created_at desc limit 5;"`

## Create jobs from UI
- Open `http://localhost:3000/recruiter`
- Use the `Create New Job` form (title, location, description, skills, domain tags)
- On submit, UI redirects directly to that job workspace.

## Bulk candidate actions
- In `/jobs/{job_id}`, select candidates using checkboxes in the Applicants table.
- Use `Bulk Recommend`, `Bulk Reject`, or `Recommend Other Jobs`.

## Candidate pipeline
- In `/jobs/{job_id}`, the `Candidate Pipeline` board shows stages:
  - New, Review, Shortlisted, Interview, Offer, Rejected
- Quick action buttons update candidate stage immediately.

## Evaluation + golden dataset
- Open `/jobs/{job_id}/evaluation` to view:
  - Precision/Recall at top-K (if golden data exists)
  - Run-to-run rank/score diff from recent ranking runs
  - Score/confidence summary
- Golden dataset file path:
  - `backend/data/golden/{job_id}.json`
  - Example format in `backend/data/golden/example-job.json`
- CLI evaluator:
  - `cd backend && python scripts/evaluate_job.py --job-id <job_id> --top-k 5`
- UI management:
  - Open `/jobs/{job_id}/evaluation`
  - Use `Golden Dataset Manager` to paste/save JSON directly

## Embedding-based semantic ranking
- Backend ranking now uses `sentence-transformers/all-MiniLM-L6-v2` cosine similarity.
- Install latest backend requirements after pulling changes:
  - `cd backend && source .venv/bin/activate && pip install -r requirements.txt`

## OpenAI LLM reasoning
- Ranking now calls OpenAI for all ranked candidates (GPT-driven scoring + analysis).
- Required:
  - `OPENAI_API_KEY=<your_key>`
- Defaults:
  - `OPENAI_API_BASE_URL=https://api.openai.com/v1`
  - `OPENAI_REASONING_MODEL=gpt-4.1-mini`
  - `LLM_TOP_K=1000`
  - `OPENAI_TIMEOUT_SECONDS=20`
- GPT-only score mode (default enabled):
  - `GPT_ONLY_RANKING=true`
- Optional LLM score blending (off by default):
  - `ENABLE_LLM_SCORING=true`
  - `LLM_SCORE_WEIGHT=0.2`
  - `LLM_CONFIDENCE_WEIGHT=0.3`

## Optional LLM parsing fallback (worker)
- Uses OpenAI to fill missing fields when heuristic parsing is weak.
- Enable:
  - `OPENAI_API_KEY=<your_key>`
  - `ENABLE_LLM_PARSE=true`
  - `OPENAI_PARSE_MODEL=gpt-4.1-mini`
  - `LLM_PARSE_TIMEOUT_SECONDS=30`
- Force GPT-only parsing (no heuristic fields):
  - `LLM_PARSE_ONLY=true`
- GPT parse now extracts `current_last_job` and prefers GPT `experience_years`
  while excluding education duration from work experience.

## Resume extraction pipeline
- Text extraction order:
  - `PyMuPDF` for PDF
  - `python-docx` for DOCX
  - `Unstructured` fallback when extracted text looks weak
- Parsed JSON enrichment:
  - heuristic parse
  - GPT parse
  - GPT normalization pass over raw text + preliminary JSON

## Distance filter behavior
- Distance is computed between `jobs.location` and candidate location extracted from resume text.
- Geocoding uses OpenStreetMap Nominatim at ranking/filter time with local in-process cache.
- Set `location` when creating a job (`POST /api/v1/jobs`) for best distance results.
- You can set/update an existing job location with `PATCH /api/v1/jobs/{job_id}`.
