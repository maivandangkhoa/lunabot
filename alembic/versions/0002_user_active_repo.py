"""user.active_repo_id — repo đang chọn (cho tenant nhiều repo)

Revision ID: 0002_user_active_repo
Revises: 0001_initial
Create Date: 2026-06-17
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0002_user_active_repo"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("active_repo_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_users_active_repo", "users", "repositories",
        ["active_repo_id"], ["id"], ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_users_active_repo", "users", type_="foreignkey")
    op.drop_column("users", "active_repo_id")
