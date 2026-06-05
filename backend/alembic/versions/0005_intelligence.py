"""job intelligence: preferences, watchlist, feedback, source health, company tiers,
hybrid-ranking columns, job.apply_type

Additive only — safe on an existing database.

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-05
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── rankings: hybrid-ranking outputs + per-user actions ──
    op.add_column("rankings", sa.Column("match_label", sa.String(16), nullable=True))
    op.add_column("rankings", sa.Column("match_signals", sa.JSON(), nullable=True))
    op.add_column(
        "rankings",
        sa.Column("saved", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "rankings",
        sa.Column("hidden", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    # ── jobs: how the user applies ──
    op.add_column(
        "jobs",
        sa.Column("apply_type", sa.String(16), nullable=False, server_default="external"),
    )

    # ── user_preferences ──
    op.create_table(
        "user_preferences",
        sa.Column("user_id", sa.String(36), primary_key=True),
        sa.Column("target_roles", sa.JSON()),
        sa.Column("experience_level", sa.String(16)),
        sa.Column("min_salary_lpa", sa.Float()),
        sa.Column("preferred_cities", sa.JSON()),
        sa.Column("work_modes", sa.JSON()),
        sa.Column("job_types", sa.JSON()),
        sa.Column("prioritized_industries", sa.JSON()),
        sa.Column("blocked_industries", sa.JSON()),
        sa.Column("preferred_countries", sa.JSON()),
        sa.Column("needs_sponsorship", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("excluded_keywords", sa.JSON()),
        sa.Column("must_have_skills", sa.JSON()),
        sa.Column("nice_to_have_skills", sa.JSON()),
        sa.Column("alert_instant", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("alert_daily_digest", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_alert_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )

    # ── watchlist_companies ──
    op.create_table(
        "watchlist_companies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("company", sa.String(255), nullable=False),
        sa.Column("company_norm", sa.String(255), nullable=False),
        sa.Column("priority", sa.String(16), nullable=False, server_default="prioritize"),
        sa.Column("created_at", sa.DateTime()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "company_norm", name="uq_watchlist_user_company"),
    )
    op.create_index("ix_watchlist_user", "watchlist_companies", ["user_id"])

    # ── job_feedback ──
    op.create_table(
        "job_feedback",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("job_id", sa.String(36)),
        sa.Column("action", sa.String(24), nullable=False),
        sa.Column("company_norm", sa.String(255)),
        sa.Column("terms", sa.JSON()),
        sa.Column("created_at", sa.DateTime()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_feedback_user", "job_feedback", ["user_id"])

    # ── source_health ──
    op.create_table(
        "source_health",
        sa.Column("source", sa.String(40), primary_key=True),
        sa.Column("last_run_at", sa.DateTime()),
        sa.Column("last_success_at", sa.DateTime()),
        sa.Column("jobs_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("jobs_added", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_runs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text()),
        sa.Column("updated_at", sa.DateTime()),
    )

    # ── company_tiers (admin overrides) ──
    op.create_table(
        "company_tiers",
        sa.Column("company_norm", sa.String(255), primary_key=True),
        sa.Column("company", sa.String(255), nullable=False),
        sa.Column("tier", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime()),
    )


def downgrade() -> None:
    op.drop_table("company_tiers")
    op.drop_table("source_health")
    op.drop_index("ix_feedback_user", table_name="job_feedback")
    op.drop_table("job_feedback")
    op.drop_index("ix_watchlist_user", table_name="watchlist_companies")
    op.drop_table("watchlist_companies")
    op.drop_table("user_preferences")
    op.drop_column("jobs", "apply_type")
    op.drop_column("rankings", "hidden")
    op.drop_column("rankings", "saved")
    op.drop_column("rankings", "match_signals")
    op.drop_column("rankings", "match_label")
