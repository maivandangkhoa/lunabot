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
    Boolean,
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
    # Chủ tenant (người tạo qua web wizard, đăng nhập GitHub OAuth). NULL cho tenant seed cũ.
    owner_github_login: Mapped[str | None] = mapped_column(String(255))
    owner_github_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
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
    bots: Mapped[list[Bot]] = relationship(
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


class Bot(Base):
    """Một bot chat thuộc về 1 tenant — kết quả provisioning qua web wizard.

    `mode="shared"` dùng chung bot Luna toàn cục (user.bot_id để NULL); `mode="own"` là bot
    riêng do khách tạo (BYO token BotFather), token mã hoá Fernet, route qua webhook /bot_id.
    """

    __tablename__ = "bots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    platform: Mapped[str] = mapped_column(String(32), default="telegram")
    mode: Mapped[str] = mapped_column(String(16), default="shared")  # shared | own
    # Token bot riêng đã MÃ HOÁ (Fernet) — KHÔNG bao giờ lưu/log plaintext. NULL khi mode=shared.
    token_encrypted: Mapped[str | None] = mapped_column(Text)
    username: Mapped[str | None] = mapped_column(String(128))
    webhook_secret: Mapped[str | None] = mapped_column(String(128))
    deployment_mode: Mapped[str] = mapped_column(
        String(24), default="shared_instance"  # shared_instance | dedicated_container
    )
    container_name: Mapped[str | None] = mapped_column(String(128))
    display_name: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(
        String(16), default="active"  # active | provisioning | error
    )
    created_at: Mapped[datetime] = _created_at()

    tenant: Mapped[Tenant] = relationship(back_populates="bots")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    # Bot mà user này liên kết tới. NULL = bot Luna CHUNG toàn cục (tương thích user seed cũ).
    # Lookup user phải scope theo (bot_id, platform, platform_user_id) để cô lập tenant.
    bot_id: Mapped[int | None] = mapped_column(
        ForeignKey("bots.id", ondelete="CASCADE"), index=True
    )
    platform: Mapped[str] = mapped_column(String(32), default="telegram")
    # chat_id của user trên platform; null cho tới khi liên kết bằng link_token.
    platform_user_id: Mapped[str | None] = mapped_column(String(128), index=True)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role"), default=UserRole.EMPLOYEE
    )
    # Ngôn ngữ trả lời ưu tiên (ISO 639-1: vi/en/ko). NULL = chưa biết → fallback DEFAULT (vi).
    # Tự suy từ NỘI DUNG người dùng gõ (heuristic app.web.i18n.detect) lần đầu & cập nhật khi
    # đổi ngôn ngữ; trước khi có tín hiệu thì tạm theo language_code của client chat.
    language: Mapped[str | None] = mapped_column(String(8))
    display_name: Mapped[str | None] = mapped_column(String(255))
    link_token: Mapped[str | None] = mapped_column(String(128), unique=True, index=True)
    linked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Repo "đang chọn" — dùng khi tenant có nhiều repo để biết gửi yêu cầu vào repo nào.
    active_repo_id: Mapped[int | None] = mapped_column(
        ForeignKey("repositories.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = _created_at()

    tenant: Mapped[Tenant] = relationship(back_populates="users")

    __table_args__ = (
        # Scope theo bot: cùng 1 tài khoản chat có thể nói với nhiều bot khác tenant.
        # (bot_id NULL = bot chung; Postgres coi NULL là distinct nên uniqueness toàn cục
        #  cho bot chung được bảo đảm thêm ở tầng ứng dụng — link_user + lookup scoped.)
        UniqueConstraint(
            "bot_id", "platform", "platform_user_id", name="uq_platform_user"
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
    # Nơi khởi tạo request — để FSM trả lời đúng chỗ (DM hay group). NULL = request cũ ⇒
    # fallback DM requester (tương thích ngược). origin_is_group quyết notify manager ở group hay DM.
    origin_platform: Mapped[str | None] = mapped_column(String(32))
    origin_chat_id: Mapped[str | None] = mapped_column(String(128))
    origin_is_group: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", default=False
    )
    # Neo session Claude để --resume xuyên vòng đời.
    claude_session_id: Mapped[str | None] = mapped_column(String(128))
    branch_name: Mapped[str | None] = mapped_column(String(255))
    pr_number: Mapped[int | None] = mapped_column(Integer)
    pr_url: Mapped[str | None] = mapped_column(String(512))
    # SHA của merge commit khi PR vào dev — để revert dev nếu manager từ chối.
    dev_merge_sha: Mapped[str | None] = mapped_column(String(64))
    # Gói báo cáo nghiệp vụ (CLAUDE_WORKFLOW.md): loại thay đổi, nguyên nhân, giải pháp,
    # phạm vi, self-test, danh sách file + thống kê diff. Dựng ở EXECUTING, dùng khi mời
    # manager duyệt (sống qua deploy-gate nền + restart). NULL = request cũ/chưa có report.
    report_json: Mapped[dict | None] = mapped_column(JSONB)
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


class PlatformAdmin(Base):
    """Super admin của nền tảng — danh tính theo GitHub (giống danh tính đăng nhập web).

    KHÔNG đặt cờ trên `users` vì bảng đó là chat-user theo tenant (không có GitHub id).
    Danh tính web thực sự là `github_id` (session OAuth) ⇒ bảng riêng khoá theo nó.
    Có 1 dòng = là super admin; quản trị toàn hệ thống (xem mọi tenant). Seed dòng đầu
    bằng `python -m app.grant_admin <github_login|github_id>`.
    """

    __tablename__ = "platform_admins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    github_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    github_login: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = _created_at()
