"""request.dev_merge_sha — SHA merge commit vào dev, để revert khi manager từ chối

Revision ID: 0004_request_dev_merge_sha
Revises: 0003_request_origin
Create Date: 2026-06-18
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0004_request_dev_merge_sha"
down_revision: Union[str, None] = "0003_request_origin"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("requests", sa.Column("dev_merge_sha", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("requests", "dev_merge_sha")
