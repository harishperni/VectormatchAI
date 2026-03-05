from __future__ import annotations

import math
from typing import Iterable

from sqlalchemy.orm import Session

from app.db.models import Job, JobEmbedding, Resume, ResumeEmbedding

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

_model = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model


def _normalize_vector(vector: Iterable[float]) -> list[float]:
    values = [float(v) for v in vector]
    norm = math.sqrt(sum(v * v for v in values))
    if norm == 0:
        return values
    return [v / norm for v in values]


def embed_text(text: str) -> list[float]:
    model = _get_model()
    vector = model.encode(text or "", normalize_embeddings=True)
    return [float(v) for v in vector]


def cosine_similarity_percent(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    a_norm = _normalize_vector(a)
    b_norm = _normalize_vector(b)
    similarity = sum(x * y for x, y in zip(a_norm, b_norm))
    similarity = max(-1.0, min(1.0, similarity))
    # map [-1,1] to [0,100]
    return round(((similarity + 1.0) / 2.0) * 100.0, 2)


def get_or_create_job_embedding(db: Session, job: Job) -> JobEmbedding:
    existing = db.get(JobEmbedding, job.id)
    if existing and existing.model_name == EMBEDDING_MODEL:
        return existing

    vector = embed_text(job.description or "")
    if existing:
        existing.embedding = vector
        existing.model_name = EMBEDDING_MODEL
        db.flush()
        return existing

    row = JobEmbedding(
        job_id=job.id,
        embedding=vector,
        model_name=EMBEDDING_MODEL,
    )
    db.add(row)
    db.flush()
    return row


def get_or_create_resume_embedding(db: Session, resume: Resume) -> ResumeEmbedding:
    existing = db.get(ResumeEmbedding, resume.id)
    if existing and existing.model_name == EMBEDDING_MODEL:
        return existing

    vector = embed_text(resume.raw_text or "")
    if existing:
        existing.embedding = vector
        existing.model_name = EMBEDDING_MODEL
        db.flush()
        return existing

    row = ResumeEmbedding(
        resume_id=resume.id,
        embedding=vector,
        model_name=EMBEDDING_MODEL,
    )
    db.add(row)
    db.flush()
    return row
