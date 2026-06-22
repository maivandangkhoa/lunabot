"""Huỷ request 'kẹt' do bug định tuyến thread Google Chat cũ.

Bug nền: adapter Google Chat từng gán `chat_id = space` (cả room) thay vì THREAD, nên
mọi thread trong cùng room chia sẻ một `origin_chat_id` → thực chất "1 ROOM = 1 request",
chặn user mở yêu cầu mới (bot báo "thread này đang xử lý #N"). Bản vá đổi sang
`chat_id = thread` (`spaces/AAA/threads/T1`); các request CŨ vẫn lưu `origin_chat_id` dạng
space (không có `/threads/`) → user không chạm tới được nữa → 'kẹt'.

Module này tìm request Google Chat trong GROUP đang BLOCKING có `origin_chat_id` dạng space
cũ, huỷ (→ CANCELLED), dọn nhánh/PR best-effort, rồi báo requester. Idempotent: chạy lại
không còn gì để huỷ. KHÔNG đụng request đã có `/threads/` (định tuyến mới, hợp lệ).

    python -m app.cancel_stuck_threads           # dry-run: chỉ liệt kê, không đổi gì
    python -m app.cancel_stuck_threads --apply   # thực thi
"""
from __future__ import annotations

import asyncio
import logging
import sys
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.cleanup import cleanup_branch
from app.config import get_settings
from app.db import SessionLocal
from app.github_app import GitHubApp
from app.models import EventDirection, EventKind, Request, RequestStatus, User
from app.orchestrator import BLOCKING_STATUSES, Orchestrator
from app.recovery import _build_adapter
from app.web.i18n import set_lang, t

log = logging.getLogger("luna.cancel_stuck")


@dataclass
class CancelAction:
    request_id: int
    status_before: str
    origin_chat_id: str | None
    applied: bool = False
    warns: tuple[str, ...] = ()


def _is_stuck(req: Request) -> bool:
    """Group Google Chat + BLOCKING + origin_chat_id dạng space cũ (chưa có '/threads/')."""
    return (
        req.origin_platform == "google_chat"
        and req.origin_is_group
        and req.status in BLOCKING_STATUSES
        and not (req.origin_chat_id or "").count("/threads/")
    )


async def cancel_stuck(
    *,
    apply: bool = False,
    db: Session | None = None,
    github: GitHubApp | None = None,
    adapter=None,
) -> list[CancelAction]:
    """Quét & huỷ request kẹt. `apply=False` (mặc định): chỉ liệt kê, KHÔNG đổi DB.
    `db`/`github`/`adapter` inject được khi test."""
    own_db = db is None
    db = db or SessionLocal()
    if adapter is None:
        adapter = _build_adapter("google_chat", get_settings())
    orch = Orchestrator(db, adapter, github=github) if adapter else None
    actions: list[CancelAction] = []
    try:
        reqs = [r for r in db.scalars(
            select(Request).where(Request.status.in_(BLOCKING_STATUSES))
            .order_by(Request.id)).all() if _is_stuck(r)]
        for req in reqs:
            act = CancelAction(req.id, req.status.value, req.origin_chat_id)
            if apply and orch is not None:
                # Dọn side-effect git trước (nếu đã có nhánh/PR); không revert dev (BLOCKING
                # không có trạng thái đã-merge-dev). Best-effort: lỗi chỉ gom cảnh báo.
                try:
                    act.warns = tuple(await cleanup_branch(orch, req, revert_dev=False))
                except Exception as exc:  # noqa: BLE001 — 1 repo lỗi không chặn cả lô
                    log.warning("cancel_stuck: dọn nhánh req %s lỗi: %s", req.id, exc)
                orch._event(req, EventKind.SYSTEM, EventDirection.OUT,
                            action="cancel_stuck_thread")
                orch._set_status(req, RequestStatus.CANCELLED)
                db.commit()
                await _notify(db, req, adapter)
                act.applied = True
            actions.append(act)
        return actions
    finally:
        if adapter is not None:
            try:
                await adapter.aclose()
            except Exception:  # noqa: BLE001
                pass
        if own_db:
            db.close()


async def _notify(db: Session, req: Request, adapter) -> None:
    target = req.origin_chat_id
    if not target:
        return
    requester = db.get(User, req.requester_user_id)
    set_lang(requester.language if requester else None)  # đúng ngôn ngữ requester
    try:
        await adapter.send(target, t("cancel_stuck.cancelled", rid=req.id, title=req.title))
    except Exception:  # noqa: BLE001 — notify best-effort
        log.exception("cancel_stuck: notify request %s lỗi", req.id)


async def _main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    apply = "--apply" in sys.argv[1:]
    github = GitHubApp.from_settings()
    try:
        actions = await cancel_stuck(apply=apply, github=github)
    finally:
        await github.aclose()
    mode = "ÁP DỤNG" if apply else "DRY-RUN (thêm --apply để thực thi)"
    print(f"\n=== Cancel stuck threads {mode} ===")
    for a in actions:
        flag = "✓ đã huỷ" if a.applied else "→ sẽ huỷ"
        warns = f"  ⚠ {'; '.join(a.warns)}" if a.warns else ""
        print(f"  #{a.request_id:<5} {a.status_before:<14} {a.origin_chat_id or '-':<28} {flag}{warns}")
    print(f"\n{len(actions)} request kẹt"
          f"{' (đã huỷ)' if apply else ' (chưa đụng — chạy --apply)'}.")


if __name__ == "__main__":
    asyncio.run(_main())
