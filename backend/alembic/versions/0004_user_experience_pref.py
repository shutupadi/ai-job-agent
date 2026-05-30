"""add users.experience_pref (fresher mode toggle)

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-30
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("experience_pref", sa.String(16), nullable=False, server_default="fresher"),
    )


def downgrade() -> None:
    op.drop_column("users", "experience_pref")
