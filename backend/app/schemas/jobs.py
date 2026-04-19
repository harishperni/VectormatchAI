import uuid

from pydantic import BaseModel, ConfigDict, Field


class JobCreate(BaseModel):
    title: str = Field(min_length=2, max_length=150)
    description: str = Field(min_length=20)
    location: str | None = None
    work_mode: str = Field(default="remote", pattern="^(remote|hybrid|inperson)$")
    min_experience_years: float | None = None
    job_hopper_short_tenure_months: int = Field(default=12, ge=3, le=36)
    job_hopper_min_short_stints: int = Field(default=2, ge=1, le=6)
    required_skills: list[str] = Field(default_factory=list)
    nice_to_have_skills: list[str] = Field(default_factory=list)
    domain_tags: list[str] = Field(default_factory=list)


class JobOut(BaseModel):
    id: uuid.UUID
    title: str
    description: str
    location: str | None
    work_mode: str
    min_experience_years: float | None
    job_hopper_short_tenure_months: int
    job_hopper_min_short_stints: int
    required_skills: list[str]
    nice_to_have_skills: list[str]
    domain_tags: list[str]

    model_config = ConfigDict(from_attributes=True)


class JobUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=150)
    description: str | None = Field(default=None, min_length=20)
    location: str | None = None
    work_mode: str | None = Field(default=None, pattern="^(remote|hybrid|inperson)$")
    min_experience_years: float | None = None
    job_hopper_short_tenure_months: int | None = Field(default=None, ge=3, le=36)
    job_hopper_min_short_stints: int | None = Field(default=None, ge=1, le=6)
    required_skills: list[str] | None = None
    nice_to_have_skills: list[str] | None = None
    domain_tags: list[str] | None = None
