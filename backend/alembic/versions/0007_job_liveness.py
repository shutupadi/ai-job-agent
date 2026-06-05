"""job liveness: jobs.open_status + jobs.last_checked_at

Additive only. Existing rows default to 'open'.

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-05
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("open_status", sa.String(10), nullable=False, server_default="open"),
    )
    op.add_column("jobs", sa.Column("last_checked_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "last_checked_at")
    op.drop_column("jobs", "open_status")
