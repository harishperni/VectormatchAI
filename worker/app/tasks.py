import dramatiq


@dramatiq.actor
def resume_ingestion_task(job_id: str, resume_id: str) -> None:
    # TODO: parse resume -> normalize profile -> generate embedding.
    print(f"Ingesting resume {resume_id} for job {job_id}")


@dramatiq.actor
def rank_job_task(job_id: str) -> None:
    # TODO: run retrieval + scoring + explanation generation.
    print(f"Ranking candidates for job {job_id}")
