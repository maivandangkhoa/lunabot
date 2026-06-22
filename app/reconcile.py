"""Reconcile request 'mồ côi'.

Bug nền: approve 1 request merge NGUYÊN nhánh `dev` → `main` (PR head=dev, base=main),
nhưng FSM chỉ đánh dấu đúng request được bấm. Các request khác đang nằm trong `dev` cũng
lên `main` theo nhưng vẫn kẹt ở AWAIT_MANAGER/MERGED_DEV → 'mồ côi': code đã release, nút
manager vẫn còn, bấm sau → PR rỗng → lỗi.

Module này KIỂM CHỨNG `dev_merge_sha` đã nằm trong `prod_branch` chưa (GitHub compare) rồi
mới đóng request + xoá nhánh + báo requester. Chỉ đụng request đã thật sự lên main; request
còn chờ hợp lệ (chưa lên main) GIỮ NGUYÊN. Idempotent — chạy lại an toàn.

    python -m app.reconcile           # dry-run: chỉ liệt kê, không đổi gì
    python -m app.reconcile --apply   # thực thi
"""
from __future__ import annotations

import asyncio
import logging
import sys
from dataclasses import dataclass
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.channels.base import ChannelAdapter
from app.config import Settings, get_settings
from app.db import SessionLocal
from app.github_app import GitHubApp
from app.models import (
    EventDirection,
    EventKind,
    Repository,
    Request,
    RequestEvent,
    RequestStatus,
    User,
)
from app.recovery import _build_adapter, _requester_pid
from app.web.i18n import set_lang, t

log = logging.getLogger("luna.reconcile")

# Trạng thái có thể bị 'mồ côi' khi 1 approve cuốn cả dev lên main.
_PENDING = (RequestStatus.AWAIT_MANAGER, RequestStatus.MERGED_DEV)


@dataclass
class ReconcileAction:
    request_id: int
    status_before: str
    verdict: str          # "released" | "pending" | "skipped:<lý do>"
    applied: bool = False


async def reconcile_orphans(
    settings: Settings,
    github: GitHubApp,
    *,
    apply: bool = False,
    db: Session | None = None,
    adapter_factory: Callable[[str | None], ChannelAdapter | None] | None = None,
) -> list[ReconcileAction]:
    """Quét request pending, đóng những cái `dev_merge_sha` đã nằm trong prod_branch.

    `apply=False` (mặc định): chỉ chẩn đoán, KHÔNG đổi DB / không xoá nhánh / không báo.
    `db`/`adapter_factory` inject được khi test.
    """
    own_db = db is None
    db = db or SessionLocal()
    factory = adapter_factory or (lambda p: _build_adapter(p, settings))
    cache: dict[str | None, ChannelAdapter | None] = {}
    built: list[ChannelAdapter] = []
    actions: list[ReconcileAction] = []
    try:
        reqs = list(db.scalars(select(Request).where(Request.status.in_(_PENDING))).all())
        for req in reqs:
            act = ReconcileAction(req.id, req.status.value, "pending")
            repo = db.get(Repository, req.repo_id)
            if not req.dev_merge_sha or not repo or not repo.gh_installation_id:
                act.verdict = "skipped:thiếu sha/installation"
                actions.append(act)
                continue
            try:
                released = await github.commit_reachable_from(
                    repo.gh_installation_id, repo.repo_full_name,
                    branch=repo.prod_branch, sha=req.dev_merge_sha)
            except Exception as exc:  # noqa: BLE001 — 1 repo lỗi không chặn cả lô
                log.warning("reconcile: compare req %s lỗi: %s", req.id, exc)
                act.verdict = "skipped:compare lỗi"
                actions.append(act)
                continue
            if not released:
                actions.append(act)            # pending hợp lệ — giữ nguyên
                continue
            act.verdict = "released"
            if apply:
                _close_released(db, req)
                await _cleanup_branch(github, repo, req)
                await _notify(db, req, repo, factory, cache, built)
                act.applied = True
            actions.append(act)
        return actions
    finally:
        for adapter in built:
            try:
                await adapter.aclose()
            except Exception:  # noqa: BLE001
                pass
        if own_db:
            db.close()


def _close_released(db: Session, req: Request) -> None:
    """MERGED_MAIN → CLOSED + ghi event SYSTEM (KHÔNG ghi Approval: không có người duyệt thật)."""
    req.status = RequestStatus.MERGED_MAIN
    db.add(RequestEvent(
        request_id=req.id, kind=EventKind.SYSTEM, direction=EventDirection.OUT,
        payload_json={"reconcile": "already_on_main", "dev_merge_sha": req.dev_merge_sha},
    ))
    req.status = RequestStatus.CLOSED
    db.commit()
    log.info("reconcile: đóng request %s (đã trên main)", req.id)


async def _cleanup_branch(github: GitHubApp, repo: Repository, req: Request) -> None:
    if not req.branch_name:
        return
    try:
        await github.delete_branch(repo.gh_installation_id, repo.repo_full_name, req.branch_name)
    except Exception as exc:  # noqa: BLE001 — best-effort
        log.warning("reconcile: xoá nhánh %s req %s lỗi: %s", req.branch_name, req.id, exc)


async def _notify(
    db: Session, req: Request, repo: Repository,
    factory: Callable[[str | None], ChannelAdapter | None],
    cache: dict[str | None, ChannelAdapter | None],
    built: list[ChannelAdapter],
) -> None:
    target = req.origin_chat_id or _requester_pid(db, req)
    if not target:
        return
    if req.origin_platform not in cache:
        cache[req.origin_platform] = factory(req.origin_platform)
        if cache[req.origin_platform] is not None:
            built.append(cache[req.origin_platform])
    adapter = cache[req.origin_platform]
    if adapter is None:
        return
    requester = db.get(User, req.requester_user_id)
    set_lang(requester.language if requester else None)  # trả lời đúng ngôn ngữ requester
    try:
        await adapter.send(
            target, t("reconcile.released", rid=req.id, title=req.title, prod=repo.prod_branch))
    except Exception:  # noqa: BLE001 — notify best-effort
        log.exception("reconcile: notify request %s lỗi", req.id)


async def _main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    apply = "--apply" in sys.argv[1:]
    settings = get_settings()
    github = GitHubApp.from_settings()
    try:
        actions = await reconcile_orphans(settings, github, apply=apply)
    finally:
        await github.aclose()
    mode = "ÁP DỤNG" if apply else "DRY-RUN (thêm --apply để thực thi)"
    print(f"\n=== Reconcile {mode} ===")
    for a in actions:
        flag = "✓ đã đóng" if a.applied else ("→ sẽ đóng" if a.verdict == "released" else a.verdict)
        print(f"  #{a.request_id:<5} {a.status_before:<14} {flag}")
    n_rel = sum(1 for a in actions if a.verdict == "released")
    print(f"\n{len(actions)} request pending; {n_rel} đã trên main"
          f"{' (đã đóng)' if apply else ' (chưa đụng — chạy --apply)'}.")


if __name__ == "__main__":
    asyncio.run(_main())
