"""drop tenants.chat_platform — field chết (luôn = 'telegram')

Kênh chat thực của tenant suy từ Bot.platform (nguồn sự thật). Cột này chỉ giữ giá
trị default 'telegram', không bao giờ được cập nhật → gây nhầm lẫn trên /admin.

Revision ID: 0008_drop_tenant_chat_platform
Revises: 0007_platform_admins
Create Date: 2026-06-24
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0008_drop_tenant_chat_platform"
down_revision: Union[str, None] = "0007_platform_admins"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("tenants", "chat_platform")


def downgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column(
            "chat_platform",
            sa.String(length=32),
            server_default="telegram",
            nullable=False,
        ),
    )
