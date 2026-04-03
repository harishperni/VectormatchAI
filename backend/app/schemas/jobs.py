import uuid

from pydantic import BaseModel, ConfigDict, Field


class JobCreate(BaseModel):
    title: str = Field(min_length=2, max_length=150)
    description: str = Field(min_length=20)
    location: str | None = None
    min_experience_years: float | None = None
    required_skills: list[str] = Field(default_factory=list)
    nice_to_have_skills: list[str] = Field(default_factory=list)
    domain_tags: list[str] = Field(default_factory=list)


class JobOut(BaseModel):
    id: uuid.UUID
    title: str
    description: str
    location: str | None
    min_experience_years: float | None
    required_skills: list[str]
    nice_to_have_skills: list[str]
    domain_tags: list[str]

    model_config = ConfigDict(from_attributes=True)


class JobUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=150)
    description: str | None = Field(default=None, min_length=20)
    location: str | None = None
    min_experience_years: float | None = None
    required_skills: list[str] | None = None
    nice_to_have_skills: list[str] | None = None
    domain_tags: list[str] | None = None
