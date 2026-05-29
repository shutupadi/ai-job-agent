"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-05-28
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("url_hash", sa.String(64), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("company", sa.String(255), nullable=False),
        sa.Column("location", sa.String(255)),
        sa.Column("remote", sa.Boolean, default=False),
        sa.Column("department", sa.String(255)),
        sa.Column("description", sa.Text, server_default=""),
        sa.Column("salary_text", sa.String(255)),
        sa.Column("posted_at", sa.DateTime),
        sa.Column("discovered_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("rank_score", sa.Integer),
        sa.Column("rank_breakdown", sa.JSON),
        sa.Column("rank_reasoning", sa.Text),
        sa.Column("ats_keywords", sa.JSON),
        sa.Column("status", sa.String(32), server_default="new"),
        sa.Column("raw", sa.JSON),
        sa.UniqueConstraint("source", "external_id", name="uq_job_source_externalid"),
    )
    op.create_index("ix_jobs_url_hash", "jobs", ["url_hash"])

    op.create_table(
        "runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("started_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime),
        sa.Column("trigger", sa.String(32), server_default="manual"),
        sa.Column("status", sa.String(32), server_default="running"),
        sa.Column("jobs_found", sa.Integer, server_default="0"),
        sa.Column("jobs_new", sa.Integer, server_default="0"),
        sa.Column("ranked", sa.Integer, server_default="0"),
        sa.Column("tailored", sa.Integer, server_default="0"),
        sa.Column("applied", sa.Integer, server_default="0"),
        sa.Column("failed_applications", sa.Integer, server_default="0"),
        sa.Column("log", sa.Text),
        sa.Column("summary", sa.Text),
    )

    op.create_table(
        "resume_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id", ondelete="SET NULL")),
        sa.Column("label", sa.String(255), server_default="tailored"),
        sa.Column("pdf_path", sa.String(512), nullable=False),
        sa.Column("json_payload", sa.JSON, nullable=False),
        sa.Column("ats_keywords", sa.JSON),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_table(
        "cover_letters",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id", ondelete="SET NULL")),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("pdf_path", sa.String(512)),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_table(
        "applications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id", ondelete="CASCADE")),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id", ondelete="SET NULL")),
        sa.Column(
            "resume_version_id",
            sa.String(36),
            sa.ForeignKey("resume_versions.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "cover_letter_id",
            sa.String(36),
            sa.ForeignKey("cover_letters.id", ondelete="SET NULL"),
        ),
        sa.Column("status", sa.String(32), server_default="queued"),
        sa.Column("approval_required", sa.Boolean, server_default=sa.false()),
        sa.Column("approved_at", sa.DateTime),
        sa.Column("submitted_at", sa.DateTime),
        sa.Column("attempts", sa.Integer, server_default="0"),
        sa.Column("error", sa.Text),
        sa.Column("screenshot_path", sa.String(512)),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_table(
        "settings_kv",
        sa.Column("key", sa.String(128), primary_key=True),
        sa.Column("value", sa.JSON),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("applications")
    op.drop_table("cover_letters")
    op.drop_table("resume_versions")
    op.drop_table("runs")
    op.drop_index("ix_jobs_url_hash", table_name="jobs")
    op.drop_table("jobs")
    op.drop_table("settings_kv")
