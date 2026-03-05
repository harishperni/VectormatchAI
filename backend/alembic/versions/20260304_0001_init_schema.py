"""init schema

Revision ID: 20260304_0001
Revises:
Create Date: 2026-03-04
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260304_0001"
down_revision = None
branch_labels = None
depends_on = None


VECTOR_DIM = 384


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False, unique=True),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("role IN ('admin','recruiter')", name="ck_users_role"),
    )

    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("employment_type", sa.Text(), nullable=True),
        sa.Column("min_experience_years", sa.Numeric(4, 1), nullable=True),
        sa.Column("required_skills", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("nice_to_have_skills", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("domain_tags", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("status IN ('active','paused','closed')", name="ck_jobs_status"),
    )

    op.create_table(
        "candidates",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("full_name", sa.Text(), nullable=True),
        sa.Column("primary_email", sa.Text(), nullable=True),
        sa.Column("phone", sa.Text(), nullable=True),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("linkedin_url", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_index(
        "ux_candidates_primary_email",
        "candidates",
        ["primary_email"],
        unique=True,
        postgresql_where=sa.text("primary_email IS NOT NULL"),
    )

    op.create_table(
        "resumes",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("candidate_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("candidates.id"), nullable=False),
        sa.Column("source_filename", sa.Text(), nullable=True),
        sa.Column("file_url", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.Text(), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("parsed_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("skills_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("experience_years", sa.Numeric(4, 1), nullable=True),
        sa.Column("parse_status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("parse_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("parse_status IN ('pending','parsed','failed')", name="ck_resumes_parse_status"),
    )

    op.create_table(
        "resume_embeddings",
        sa.Column("resume_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("resumes.id"), primary_key=True),
        sa.Column("embedding", sa.ARRAY(sa.Float()), nullable=False),
        sa.Column("model_name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "job_embeddings",
        sa.Column("job_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("jobs.id"), primary_key=True),
        sa.Column("embedding", sa.ARRAY(sa.Float()), nullable=False),
        sa.Column("model_name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "rankings",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("candidate_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("candidates.id"), nullable=False),
        sa.Column("resume_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("resumes.id"), nullable=False),
        sa.Column("score", sa.Numeric(5, 2), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 2), nullable=False),
        sa.Column("semantic_score", sa.Numeric(5, 2), nullable=False),
        sa.Column("skill_score", sa.Numeric(5, 2), nullable=False),
        sa.Column("experience_score", sa.Numeric(5, 2), nullable=False),
        sa.Column("domain_score", sa.Numeric(5, 2), nullable=False),
        sa.Column("explanation_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("model_version", sa.Text(), nullable=False),
        sa.Column("scoring_version", sa.Text(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_rankings_job_score", "rankings", ["job_id", "score"], unique=False)
    op.create_index(
        "ux_rankings_job_candidate_resume_version",
        "rankings",
        ["job_id", "candidate_id", "resume_id", "scoring_version"],
        unique=True,
    )

    op.create_table(
        "recruiter_actions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("candidate_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("candidates.id"), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "action IN ('viewed','shortlisted','rejected','interviewed','hired')",
            name="ck_recruiter_actions_action",
        ),
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_by", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("recruiter_actions")
    op.drop_index("ux_rankings_job_candidate_resume_version", table_name="rankings")
    op.drop_index("idx_rankings_job_score", table_name="rankings")
    op.drop_table("rankings")
    op.drop_table("job_embeddings")
    op.drop_table("resume_embeddings")
    op.drop_table("resumes")
    op.drop_index("ux_candidates_primary_email", table_name="candidates")
    op.drop_table("candidates")
    op.drop_table("jobs")
    op.drop_table("users")
