"""initial schema (M0)

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-15

Tạo toàn bộ schema multi-tenant: tenants, repositories, users, requests,
request_events, approvals + các enum FSM/role/event/approval.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


request_status = sa.Enum(
    "NEW", "ANALYZING", "CLARIFYING", "PLAN_REVIEW", "EXECUTING", "VERIFY",
    "MERGED_DEV", "AWAIT_MANAGER", "MERGED_MAIN", "CLOSED", "CANCELLED",
    name="request_status",
)
user_role = sa.Enum("EMPLOYEE", "MANAGER", "ADMIN", name="user_role")
event_kind = sa.Enum(
    "MSG", "CLARIFY", "PLAN", "CONFIRM", "VERIFY", "APPROVE", "SYSTEM",
    name="event_kind",
)
event_direction = sa.Enum("IN", "OUT", name="event_direction")
approval_type = sa.Enum("MERGE_TO_MAIN", name="approval_type")
approval_decision = sa.Enum("APPROVED", "REJECTED", name="approval_decision")


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("plan", sa.String(length=64), server_default="free"),
        sa.Column("chat_platform", sa.String(length=32), server_default="telegram"),
        sa.Column("settings_json", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "repositories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("gh_installation_id", sa.BigInteger(), nullable=True),
        sa.Column("repo_full_name", sa.String(length=255), nullable=False),
        sa.Column("base_branch", sa.String(length=128), server_default="dev"),
        sa.Column("prod_branch", sa.String(length=128), server_default="main"),
        sa.Column("settings_json", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "repo_full_name", name="uq_repo_per_tenant"),
    )
    op.create_index("ix_repositories_tenant_id", "repositories", ["tenant_id"])

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(length=32), server_default="telegram"),
        sa.Column("platform_user_id", sa.String(length=128), nullable=True),
        sa.Column("role", user_role, server_default="EMPLOYEE"),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("link_token", sa.String(length=128), nullable=True),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("link_token", name="uq_users_link_token"),
        sa.UniqueConstraint("platform", "platform_user_id", name="uq_platform_user"),
    )
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])
    op.create_index("ix_users_platform_user_id", "users", ["platform_user_id"])
    op.create_index("ix_users_link_token", "users", ["link_token"])

    op.create_table(
        "requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("repo_id", sa.Integer(), nullable=False),
        sa.Column("requester_user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("status", request_status, server_default="NEW"),
        sa.Column("claude_session_id", sa.String(length=128), nullable=True),
        sa.Column("branch_name", sa.String(length=255), nullable=True),
        sa.Column("pr_number", sa.Integer(), nullable=True),
        sa.Column("pr_url", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["repo_id"], ["repositories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requester_user_id"], ["users.id"]),
    )
    op.create_index("ix_requests_tenant_id", "requests", ["tenant_id"])
    op.create_index("ix_requests_repo_id", "requests", ["repo_id"])
    op.create_index("ix_requests_status", "requests", ["status"])

    op.create_table(
        "request_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_id", sa.Integer(), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("kind", event_kind, nullable=False),
        sa.Column("direction", event_direction, nullable=False),
        sa.Column("payload_json", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["request_id"], ["requests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
    )
    op.create_index("ix_request_events_request_id", "request_events", ["request_id"])

    op.create_table(
        "approvals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_id", sa.Integer(), nullable=False),
        sa.Column("approver_user_id", sa.Integer(), nullable=False),
        sa.Column("type", approval_type, server_default="MERGE_TO_MAIN"),
        sa.Column("decision", approval_decision, nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["request_id"], ["requests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["approver_user_id"], ["users.id"]),
    )
    op.create_index("ix_approvals_request_id", "approvals", ["request_id"])


def downgrade() -> None:
    op.drop_table("approvals")
    op.drop_table("request_events")
    op.drop_table("requests")
    op.drop_table("users")
    op.drop_table("repositories")
    op.drop_table("tenants")

    for enum in (
        approval_decision, approval_type, event_direction, event_kind,
        user_role, request_status,
    ):
        enum.drop(op.get_bind(), checkfirst=True)
