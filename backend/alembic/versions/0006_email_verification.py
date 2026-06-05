"""email verification (OTP) + guest résumé sessions

Additive + a safe backfill: existing users are grandfathered to email_verified=True
so nobody is locked out. New email/password signups start unverified.

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-05
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── users: verification flags ──
    op.add_column(
        "users",
        sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("users", sa.Column("email_verified_at", sa.DateTime(), nullable=True))
    # Grandfather every EXISTING account so current users are not locked out.
    op.execute("UPDATE users SET email_verified = true")

    # ── email_otps ──
    op.create_table(
        "email_otps",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("otp_hash", sa.String(128), nullable=False),
        sa.Column("purpose", sa.String(20), nullable=False, server_default="signup"),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("consumed_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_email_otps_user_id", "email_otps", ["user_id"])
    op.create_index("ix_email_otps_user_purpose", "email_otps", ["user_id", "purpose"])

    # ── guest_sessions ──
    op.create_table(
        "guest_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("token", sa.String(64), nullable=False),
        sa.Column("filename", sa.String(255)),
        sa.Column("raw_text", sa.Text()),
        sa.Column("parsed_json", sa.JSON(), nullable=False),
        sa.Column("claimed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("token", name="uq_guest_sessions_token"),
    )
    op.create_index("ix_guest_sessions_token", "guest_sessions", ["token"])


def downgrade() -> None:
    op.drop_index("ix_guest_sessions_token", table_name="guest_sessions")
    op.drop_table("guest_sessions")
    op.drop_index("ix_email_otps_user_purpose", table_name="email_otps")
    op.drop_index("ix_email_otps_user_id", table_name="email_otps")
    op.drop_table("email_otps")
    op.drop_column("users", "email_verified_at")
    op.drop_column("users", "email_verified")
