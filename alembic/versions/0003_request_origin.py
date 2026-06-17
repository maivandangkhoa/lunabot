"""request.origin_* — nơi khởi tạo request (DM hay group) để FSM trả lời đúng chỗ

Revision ID: 0003_request_origin
Revises: 0002_user_active_repo
Create Date: 2026-06-17
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0003_request_origin"
down_revision: Union[str, None] = "0002_user_active_repo"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("requests", sa.Column("origin_platform", sa.String(length=32), nullable=True))
    op.add_column("requests", sa.Column("origin_chat_id", sa.String(length=128), nullable=True))
    op.add_column(
        "requests",
        sa.Column("origin_is_group", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("requests", "origin_is_group")
    op.drop_column("requests", "origin_chat_id")
    op.drop_column("requests", "origin_platform")
