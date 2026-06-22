"""users.language — ngôn ngữ trả lời ưu tiên (vi/en/ko), suy từ client chat

Revision ID: 0006_user_language
Revises: 0005_bots_and_oauth
Create Date: 2026-06-20
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0006_user_language"
down_revision: Union[str, None] = "0005_bots_and_oauth"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("language", sa.String(length=8), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "language")
