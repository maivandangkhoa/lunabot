"""Duyệt/từ chối merge production qua web (/requests).

Cho **chủ workspace** (đăng nhập GitHub OAuth) duyệt request đang `AWAIT_MANAGER` ngay trên
web — tương đương manager bấm nút trong chat. KHÔNG nhân bản nghiệp vụ FSM: tái dùng nguyên
`orchestrator.handle_callback(mgr_approve/mgr_reject)` (tạo PR base→prod, merge, revert dev khi
từ chối, đóng PR, xoá nhánh, ghi Approval, báo requester).

Uỷ quyền: chủ tenant (`owner_github_id == session uid`) + CSRF. Approval gán cho user ADMIN/
MANAGER của tenant (tenant tạo qua wizard luôn có 1 ADMIN = chủ — provisioning.py). Báo
requester best-effort qua adapter đúng kênh; lỗi gửi KHÔNG làm hỏng merge (đã commit).

Tách khỏi routes.py để giữ mỗi file ≤500 LOC. Hook `_github/_git/_reply_adapter` để test
monkeypatch (không gọi GitHub/git thật).
"""
from __future__ import annotations

import hmac
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import bot_registry, git_ops
from app.channels.base import Button
from app.config import get_settings
from app.db import get_db
from app.github_app import GitHubApp
from app.models import Request as MaintRequest, RequestStatus, Tenant, User, UserRole
from app.orchestrator import Orchestrator, cb
from app.web.routes import _auth, _csrf, _form

log = logging.getLogger("luna.web.approvals")
router = APIRouter(tags=["web-approvals"])

# action web → callback orchestrator
_ACTIONS = {"approve": "mgr_approve", "reject": "mgr_reject"}


# ----- best-effort adapter báo requester -----
class _SafeAdapter:
    """Bọc adapter thật: nuốt lỗi `send` (merge đã commit, đừng để notify làm 500). Orchestrator
    chỉ gọi `.send` cho tin hướng-requester."""

    name = "web"

    def __init__(self, inner=None):
        self._inner = inner

    async def send(self, destination, text, buttons: list[list[Button]] | None = None):
        if self._inner is None or destination is None:
            return None
        try:
            return await self._inner.send(destination, text, buttons)
        except Exception as exc:  # noqa: BLE001 — báo requester là phụ, không chặn merge
            log.warning("web approval: báo requester lỗi: %s", exc)
            return None

    async def aclose(self):
        inner = self._inner
        if inner is not None and hasattr(inner, "aclose"):
            try:
                await inner.aclose()
            except Exception:  # noqa: BLE001
                pass


def _reply_adapter(db: Session, req: MaintRequest, s) -> _SafeAdapter:
    """Dựng adapter đúng kênh của requester (best-effort). Trả _SafeAdapter rỗng nếu không dựng được."""
    try:
        requester = db.get(User, req.requester_user_id)
        platform = req.origin_platform or (requester.platform if requester else "telegram")
        bot_id = requester.bot_id if requester else None
        if bot_id is not None:
            bot = bot_registry.get_bot(db, bot_id)
            if bot is not None and platform in ("telegram", "zalo"):
                return _SafeAdapter(bot_registry.build_adapter(bot, s))
        if platform == "telegram":
            from app.channels.telegram import TelegramAdapter
            return _SafeAdapter(TelegramAdapter(
                token=s.telegram_bot_token or "", bot_username=s.telegram_bot_username))
        if platform == "google_chat":
            from app.channels.google_chat import GoogleChatAdapter
            return _SafeAdapter(GoogleChatAdapter.from_settings(s))
        if platform == "zalo":
            from app.channels.zalo import ZaloAdapter
            return _SafeAdapter(ZaloAdapter.from_settings(s))
        if platform == "messenger":
            from app.channels.messenger import MessengerAdapter
            return _SafeAdapter(MessengerAdapter.from_settings(s))
    except Exception as exc:  # noqa: BLE001
        log.warning("web approval: dựng adapter báo requester lỗi: %s", exc)
    return _SafeAdapter(None)


def _github():
    """GitHub App (raise nếu chưa cấu hình). Hook riêng để test monkeypatch."""
    return GitHubApp.from_settings()


def _git():
    return git_ops


# ----- helpers uỷ quyền -----
def _owned_await_request(db: Session, data: dict, rid: int) -> MaintRequest | None:
    """Request thuộc tenant của owner đăng nhập + đang AWAIT_MANAGER (mới duyệt được)."""
    req = db.get(MaintRequest, rid)
    if req is None or req.status != RequestStatus.AWAIT_MANAGER:
        return None
    tn = db.get(Tenant, req.tenant_id)
    if tn is None or tn.owner_github_id != int(data["uid"]):
        return None
    return req


def _approver(db: Session, tenant_id: int) -> User | None:
    """User được gán Approval: ưu tiên ADMIN (chủ tenant), rồi MANAGER (id nhỏ nhất)."""
    for role in (UserRole.ADMIN, UserRole.MANAGER):
        u = db.scalars(
            select(User).where(User.tenant_id == tenant_id, User.role == role)
            .order_by(User.id)
        ).first()
        if u is not None:
            return u
    return None


async def _act(rid: int, request: Request, db: Session, action: str):
    data = _auth(request)
    if not data:
        return RedirectResponse("/", status_code=303)
    form = await _form(request)
    s = get_settings()
    if not hmac.compare_digest(form.get("csrf", ""), _csrf(data)):
        return RedirectResponse("/requests", status_code=303)
    req = _owned_await_request(db, data, rid)
    approver = _approver(db, req.tenant_id) if req is not None else None
    if req is None or approver is None:
        return RedirectResponse("/requests", status_code=303)

    github = adapter = None
    try:
        github = _github()
        adapter = _reply_adapter(db, req, s)
        orch = Orchestrator(db, adapter, github=github, git=_git())
        await orch.handle_callback(req, approver, cb(_ACTIONS[action], req.id))
    except Exception:  # noqa: BLE001 — đừng để lỗi merge/notify làm 500 trang
        log.exception("web approval %s req=%s lỗi", action, rid)
    finally:
        if adapter is not None:
            await adapter.aclose()
        if github is not None and hasattr(github, "aclose"):
            try:
                await github.aclose()
            except Exception:  # noqa: BLE001
                pass
    return RedirectResponse("/requests", status_code=303)


@router.post("/requests/{rid}/approve")
async def approve(rid: int, request: Request, db: Session = Depends(get_db)):
    return await _act(rid, request, db, "approve")


@router.post("/requests/{rid}/reject")
async def reject(rid: int, request: Request, db: Session = Depends(get_db)):
    return await _act(rid, request, db, "reject")
