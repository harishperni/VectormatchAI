"""add work_mode to jobs

Revision ID: 20260402_0003
Revises: 20260304_0002
Create Date: 2026-04-02
"""

from alembic import op
import sqlalchemy as sa


revision = "20260402_0003"
down_revision = "20260304_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("work_mode", sa.Text(), nullable=False, server_default=sa.text("'remote'")),
    )
    op.create_check_constraint(
        "ck_jobs_work_mode",
        "jobs",
        "work_mode IN ('remote','hybrid','inperson')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_jobs_work_mode", "jobs", type_="check")
    op.drop_column("jobs", "work_mode")

