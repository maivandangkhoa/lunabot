"""Cổng kiểm tra SAU KHI merge vào production (`main`) — đối xứng với `post_deploy` bên `dev`.

Trước đây `_merge_to_main` merge PR release xong là báo "đã merge và đóng" ngay: đó mới chỉ là
**code đã vào `main`**, chưa phải **đã lên production**. CI trên `main` fail (build lỗi, deploy
rớt) thì request đã CLOSED và không ai được báo.

Module này poll GitHub Actions theo sha merge vào `main`, rồi curl `prod_url`:
- xanh + trang sống → đóng request, báo requester kèm LINK production;
- repo không có CI deploy (`no_ci`) → giữ nguyên hành vi cũ (đóng, báo đã merge);
- đỏ/timeout → **KHÔNG auto-fix** (fix-forward thẳng lên production quá rủi ro): đóng request
  nhưng BÁO ĐỘNG requester + các approver để người quyết rollback hay mở yêu cầu sửa.

Tái dùng `post_deploy._poll_deploy/_http_ok/_approvers` (cùng cơ chế, khác nhánh & URL).
Chạy như BACKGROUND TASK với db/adapter/github riêng, y hệt `verify_after_dev_merge`.
"""
from __future__ import annotations

import contextlib
import json
import logging
import re
from typing import TYPE_CHECKING

from app import post_deploy, prompts, usage
from app.claude_runner import PermissionMode
from app.config import Settings, get_settings
from app.github_app import GitHubApp
from app.models import Repository, Request, RequestStatus, User
from app.web.i18n import set_lang, set_lang_for, t

if TYPE_CHECKING:
    from app.orchestrator import Orchestrator

log = logging.getLogger("luna.prod_verify")

# sha merge vào prod lưu trong report_json (không cần migration; chỉ dùng cho vòng đời cổng này).
_SHA_KEY = "_main_merge_sha"


def prod_verify_configured(repo: Repository) -> bool:
    """Cổng production BẬT MẶC ĐỊNH. Opt-OUT per-repo: settings_json.prod_gate=false.
    Repo không có CI deploy được phát hiện tự động (no_ci) trong lúc poll, không cần config."""
    return bool((repo.settings_json or {}).get("prod_gate", True))


def remember_main_sha(req: Request, sha: str | None) -> None:
    req.report_json = {**(req.report_json or {}), _SHA_KEY: sha}


def main_merge_sha(req: Request) -> str | None:
    return (req.report_json or {}).get(_SHA_KEY)


_PROD_URL_JSON = re.compile(r'\{[^{}]*"prod_url"[^{}]*\}', re.DOTALL)


def _parse_prod_url(text: str) -> str | None:
    """Trích {"prod_url": "..."} từ output Claude. Chỉ nhận URL http(s) thật."""
    if not text:
        return None
    m = _PROD_URL_JSON.search(text)
    if not m:
        return None
    try:
        val = json.loads(m.group(0)).get("prod_url")
    except (json.JSONDecodeError, AttributeError):
        return None
    return val.strip() if isinstance(val, str) and val.startswith("http") else None


async def _discover_prod_url(orch: "Orchestrator", repo: Repository) -> str | None:
    """Dò URL production từ cấu hình TRONG repo bằng Claude read-only (1 lần rồi cache)."""
    from app.orchestrator import _repo_locks
    try:
        async with _repo_locks[repo.id]:
            repo_dir = await orch._ensure_repo_cloned(repo)
        res = await orch.claude_run(
            prompt="Dò URL môi trường production mà CI tự deploy tới.", cwd=repo_dir,
            permission_mode=PermissionMode.READONLY,
            system_prompt=prompts.discover_prod_url_system_prompt(repo.prod_branch))
    except Exception as exc:  # noqa: BLE001
        log.warning("dò prod_url repo %s lỗi: %s", repo.repo_full_name, exc)
        return None
    usage.record(orch.db, tenant_id=repo.tenant_id, phase="discover_prod_url", res=res)
    return _parse_prod_url(res.result) if res.ok else None


async def _resolve_prod_url(orch: "Orchestrator", repo: Repository) -> str | None:
    """prod_url theo thứ tự: override config → đã dò (cache) → tự dò rồi cache vào settings_json."""
    s = repo.settings_json or {}
    if s.get("prod_url"):
        return s["prod_url"]
    if s.get("prod_url_auto"):
        return s["prod_url_auto"]
    url = await _discover_prod_url(orch, repo)
    if url:
        repo.settings_json = {**s, "prod_url_auto": url}  # reassign → SQLAlchemy bắt đổi JSONB
        orch.db.commit()
        log.info("prod_verify: tự dò prod_url=%s cho repo %s", url, repo.repo_full_name)
    return url


# ---------------- entry background task ----------------
async def verify_after_main_merge(
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
        if req is None or req.status != RequestStatus.MERGED_MAIN:
            return  # đã đóng/đổi state ở nơi khác → bỏ qua
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
            log.error("prod_verify req %s: không dựng được adapter", req_id)
            return
        from app.orchestrator import Orchestrator
        orch = Orchestrator(db, adapter, github=github, claude_run=claude_run, git=git)
        await _run_prod_loop(orch, req, repo, settings)
    except Exception:  # noqa: BLE001 — background task không được làm sập app
        log.exception("prod_verify req %s lỗi", req_id)
    finally:
        if own_adapter and adapter is not None:
            with contextlib.suppress(Exception):
                await adapter.aclose()
        if own_gh and github is not None:
            with contextlib.suppress(Exception):
                await github.aclose()
        if own_db:
            db.close()


async def _run_prod_loop(orch: "Orchestrator", req: Request, repo: Repository,
                         settings: Settings) -> None:
    """1 lượt: chờ CI trên `main` → curl trang production → đóng request với kết luận THẬT."""
    sha = main_merge_sha(req)
    if not sha:  # không có sha (merge không trả sha) → không poll được, giữ hành vi cũ
        await _close_merged(orch, req, repo)
        return
    outcome = await post_deploy._poll_deploy(orch.github, repo, sha, settings)
    if outcome.status == "no_ci":  # repo không có CI deploy → không có gì để chờ
        await _close_merged(orch, req, repo)
        return
    if outcome.status == "success":
        url = await _resolve_prod_url(orch, repo)
        if url:
            ok, detail = await post_deploy._http_ok(url)
            if not ok:
                await _alert_failure(orch, req, repo, outcome,
                                     reason=f"trang production {url} không trả 2xx ({detail})")
                return
        await _close_deployed(orch, req, repo, url)
        return
    await _alert_failure(orch, req, repo, outcome,
                         reason=outcome.summary or f"deploy {outcome.status}")


# ---------------- kết luận ----------------
def _close(orch: "Orchestrator", req: Request) -> None:
    orch._set_status(req, RequestStatus.CLOSED)
    orch.db.commit()


async def _close_merged(orch: "Orchestrator", req: Request, repo: Repository) -> None:
    """Không có CI deploy để chờ → câu báo cũ (đã merge & đóng)."""
    _close(orch, req)
    set_lang_for(orch._requester(req))
    await orch._say(req, orch._requester(req),
                    t("orch.merged_main_closed", id=req.id, prod=repo.prod_branch))


async def _close_deployed(orch: "Orchestrator", req: Request, repo: Repository,
                          url: str | None) -> None:
    """Deploy production xanh (và trang sống nếu biết URL) → đóng + báo requester kèm link."""
    _close(orch, req)
    set_lang_for(orch._requester(req))
    key = "ops.prod.deployed_link" if url else "ops.prod.deployed"
    await orch._say(req, orch._requester(req), t(key, id=req.id, url=url))


async def _alert_failure(orch: "Orchestrator", req: Request, repo: Repository,
                         outcome: post_deploy.DeployOutcome, *, reason: str) -> None:
    """Merge xong nhưng deploy production hỏng: KHÔNG tự sửa trên production — báo động người thật.

    Vẫn đóng request (code đã nằm trên `{prod}`, không tự hoàn tác được) để không kẹt trạng thái
    lửng lơ; người nhận quyết rollback hay mở yêu cầu sửa mới. Chi tiết kỹ thuật chỉ vào log."""
    log.warning("prod deploy req %s HỎNG: reason=%s run_url=%s", req.id, reason, outcome.run_url)
    req.report_json = {**(req.report_json or {}),
                       "_prod_deploy": {"status": outcome.status, "run_url": outcome.run_url}}
    _close(orch, req)
    requester = orch._requester(req)
    set_lang_for(requester)
    msg = t("ops.prod.deploy_failed", id=req.id, prod=repo.prod_branch)
    await orch._say(req, requester, msg)
    if req.origin_is_group and req.origin_chat_id:
        return  # đã đăng công khai trong group → approver thấy rồi
    for m in post_deploy._approvers(orch, repo):
        if m.id == requester.id:
            continue
        try:
            set_lang_for(m)
            await orch.adapter.send(m.platform_user_id,
                                    t("ops.prod.deploy_failed", id=req.id, prod=repo.prod_branch))
        except Exception as exc:  # noqa: BLE001 — báo 1 người lỗi không hỏng luồng
            log.warning("báo approver %s deploy prod hỏng req %s lỗi: %s", m.id, req.id, exc)
