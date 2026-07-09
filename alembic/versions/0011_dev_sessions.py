"""dev_sessions — phiên dev-mode per (user, repo): neo claude_session_id + trạng thái chờ
xác nhận deploy main. Xem tasks/dev-mode.md.

Revision ID: 0011_dev_sessions
Revises: 0010_usage_records
Create Date: 2026-07-09
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0011_dev_sessions"
down_revision: Union[str, None] = "0010_usage_records"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dev_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("repo_id", sa.Integer(),
                  sa.ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("claude_session_id", sa.String(128), nullable=True),
        sa.Column("pending_json", JSONB(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "repo_id", name="uq_dev_session"),
    )
    op.create_index("ix_dev_sessions_user_id", "dev_sessions", ["user_id"])
    op.create_index("ix_dev_sessions_repo_id", "dev_sessions", ["repo_id"])


def downgrade() -> None:
    op.drop_index("ix_dev_sessions_repo_id", table_name="dev_sessions")
    op.drop_index("ix_dev_sessions_user_id", table_name="dev_sessions")
    op.drop_table("dev_sessions")
