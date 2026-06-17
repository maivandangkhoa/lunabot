"""Data model (Postgres) — multi-tenant.

Thực thể trung tâm: `Request` (1 ticket bảo trì) chạy qua FSM `RequestStatus`,
neo `claude_session_id` để `--resume` giữ ngữ cảnh xuyên vòng đời.

Bảng: tenants, repositories, users, requests, request_events, approvals.
"""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# JSONB trên Postgres (prod), JSON thường trên các dialect khác (SQLite trong test).
JSONB = JSON().with_variant(PG_JSONB(), "postgresql")


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #
class RequestStatus(str, enum.Enum):
    """FSM — trái tim hệ thống. Xem tasks/todo.md để biết transition đầy đủ."""

    NEW = "new"
    ANALYZING = "analyzing"
    CLARIFYING = "clarifying"
    PLAN_REVIEW = "plan_review"
    EXECUTING = "executing"
    VERIFY = "verify"
    MERGED_DEV = "merged_dev"
    AWAIT_MANAGER = "await_manager"
    MERGED_MAIN = "merged_main"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class UserRole(str, enum.Enum):
    EMPLOYEE = "employee"
    MANAGER = "manager"
    ADMIN = "admin"


class EventKind(str, enum.Enum):
    MSG = "msg"
    CLARIFY = "clarify"
    PLAN = "plan"
    CONFIRM = "confirm"
    VERIFY = "verify"
    APPROVE = "approve"
    SYSTEM = "system"


class EventDirection(str, enum.Enum):
    IN = "in"
    OUT = "out"


class ApprovalType(str, enum.Enum):
    MERGE_TO_MAIN = "merge_to_main"


class ApprovalDecision(str, enum.Enum):
    APPROVED = "approved"
    REJECTED = "rejected"


# Helper: cột timestamps dùng lại
def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


# --------------------------------------------------------------------------- #
# Tables
# --------------------------------------------------------------------------- #
class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    plan: Mapped[str] = mapped_column(String(64), default="free")
    chat_platform: Mapped[str] = mapped_column(String(32), default="telegram")
    settings_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = _created_at()

    repositories: Mapped[list[Repository]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )
    users: Mapped[list[User]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )
    requests: Mapped[list[Request]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    gh_installation_id: Mapped[int | None] = mapped_column(BigInteger)
    repo_full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    base_branch: Mapped[str] = mapped_column(String(128), default="dev")
    prod_branch: Mapped[str] = mapped_column(String(128), default="main")
    settings_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = _created_at()

    tenant: Mapped[Tenant] = relationship(back_populates="repositories")
    requests: Mapped[list[Request]] = relationship(back_populates="repository")

    __table_args__ = (
        UniqueConstraint("tenant_id", "repo_full_name", name="uq_repo_per_tenant"),
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    platform: Mapped[str] = mapped_column(String(32), default="telegram")
    # chat_id của user trên platform; null cho tới khi liên kết bằng link_token.
    platform_user_id: Mapped[str | None] = mapped_column(String(128), index=True)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role"), default=UserRole.EMPLOYEE
    )
    display_name: Mapped[str | None] = mapped_column(String(255))
    link_token: Mapped[str | None] = mapped_column(String(128), unique=True, index=True)
    linked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()

    tenant: Mapped[Tenant] = relationship(back_populates="users")

    __table_args__ = (
        UniqueConstraint(
            "platform", "platform_user_id", name="uq_platform_user"
        ),
    )


class Request(Base):
    """Ticket bảo trì — thực thể trung tâm, chạy qua FSM RequestStatus."""

    __tablename__ = "requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    repo_id: Mapped[int] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), index=True
    )
    requester_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    status: Mapped[RequestStatus] = mapped_column(
        Enum(RequestStatus, name="request_status"),
        default=RequestStatus.NEW,
        index=True,
    )
    # Neo session Claude để --resume xuyên vòng đời.
    claude_session_id: Mapped[str | None] = mapped_column(String(128))
    branch_name: Mapped[str | None] = mapped_column(String(255))
    pr_number: Mapped[int | None] = mapped_column(Integer)
    pr_url: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    tenant: Mapped[Tenant] = relationship(back_populates="requests")
    repository: Mapped[Repository] = relationship(back_populates="requests")
    events: Mapped[list[RequestEvent]] = relationship(
        back_populates="request", cascade="all, delete-orphan"
    )
    approvals: Mapped[list[Approval]] = relationship(
        back_populates="request", cascade="all, delete-orphan"
    )


class RequestEvent(Base):
    """Audit + lịch sử hội thoại của 1 request."""

    __tablename__ = "request_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[int] = mapped_column(
        ForeignKey("requests.id", ondelete="CASCADE"), index=True
    )
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[EventKind] = mapped_column(Enum(EventKind, name="event_kind"))
    direction: Mapped[EventDirection] = mapped_column(
        Enum(EventDirection, name="event_direction")
    )
    payload_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = _created_at()

    request: Mapped[Request] = relationship(back_populates="events")


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[int] = mapped_column(
        ForeignKey("requests.id", ondelete="CASCADE"), index=True
    )
    approver_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    type: Mapped[ApprovalType] = mapped_column(
        Enum(ApprovalType, name="approval_type"),
        default=ApprovalType.MERGE_TO_MAIN,
    )
    decision: Mapped[ApprovalDecision] = mapped_column(
        Enum(ApprovalDecision, name="approval_decision")
    )
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()

    request: Mapped[Request] = relationship(back_populates="approvals")
