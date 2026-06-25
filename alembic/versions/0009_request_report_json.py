"""request.report_json — gói báo cáo nghiệp vụ (self-test + 10.x) cho manager duyệt

Revision ID: 0009_request_report_json
Revises: 0008_drop_tenant_chat_platform
Create Date: 2026-06-25
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0009_request_report_json"
down_revision: Union[str, None] = "0008_drop_tenant_chat_platform"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("requests", sa.Column("report_json", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("requests", "report_json")
