"""multi-user: users, resumes, rankings + user_id on per-user tables

Additive only (new tables + nullable user_id columns) so it applies cleanly on
an existing single-user database.

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-30
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── users ──
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255)),
        sa.Column("password_hash", sa.String(255)),
        sa.Column("google_sub", sa.String(255)),
        sa.Column("avatar_url", sa.String(512)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime()),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.UniqueConstraint("google_sub", name="uq_users_google_sub"),
    )
    op.create_index("ix_users_email", "users", ["email"])

    # ── resumes ──
    op.create_table(
        "resumes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("filename", sa.String(255)),
        sa.Column("raw_text", sa.Text()),
        sa.Column("parsed_json", sa.JSON(), nullable=False),
        sa.Column("pdf_path", sa.String(512)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_resumes_user_id", "resumes", ["user_id"])
    op.create_index("ix_resumes_user_active", "resumes", ["user_id", "is_active"])

    # ── rankings ──
    op.create_table(
        "rankings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("job_id", sa.String(36), nullable=False),
        sa.Column("rank_score", sa.Integer()),
        sa.Column("rank_breakdown", sa.JSON()),
        sa.Column("rank_reasoning", sa.Text()),
        sa.Column("ats_keywords", sa.JSON()),
        sa.Column("status", sa.String(32), nullable=False, server_default="ranked"),
        sa.Column("applied_manually_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "job_id", name="uq_ranking_user_job"),
    )
    op.create_index("ix_rankings_user_id", "rankings", ["user_id"])
    op.create_index("ix_rankings_job_id", "rankings", ["job_id"])
    op.create_index("ix_rankings_user_score", "rankings", ["user_id", "rank_score"])

    # ── user_id on per-user tables ──
    for table in ("applications", "resume_versions", "cover_letters"):
        op.add_column(table, sa.Column("user_id", sa.String(36), nullable=True))
        op.create_index(f"ix_{table}_user_id", table, ["user_id"])
        op.create_foreign_key(
            f"fk_{table}_user", table, "users", ["user_id"], ["id"], ondelete="CASCADE"
        )


def downgrade() -> None:
    for table in ("applications", "resume_versions", "cover_letters"):
        op.drop_constraint(f"fk_{table}_user", table, type_="foreignkey")
        op.drop_index(f"ix_{table}_user_id", table_name=table)
        op.drop_column(table, "user_id")
    op.drop_table("rankings")
    op.drop_table("resumes")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
