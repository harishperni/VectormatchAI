from fastapi import APIRouter

from app.api.v1 import jobs, rankings

api_router = APIRouter()
api_router.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
api_router.include_router(rankings.router, prefix="/jobs", tags=["rankings"])
