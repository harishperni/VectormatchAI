"""add job_resumes link table

Revision ID: 20260304_0002
Revises: 20260304_0001
Create Date: 2026-03-04
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260304_0002"
down_revision = "20260304_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "job_resumes",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("candidate_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("candidates.id"), nullable=False),
        sa.Column("resume_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("resumes.id"), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_index("idx_job_resumes_job", "job_resumes", ["job_id"], unique=False)
    op.create_index(
        "ux_job_resumes_job_resume",
        "job_resumes",
        ["job_id", "resume_id"],
        unique=True,
    )
    op.execute(
        """
        INSERT INTO job_resumes (id, job_id, candidate_id, resume_id, created_at)
        SELECT
            gen_random_uuid(),
            entity_id,
            (payload->>'candidate_id')::uuid,
            (payload->>'resume_id')::uuid,
            now()
        FROM audit_logs
        WHERE entity_type = 'job'
          AND event_type IN ('resume_ingestion_queued', 'resume_ingestion_queue_failed')
          AND payload ? 'candidate_id'
          AND payload ? 'resume_id'
        ON CONFLICT (job_id, resume_id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("ux_job_resumes_job_resume", table_name="job_resumes")
    op.drop_index("idx_job_resumes_job", table_name="job_resumes")
    op.drop_table("job_resumes")
