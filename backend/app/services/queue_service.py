import json
import os
import uuid

import redis


REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
INGESTION_QUEUE_KEY = os.getenv("INGESTION_QUEUE_KEY", "resume_ingestion_queue")


def enqueue_resume_ingestion(job_id: uuid.UUID, resume_id: uuid.UUID, file_url: str) -> bool:
    message = {
        "job_id": str(job_id),
        "resume_id": str(resume_id),
        "file_url": file_url,
    }
    try:
        client = redis.from_url(REDIS_URL, decode_responses=True)
        client.rpush(INGESTION_QUEUE_KEY, json.dumps(message))
        return True
    except redis.RedisError:
        return False
