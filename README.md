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

## Resume ingestion test
- Upload one or more files:
  - `POST /api/v1/jobs/{job_id}/resumes/upload` (multipart form field: `files`)
- Check queue status:
  - `GET /api/v1/jobs/{job_id}/ingestion-status`
- Verify parsed output in DB (optional):
  - `docker exec -it ats-postgres psql -U postgres -d ats -c "select id, parse_status, experience_years, left(raw_text,120) from resumes order by created_at desc limit 5;"`

## Embedding-based semantic ranking
- Backend ranking now uses `sentence-transformers/all-MiniLM-L6-v2` cosine similarity.
- Install latest backend requirements after pulling changes:
  - `cd backend && source .venv/bin/activate && pip install -r requirements.txt`

## Ollama LLM reasoning
- Ranking now calls Ollama for top candidates (default top 1) to generate summary/reasons.
- Defaults:
  - `OLLAMA_BASE_URL=http://localhost:11434`
  - `OLLAMA_MODEL=llama3.1:8b`
  - `LLM_TOP_K=1`
  - `OLLAMA_TIMEOUT_SECONDS=20`
- Optional LLM score blending (off by default):
  - `ENABLE_LLM_SCORING=true`
  - `LLM_SCORE_WEIGHT=0.2`
  - `LLM_CONFIDENCE_WEIGHT=0.3`
- Pull a model first (one-time):
  - `ollama pull llama3.1:8b`

## Distance filter behavior
- Distance is computed between `jobs.location` and candidate location extracted from resume text.
- Geocoding uses OpenStreetMap Nominatim at ranking/filter time with local in-process cache.
- Set `location` when creating a job (`POST /api/v1/jobs`) for best distance results.
- You can set/update an existing job location with `PATCH /api/v1/jobs/{job_id}`.
