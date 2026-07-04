"""Kiểm thử sau khi merge vào dev — chờ CI build+deploy + curl trang dev, rồi mới mời manager.

Khiếu nại gốc: bot merge vào `dev` → GitHub Action deploy lên môi trường dev; build LỖI mà
bot vẫn báo OK / mời manager. Module này chèn bước: sau merge dev (status `MERGED_DEV`),
poll GitHub Actions theo `head_sha`, nếu xanh thì curl `dev_url` (200) → AWAIT_MANAGER và
báo user 'đã deploy + test ổn'. Lỗi → tự đưa cho Claude sửa (fix-forward), lặp tối đa
`dev_verify_max_rounds` vòng; hết vẫn lỗi → về VERIFY cho người quyết, KHÔNG báo OK.

Chạy như BACKGROUND TASK (poll lâu, không được chặn poller). Có DB session/adapter riêng
để sống độc lập vòng đời request. orchestrator.py giữ FSM; module này chỉ là phần "deploy gate".
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx
from sqlalchemy import select

from app import prompts, report, usage
from app.channels.base import Button
from app.claude_runner import PermissionMode
from app.config import Settings, get_settings
from app.github_app import GitHubApp
from app.models import Repository, Request, RequestStatus, User, UserRole
from app.parsing import parse_signal
from app.web.i18n import set_lang, set_lang_for, t

if TYPE_CHECKING:
    from app.orchestrator import Orchestrator

log = logging.getLogger("luna.post_deploy")


def dev_verify_configured(repo: Repository) -> bool:
    """Deploy-gate BẬT MẶC ĐỊNH cho mọi repo. Opt-OUT per-repo bằng settings_json.deploy_gate=false.
    Repo không có CI deploy được phát hiện & bỏ qua tự động (no_ci) trong lúc poll, không cần config."""
    return bool((repo.settings_json or {}).get("deploy_gate", True))


_DEV_URL_JSON = re.compile(r'\{[^{}]*"dev_url"[^{}]*\}', re.DOTALL)


def _parse_dev_url(text: str) -> str | None:
    """Trích {"dev_url": "..."} từ output Claude. Chỉ nhận URL http(s) thật."""
    if not text:
        return None
    m = _DEV_URL_JSON.search(text)
    if not m:
        return None
    try:
        val = json.loads(m.group(0)).get("dev_url")
    except (json.JSONDecodeError, AttributeError):
        return None
    return val.strip() if isinstance(val, str) and val.startswith("http") else None


async def _discover_dev_url(orch: "Orchestrator", repo: Repository) -> str | None:
    """Dò URL dev từ cấu hình TRONG repo (.firebaserc/firebase.json/workflow) bằng Claude read-only."""
    from app.orchestrator import _repo_locks
    try:
        async with _repo_locks[repo.id]:
            repo_dir = await orch._ensure_repo_cloned(repo)
        res = await orch.claude_run(
            prompt="Dò URL môi trường dev mà CI tự deploy tới.", cwd=repo_dir,
            permission_mode=PermissionMode.READONLY,
            system_prompt=prompts.discover_dev_url_system_prompt())
    except Exception as exc:  # noqa: BLE001
        log.warning("dò dev_url repo %s lỗi: %s", repo.repo_full_name, exc)
        return None
    usage.record(orch.db, tenant_id=repo.tenant_id, phase="discover_dev_url", res=res)
    return _parse_dev_url(res.result) if res.ok else None


async def _resolve_dev_url(orch: "Orchestrator", repo: Repository) -> str | None:
    """dev_url theo thứ tự: override config → đã dò (cache) → tự dò rồi cache vào settings_json."""
    s = repo.settings_json or {}
    if s.get("dev_url"):
        return s["dev_url"]
    if s.get("dev_url_auto"):
        return s["dev_url_auto"]
    url = await _discover_dev_url(orch, repo)
    if url:
        repo.settings_json = {**s, "dev_url_auto": url}  # reassign → SQLAlchemy bắt thay đổi JSONB
        orch.db.commit()
        log.info("post_deploy: tự dò dev_url=%s cho repo %s", url, repo.repo_full_name)
    return url


@dataclass
class DeployOutcome:
    status: str                 # success | failed | timeout
    run_id: int | None = None
    run_url: str | None = None
    summary: str = ""


async def _poll_deploy(github, repo: Repository, sha: str, settings: Settings) -> DeployOutcome:
    """Poll workflow run gắn `sha` tới khi hoàn tất. Lọc theo settings_json.deploy_workflow nếu có.

    Trả `no_ci` nếu sau `deploy_ci_grace_s` KHÔNG thấy workflow nào cho commit (repo không có CI
    deploy) — để cổng bật-mặc-định không kẹt/auto-fix nhầm với repo không deploy.
    """
    start = time.monotonic()
    deadline = start + settings.deploy_timeout_s
    grace_deadline = start + settings.deploy_ci_grace_s
    wanted = (repo.settings_json or {}).get("deploy_workflow")
    seen_any = False
    while True:
        try:
            raw = await github.list_workflow_runs(
                repo.gh_installation_id, repo.repo_full_name, head_sha=sha)
        except Exception as exc:  # noqa: BLE001 — lỗi mạng tạm thời → thử lại tới timeout
            log.warning("poll deploy sha=%s lỗi: %s", sha, exc)
            raw = []
        if raw:
            seen_any = True
        runs = [r for r in raw
                if r.get("name") == wanted or str(r.get("path", "")).endswith(wanted)] if wanted else raw

        pending = [r for r in runs if r.get("status") != "completed"]
        if runs and not pending:
            failed = [r for r in runs if r.get("conclusion") != "success"]
            if failed:
                r = failed[0]
                names = ", ".join(f"{x.get('name')}={x.get('conclusion')}" for x in failed)
                return DeployOutcome("failed", run_id=r.get("id"),
                                     run_url=r.get("html_url"), summary=f"workflow lỗi: {names}")
            ok = runs[0]
            return DeployOutcome("success", run_id=ok.get("id"), run_url=ok.get("html_url"))

        now = time.monotonic()
        if not seen_any and now >= grace_deadline:
            return DeployOutcome("no_ci", summary="repo không chạy CI deploy cho commit này")
        if now >= deadline:
            url = runs[0].get("html_url") if runs else None
            return DeployOutcome("timeout", run_url=url, summary="hết thời gian chờ build/deploy")
        await asyncio.sleep(settings.deploy_poll_interval_s)


async def _http_ok(url: str) -> tuple[bool, str]:
    """GET url (theo redirect). Trả (2xx/3xx?, mô tả)."""
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
            resp = await client.get(url)
        return resp.status_code < 400, f"HTTP {resp.status_code}"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)[:200]


# ---------------- notify / chuyển trạng thái (tách khỏi orchestrator để file < 500 LOC) ----------------
def _mgr_packet(orch: "Orchestrator", req: Request, repo: Repository):
    """Compose gói duyệt + nút DƯỚI ngôn ngữ contextvar hiện tại (caller set theo người nhận)."""
    text = report.manager_packet(req, repo, requester=orch._requester(req))
    buttons = [[Button(t("ops.btn.approve_merge"), f"mgr_approve:{req.id}"),
                Button(t("ops.btn.reject"), f"mgr_reject:{req.id}")]]
    return text, buttons


async def notify_managers(orch: "Orchestrator", req: Request, repo: Repository) -> None:
    """Báo (các) manager: gói duyệt 10.x (loại thay đổi/nguyên nhân/giải pháp/phạm vi/test/
    file/thống kê/diff) + nút duyệt. Group → đăng công khai NGÔN NGỮ REQUESTER (chủ thread);
    DM → từng manager, compose lại theo NGÔN NGỮ TỪNG NGƯỜI."""
    requester = orch._requester(req)
    if req.origin_is_group and req.origin_chat_id:
        set_lang_for(requester)
        text, buttons = _mgr_packet(orch, req, repo)
        await orch.adapter.send(req.origin_chat_id, text, buttons)
        return
    # MANAGER + ADMIN: cả hai role đều có quyền duyệt merge (xem _merge_to_main), nên cả hai
    # đều phải được mời. Tenant chỉ-có-admin (không có manager) trước đây bị silent fail.
    approvers = _approvers(orch, repo)
    if not approvers:
        log.warning("request %s vào AWAIT_MANAGER nhưng tenant %s không có manager/admin đã link "
                    "chat để mời duyệt", req.id, repo.tenant_id)
        return
    for m in approvers:
        set_lang_for(m)
        text, buttons = _mgr_packet(orch, req, repo)
        await orch.adapter.send(m.platform_user_id, text, buttons)
    set_lang_for(requester)  # trả contextvar về requester cho tin kế tiếp trong cùng luồng


def _approvers(orch: "Orchestrator", repo: Repository) -> list[User]:
    return list(orch.db.scalars(
        select(User).where(User.tenant_id == repo.tenant_id,
                           User.role.in_((UserRole.MANAGER, UserRole.ADMIN)),
                           User.platform_user_id.is_not(None))
    ).all())


async def notify_other_approvers(orch: "Orchestrator", req: Request, repo: Repository,
                                 actor: User, *, approved: bool) -> None:
    """Sau khi 1 approver chốt (duyệt/từ chối): báo các approver CÒN LẠI đã từng được DM
    lời mời, để lời mời trong DM của họ không thành stale ('bấm mới biết đã xử lý').

    Chỉ áp dụng khi lời mời đi qua DM (request tạo từ DM) — group thì lời mời + kết quả
    đã nằm chung trong group. Best-effort: DM 1 người lỗi không được hỏng luồng chính
    (merge đã xong). Mỗi người nhận theo ngôn ngữ CỦA HỌ."""
    if req.origin_is_group and req.origin_chat_id:
        return
    key = "ops.resolved_by_other.approved" if approved else "ops.resolved_by_other.rejected"
    name = actor.display_name or actor.platform_user_id or "?"
    for m in _approvers(orch, repo):
        if m.id == actor.id:
            continue
        try:
            set_lang_for(m)
            await orch.adapter.send(m.platform_user_id, t(key, id=req.id, name=name))
        except Exception as exc:  # noqa: BLE001
            log.warning("báo approver %s về req %s lỗi: %s", m.id, req.id, exc)


async def enter_await_manager(orch: "Orchestrator", req: Request, *, user_msg: str | None = None) -> None:
    """Chuyển AWAIT_MANAGER + báo requester + mời manager. user_msg tuỳ biến câu báo cho requester."""
    repo = orch._repo(req)
    orch._set_status(req, RequestStatus.AWAIT_MANAGER)
    orch.db.commit()
    msg = user_msg or t("ops.await_manager.default", base=repo.base_branch)
    await orch._say(req, orch._requester(req), msg)
    await notify_managers(orch, req, repo)


# ---------------- vòng deploy-gate ----------------
async def verify_after_dev_merge(
    req_id: int, *, settings: Settings | None = None, db=None,
    github=None, adapter=None, claude_run=None, git=None,
) -> None:
    """Entry của background task. Tự dựng db/adapter/github nếu không inject (cho test/recovery)."""
    settings = settings or get_settings()
    own_db = db is None
    if db is None:
        from app.db import SessionLocal
        db = SessionLocal()
    own_gh = own_adapter = False
    try:
        req = db.get(Request, req_id)
        if req is None or req.status != RequestStatus.MERGED_DEV:
            return  # đã bị huỷ/đổi state ở nơi khác → bỏ qua
        # Task nền có context riêng (đặc biệt khi rekick lúc restart) → đặt ngôn ngữ theo requester
        # để báo deploy đúng ngôn ngữ người dùng, không mặc định về vi.
        requester = db.get(User, req.requester_user_id)
        set_lang(requester.language if requester else None)
        repo = db.get(Repository, req.repo_id)
        if github is None:
            github = GitHubApp.from_settings()
            own_gh = True
        if adapter is None:
            from app.recovery import _build_adapter
            adapter = _build_adapter(req.origin_platform, settings)
            own_adapter = True
        if adapter is None:
            log.error("post_deploy req %s: không dựng được adapter", req_id)
            return
        from app.orchestrator import Orchestrator
        orch = Orchestrator(db, adapter, github=github, claude_run=claude_run, git=git)
        await _run_verify_loop(orch, req, repo, settings)
    except Exception:  # noqa: BLE001 — background task không được làm sập app
        log.exception("post_deploy req %s lỗi", req_id)
    finally:
        if own_adapter and adapter is not None:
            with contextlib.suppress(Exception):
                await adapter.aclose()
        if own_gh and github is not None:
            with contextlib.suppress(Exception):
                await github.aclose()
        if own_db:
            db.close()


async def _run_verify_loop(orch: "Orchestrator", req: Request, repo: Repository,
                           settings: Settings) -> None:
    sha = req.dev_merge_sha
    rounds = 0
    dev_url = None
    resolved = False
    while True:
        if not sha:  # không có sha (vd merge fast-forward không trả sha) → không thể poll
            await enter_await_manager(orch, req)
            return
        outcome = await _poll_deploy(orch.github, repo, sha, settings)
        if outcome.status == "no_ci":  # repo không có CI deploy → bỏ qua cổng, mời manager như cũ
            await enter_await_manager(orch, req)
            return
        passed = outcome.status == "success"
        reason = "" if passed else (outcome.summary or f"deploy {outcome.status}")
        if passed:  # CI xanh → kiểm tra trang dev thực sự phản hồi (dò dev_url 1 lần, chỉ khi có deploy)
            if not resolved:
                dev_url = await _resolve_dev_url(orch, repo)
                resolved = True
            if dev_url:
                ok, detail = await _http_ok(dev_url)
                passed = ok
                reason = "" if ok else f"trang dev {dev_url} không trả 2xx ({detail})"

        if passed:
            # Bàn giao kèm link DEV để người dùng tự kiểm tra (UAT) nếu đã dò được URL.
            msg = t("ops.deploy_ok_link", url=dev_url) if dev_url else t("ops.deploy_ok")
            await enter_await_manager(orch, req, user_msg=msg)
            return

        rounds += 1
        if rounds > settings.dev_verify_max_rounds:
            await _give_up(orch, req, reason, outcome)
            return
        await orch._say(req, orch._requester(req),
                        t("ops.deploy_retry", reason=reason, round=rounds))
        new_sha = await _auto_fix_round(orch, req, repo, reason, outcome, rounds)
        if new_sha is None:
            await _give_up(orch, req, reason, outcome, fix_failed=True)
            return
        sha = new_sha


async def _give_up(orch: "Orchestrator", req: Request, reason: str,
                   outcome: DeployOutcome, *, fix_failed: bool = False) -> None:
    """Hết vòng auto-fix (hoặc fix thất bại): về VERIFY cho người quyết. KHÔNG mời manager."""
    # Reset PR để lần sửa thủ công kế tiếp tạo PR mới sạch (PR trước đã merge vào dev).
    req.pr_number = None
    req.pr_url = None
    orch._set_status(req, RequestStatus.VERIFY)
    orch.db.commit()
    # Chi tiết kỹ thuật (lý do + log CI) chỉ ghi log nội bộ, KHÔNG gửi người dùng cuối.
    log.info("give_up req %s: reason=%s run_url=%s fix_failed=%s",
             req.id, reason, outcome.run_url, fix_failed)
    extra = t("ops.give_up.extra_fix_failed") if fix_failed else ""
    await orch._say(
        req, orch._requester(req),
        t("ops.give_up", extra=extra),
        buttons=[[Button(t("ops.btn.needs_fix"), f"verify_fix:{req.id}"),
                  Button(t("ops.btn.cancel"), f"cancel:{req.id}")]])


async def _auto_fix_round(orch: "Orchestrator", req: Request, repo: Repository,
                          reason: str, outcome: DeployOutcome, rounds: int) -> str | None:
    """1 vòng fix-forward: Claude sửa theo log lỗi → nhánh fix mới → PR → merge dev. Trả sha mới/None."""
    from app.orchestrator import _repo_locks

    detail = ""
    if outcome.run_id:
        with contextlib.suppress(Exception):
            detail = await orch.github.run_failure_summary(
                repo.gh_installation_id, repo.repo_full_name, outcome.run_id)
    parts = [f"Deploy lên môi trường dev thất bại: {reason}."]
    if detail:
        parts.append("Chi tiết job lỗi:\n" + detail)
    if outcome.run_url:
        parts.append("Log: " + outcome.run_url)
    parts.append("Hãy sửa lại để build & deploy dev thành công.")
    feedback = "\n".join(parts)

    async with _repo_locks[repo.id]:
        orch._set_status(req, RequestStatus.EXECUTING)
        orch.db.commit()
        branch = f"bot/req-{req.id}-fix{rounds}"  # nhánh mới mỗi vòng → PR sạch, tránh non-ff
        try:
            repo_dir = await orch._ensure_repo_cloned(repo)
            await orch.git.prepare_branch(repo_dir, branch, repo.base_branch)
        except Exception as exc:  # noqa: BLE001
            log.warning("auto-fix req %s chuẩn bị nhánh lỗi: %s", req.id, exc)
            return None

        sysp = prompts.executing_system_prompt(
            repo.repo_full_name, repo.base_branch, branch, [repo.prod_branch],
            build_cmd=(repo.settings_json or {}).get("build_cmd"))
        res = await orch.claude_run(
            prompt=prompts.fix_request_prompt(feedback), cwd=repo_dir,
            permission_mode=PermissionMode.BYPASS,
            session_id=req.claude_session_id, system_prompt=sysp)
        req.claude_session_id = res.session_id
        usage.record(orch.db, tenant_id=repo.tenant_id, request_id=req.id,
                     phase="auto_fix", res=res)
        if not res.ok or not parse_signal(res.result).ok:
            orch.db.commit()
            log.warning("auto-fix req %s: Claude không cho tín hiệu hợp lệ", req.id)
            return None

        try:
            changed = await orch.git.commit_all(repo_dir, f"luna: req-{req.id} fix deploy (lần {rounds})")
            if not changed:
                orch.db.commit()
                log.warning("auto-fix req %s: Claude không thay đổi gì", req.id)
                return None
            await orch.git.push_branch(repo_dir, branch)
            pr = await orch.github.create_pull_request(
                repo.gh_installation_id, repo.repo_full_name,
                head=branch, base=repo.base_branch,
                title=f"[luna] fix deploy req-{req.id}", body=feedback[:1000])
            req.branch_name = branch
            req.pr_number = pr.get("number")
            req.pr_url = pr.get("html_url")
            merged = await orch.github.merge_pull_request(
                repo.gh_installation_id, repo.repo_full_name, req.pr_number)
        except Exception as exc:  # noqa: BLE001
            orch.db.commit()
            log.warning("auto-fix req %s push/PR/merge lỗi: %s", req.id, exc)
            return None

    new_sha = (merged or {}).get("sha")
    req.dev_merge_sha = new_sha
    orch._set_status(req, RequestStatus.MERGED_DEV)
    orch.db.commit()
    return new_sha
