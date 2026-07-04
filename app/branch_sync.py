"""Đồng bộ nhánh prod→base: phát hiện phân kỳ lúc nhận request + gỡ xung đột merge release.

Bối cảnh: mọi thay đổi lên prod đáng lẽ đi qua bot (base→prod), nhưng human có thể push
hotfix thẳng prod → base thiếu commit đó. Hệ quả: (1) bot làm việc trên code cũ hơn
production; (2) merge release base→prod dính conflict thật (405 "merge conflict" — khác
race "Base branch was modified").

Nguyên tắc: KHÔNG tự ý đụng lịch sử git — luôn báo người dùng và chờ XÁC NHẬN tường minh
trước khi merge prod vào base (cả 2 tình huống). Trạng thái chờ-xác-nhận lưu trong
`Request.report_json` (reassign dict để SQLAlchemy bắt thay đổi JSONB):
  - report_json["prod_sync"]   = {"state": "asked"|"confirmed"|"declined"|"failed"}
    (tiêu thụ trước EXECUTING — nơi build_report ghi đè report_json — nên không đụng nhau)
  - report_json["conflict_fix"] = {"offered": bool, "running": bool}
    (chỉ ghi ở AWAIT_MANAGER, sau lần build_report cuối)
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app import prompts, usage
from app.channels.base import Button
from app.claude_runner import PermissionMode
from app.github_app import GitHubAppError
from app.models import Repository, Request, RequestStatus, User, UserRole
from app.textnorm import strip_symbols
from app.web.i18n import set_lang_for, t

if TYPE_CHECKING:  # pragma: no cover
    from app.orchestrator import Orchestrator

log = logging.getLogger("luna.branch_sync")

SYNC_KEY = "prod_sync"
CONFLICT_KEY = "conflict_fix"

# Từ xác nhận/từ chối cho câu hỏi sync (định nghĩa tại đây, không import từ dispatcher —
# tránh vòng import dispatcher→orchestrator→branch_sync). Chỉ merge khi khớp _W_YES.
_W_YES = {"ok", "oke", "okay", "đồng ý", "dong y", "duyệt", "duyet", "yes", "y",
          "gộp", "gop", "gộp vào", "gop vao", "merge", "có", "co", "네", "예"}
_W_NO = {"không", "khong", "no", "n", "bỏ qua", "bo qua", "thôi", "thoi", "skip",
         "cứ làm tiếp", "cu lam tiep", "아니요", "아니"}


def _get(req: Request, key: str) -> dict:
    return (req.report_json or {}).get(key) or {}


def _set(orch: "Orchestrator", req: Request, key: str, value: dict) -> None:
    req.report_json = {**(req.report_json or {}), key: value}
    orch.db.commit()


# ---------------- Feature 1: phân kỳ lúc nhận request ----------------

async def check_divergence_at_intake(
    orch: "Orchestrator", req: Request, repo: Repository, repo_dir,
) -> bool:
    """Gọi từ _analyze ngay sau clone OK. True = đã hỏi requester và DỪNG (caller return).

    Đã có quyết định (confirmed/declined/failed) hoặc không phân kỳ → False (đi tiếp).
    state=="asked" (re-entry qua "chạy lại") → hỏi lại kèm nút mới.
    Lỗi khi check → log warning + False: check phân kỳ là phụ trợ, không chặn luồng chính.
    """
    state = _get(req, SYNC_KEY).get("state")
    if state in ("confirmed", "declined", "failed"):
        return False
    try:
        n = await orch.git.divergence(repo_dir, repo.base_branch, repo.prod_branch)
    except Exception as exc:  # noqa: BLE001
        log.warning("check phân kỳ req %s lỗi: %s", req.id, exc)
        return False
    if n <= 0:
        return False

    _set(orch, req, SYNC_KEY, {"state": "asked"})
    orch._set_status(req, RequestStatus.CLARIFYING)
    orch.db.commit()
    await orch._say(
        req, orch._requester(req),
        t("sync.diverged_ask", prod=repo.prod_branch, base=repo.base_branch, n=n),
        buttons=[[
            Button(t("sync.btn.yes"), f"sync_yes:{req.id}"),
            Button(t("sync.btn.no"), f"sync_no:{req.id}"),
        ]])
    return True


async def maybe_handle_sync_reply(orch: "Orchestrator", req: Request, text: str) -> bool:
    """Gọi từ handle_message khi CLARIFYING. Chỉ hoạt động khi đang chờ trả lời sync.

    Khớp _W_YES → confirm+sync. Mọi text khác → declined (chỉ merge khi xác nhận TƯỜNG MINH);
    nếu text không phải từ yes/no thuần thì trả False để caller chuyển tiếp làm clarification.
    """
    if _get(req, SYNC_KEY).get("state") != "asked":
        return False
    # strip_symbols: Messenger/Zalo echo nhãn nút thành TEXT "✅ Gộp vào" — phải bỏ
    # emoji/ký hiệu trước khi khớp, nếu không click nút bị đọc nhầm thành từ chối.
    low = strip_symbols(text).lower()
    if low in _W_YES:
        await on_sync_confirm(orch, req)
        return True
    _set(orch, req, SYNC_KEY, {"state": "declined"})
    repo = orch._repo(req)
    await orch._say(req, orch._requester(req), t("sync.declined", prod=repo.prod_branch))
    if low in _W_NO:
        await orch._analyze(req)  # từ chối thuần → vẫn phải phân tích tiếp
        return True
    return False  # text tự do → caller đưa tiếp vào _analyze làm câu trả lời làm rõ


async def on_sync_confirm(orch: "Orchestrator", req: Request) -> None:
    """Nút sync_yes / text yes: merge prod vào base rồi phân tích tiếp."""
    if _get(req, SYNC_KEY).get("state") != "asked":  # double-click / đã quyết
        return
    repo = orch._repo(req)
    requester = orch._requester(req)
    ok = await sync_prod_into_base(orch, req, repo)
    if ok:
        _set(orch, req, SYNC_KEY, {"state": "confirmed"})
        await orch._say(req, requester, t("sync.done", prod=repo.prod_branch))
    else:
        # Không để request kẹt vì sync lỗi: báo rõ rồi vẫn làm tiếp trên base hiện tại.
        _set(orch, req, SYNC_KEY, {"state": "failed"})
        await orch._say(req, requester, t("sync.failed", prod=repo.prod_branch))
    await orch._analyze(req)


async def on_sync_decline(orch: "Orchestrator", req: Request) -> None:
    """Nút sync_no: ghi nhận từ chối (không hỏi lại) rồi phân tích tiếp trên base hiện tại."""
    if _get(req, SYNC_KEY).get("state") != "asked":
        return
    repo = orch._repo(req)
    _set(orch, req, SYNC_KEY, {"state": "declined"})
    await orch._say(req, orch._requester(req), t("sync.declined", prod=repo.prod_branch))
    await orch._analyze(req)


# ---------------- lõi chung: merge prod vào base (Claude resolve nếu conflict) ----------------

async def sync_prod_into_base(orch: "Orchestrator", req: Request, repo: Repository) -> bool:
    """Merge origin/prod vào base local rồi push. Conflict → Claude resolve → commit + push.

    Thất bại đường nào cũng abort_merge để worktree sạch cho lần sau. Trả True/False.
    """
    from app.orchestrator import _repo_locks

    repo_dir = None
    async with _repo_locks[repo.id]:
        try:
            repo_dir = await orch._ensure_repo_cloned(repo)
            clean = await orch.git.merge_branch(repo_dir, repo.base_branch, repo.prod_branch)
            if not clean:
                if not await _claude_resolve(orch, req, repo, repo_dir):
                    await orch.git.abort_merge(repo_dir)
                    return False
                await orch.git.commit_all(
                    repo_dir, f"luna: merge {repo.prod_branch} into {repo.base_branch} (req-{req.id})")
            await orch.git.push_branch(repo_dir, repo.base_branch)
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("sync %s→%s req %s lỗi: %s",
                        repo.prod_branch, repo.base_branch, req.id, exc)
            if repo_dir is not None:
                try:
                    await orch.git.abort_merge(repo_dir)
                except Exception:  # noqa: BLE001 — dọn best-effort
                    pass
            return False


async def _claude_resolve(
    orch: "Orchestrator", req: Request, repo: Repository, repo_dir,
) -> bool:
    """Claude gỡ conflict marker (giữ CẢ HAI ý định). True khi hết marker/unmerged."""
    files = await orch.git.conflicted_files(repo_dir)
    if not files:
        return True
    sysp = prompts.conflict_system_prompt(
        repo.repo_full_name, repo.base_branch, repo.prod_branch, [repo.prod_branch])
    res = await orch.claude_run(
        prompt=prompts.conflict_fix_prompt(files), cwd=repo_dir,
        permission_mode=PermissionMode.BYPASS,
        session_id=req.claude_session_id, system_prompt=sysp)
    req.claude_session_id = res.session_id
    usage.record(orch.db, tenant_id=repo.tenant_id, request_id=req.id,
                 phase="conflict_fix", res=res)
    orch.db.commit()
    if not res.ok:
        log.warning("conflict_fix req %s: Claude lỗi: %s", req.id, res.result[:300])
        return False
    remaining = await orch.git.conflicted_files(repo_dir)
    if remaining or orch.git.has_conflict_markers(repo_dir, files):
        log.warning("conflict_fix req %s: còn conflict sau khi Claude chạy", req.id)
        return False
    return True


# ---------------- Feature 2: conflict khi merge release base→prod ----------------

def is_merge_conflict_405(exc: Exception) -> bool:
    """Phân biệt 405 conflict THẬT với 405 race 'Base branch was modified' (retry được)."""
    if not isinstance(exc, GitHubAppError) or exc.status_code != 405:
        return False
    low = str(exc).lower()
    return "merge conflict" in low or "not mergeable" in low


async def ask_conflict_fix(
    orch: "Orchestrator", req: Request, repo: Repository, target: str | None,
) -> None:
    """Mời manager xác nhận xử lý conflict. Status GIỮ AWAIT_MANAGER (duyệt lại/từ chối vẫn được)."""
    _set(orch, req, CONFLICT_KEY, {"offered": True, "running": False})
    await orch.adapter.send(
        target or orch._reply_target(req),
        t("sync.conflict_ask", id=req.id, prod=repo.prod_branch),
        [[
            Button(t("sync.btn.fix_conflict"), f"conflict_fix:{req.id}"),
            Button(t("ops.btn.reject"), f"mgr_reject:{req.id}"),
        ]])


async def resolve_conflict_and_merge(
    orch: "Orchestrator", req: Request, actor: User, target: str | None,
) -> None:
    """Nút conflict_fix: sync prod→base (Claude resolve) rồi chạy lại nguyên đường merge release."""
    # Tin trạng thái (fixing/fix_failed/only_manager) đi về `dest`: group → ngôn ngữ
    # requester (chủ thread); DM → ngôn ngữ người bấm.
    set_lang_for(orch._requester(req) if req.origin_is_group else actor)
    if actor.role not in (UserRole.MANAGER, UserRole.ADMIN):
        await orch.adapter.send(target or actor.platform_user_id, t("orch.only_manager"))
        return
    state = _get(req, CONFLICT_KEY)
    if not state.get("offered"):
        # Chưa từng phát hiện conflict → keyword/nút lạc, không tự ý sync.
        await orch.adapter.send(target or orch._reply_target(req),
                                t("orch.already_handled", id=req.id))
        return
    if state.get("running"):
        await orch.adapter.send(target or orch._reply_target(req),
                                t("sync.fix_in_progress", id=req.id))
        return

    _set(orch, req, CONFLICT_KEY, {"offered": True, "running": True})
    dest = target or orch._reply_target(req)
    await orch.adapter.send(dest, t("sync.fixing"))
    ok = await sync_prod_into_base(orch, req, orch._repo(req))
    if not ok:
        _set(orch, req, CONFLICT_KEY, {"offered": True, "running": False})
        await orch.adapter.send(dest, t("sync.fix_failed"), [[
            Button(t("sync.btn.fix_conflict"), f"conflict_fix:{req.id}"),
            Button(t("ops.btn.reject"), f"mgr_reject:{req.id}"),
        ]])
        return
    _set(orch, req, CONFLICT_KEY, {"offered": True, "running": False})
    # base đã chứa prod → PR release hết conflict; tái dùng nguyên đường merge_to_main
    # (idempotent reuse PR + Approval + MERGED_MAIN→CLOSED + dọn nhánh + báo requester).
    await orch._merge_to_main(req, actor, target)
