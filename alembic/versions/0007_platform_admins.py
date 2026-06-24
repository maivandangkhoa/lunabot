"""platform_admins — super admin nền tảng (danh tính GitHub), xem mọi tenant

Revision ID: 0007_platform_admins
Revises: 0006_user_language
Create Date: 2026-06-24
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0007_platform_admins"
down_revision: Union[str, None] = "0006_user_language"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "platform_admins",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("github_id", sa.BigInteger(), nullable=False),
        sa.Column("github_login", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_platform_admins_github_id", "platform_admins", ["github_id"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_platform_admins_github_id", table_name="platform_admins")
    op.drop_table("platform_admins")
