"""rank-only sources + manual apply tracking

Adds:
  - jobs.auto_apply           (bool, default true)  — false for rank-only sources
  - jobs.applied_manually_at  (datetime, nullable)  — set on manual "mark applied"
  - applications.manual       (bool, default false) — manual application flag

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-29
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("auto_apply", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "jobs",
        sa.Column("applied_manually_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "applications",
        sa.Column("manual", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("applications", "manual")
    op.drop_column("jobs", "applied_manually_at")
    op.drop_column("jobs", "auto_apply")
