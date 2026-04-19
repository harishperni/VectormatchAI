"""add per-job job hopper thresholds

Revision ID: 20260418_0004
Revises: 20260402_0003
Create Date: 2026-04-18
"""

from alembic import op
import sqlalchemy as sa


revision = "20260418_0004"
down_revision = "20260402_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("job_hopper_short_tenure_months", sa.Integer(), nullable=False, server_default="12"),
    )
    op.add_column(
        "jobs",
        sa.Column("job_hopper_min_short_stints", sa.Integer(), nullable=False, server_default="2"),
    )
    op.create_check_constraint(
        "ck_jobs_job_hopper_short_tenure_months",
        "jobs",
        "job_hopper_short_tenure_months BETWEEN 3 AND 36",
    )
    op.create_check_constraint(
        "ck_jobs_job_hopper_min_short_stints",
        "jobs",
        "job_hopper_min_short_stints BETWEEN 1 AND 6",
    )


def downgrade() -> None:
    op.drop_constraint("ck_jobs_job_hopper_min_short_stints", "jobs", type_="check")
    op.drop_constraint("ck_jobs_job_hopper_short_tenure_months", "jobs", type_="check")
    op.drop_column("jobs", "job_hopper_min_short_stints")
    op.drop_column("jobs", "job_hopper_short_tenure_months")
