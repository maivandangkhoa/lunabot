"""bots table + users.bot_id (scope per-bot) + tenants.owner_github_* (web wizard)

Revision ID: 0005_bots_and_oauth
Revises: 0004_request_dev_merge_sha
Create Date: 2026-06-18
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0005_bots_and_oauth"
down_revision: Union[str, None] = "0004_request_dev_merge_sha"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("token_encrypted", sa.Text(), nullable=True),
        sa.Column("username", sa.String(length=128), nullable=True),
        sa.Column("webhook_secret", sa.String(length=128), nullable=True),
        sa.Column("deployment_mode", sa.String(length=24), nullable=False),
        sa.Column("container_name", sa.String(length=128), nullable=True),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bots_tenant_id", "bots", ["tenant_id"])

    # tenants: chủ sở hữu (GitHub OAuth)
    op.add_column(
        "tenants", sa.Column("owner_github_login", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "tenants", sa.Column("owner_github_id", sa.BigInteger(), nullable=True)
    )
    op.create_index("ix_tenants_owner_github_id", "tenants", ["owner_github_id"])

    # users: scope theo bot. Đổi unique constraint (platform, platform_user_id)
    # → (bot_id, platform, platform_user_id).
    op.add_column("users", sa.Column("bot_id", sa.Integer(), nullable=True))
    op.create_index("ix_users_bot_id", "users", ["bot_id"])
    op.create_foreign_key(
        "fk_users_bot_id", "users", "bots", ["bot_id"], ["id"], ondelete="CASCADE"
    )
    op.drop_constraint("uq_platform_user", "users", type_="unique")
    op.create_unique_constraint(
        "uq_platform_user", "users", ["bot_id", "platform", "platform_user_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_platform_user", "users", type_="unique")
    op.create_unique_constraint(
        "uq_platform_user", "users", ["platform", "platform_user_id"]
    )
    op.drop_constraint("fk_users_bot_id", "users", type_="foreignkey")
    op.drop_index("ix_users_bot_id", table_name="users")
    op.drop_column("users", "bot_id")

    op.drop_index("ix_tenants_owner_github_id", table_name="tenants")
    op.drop_column("tenants", "owner_github_id")
    op.drop_column("tenants", "owner_github_login")

    op.drop_index("ix_bots_tenant_id", table_name="bots")
    op.drop_table("bots")
