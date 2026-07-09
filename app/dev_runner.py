"""Dev-mode runner — "Claude Code extension qua chat" (per-tenant).

Khi tenant bật `Tenant.settings_json['dev_mode']`, mọi tin nhắn đi THẲNG vào Claude Code
headless (`bypassPermissions`, `--resume`) như một trợ lý coding agentic — KHÔNG qua FSM.
Toàn quyền đọc/sửa/chạy lệnh, kể cả deploy `main`, NHƯNG deploy `main` phải xác nhận GIỮA
2 lượt chat (Claude dừng, hỏi, lượt sau mới merge) → không block subprocess.

Tách hẳn khỏi orchestrator.py (FSM): chế độ thường KHÔNG đổi. Xem tasks/dev-mode.md.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import git_ops, usage
from app.claude_runner import ClaudeResult, _build_env
from app.config import get_settings
from app.github_app import GitHubAppError
from app.models import DevSession, Repository, Tenant, User
from app.parsing import scrub_meta
from app.textnorm import strip_symbols
from app.web.i18n import set_lang_for, t

log = logging.getLogger("luna.dev")

# Marker Claude phát ra (theo system prompt) khi user xin deploy production → app xin xác nhận
# giữa 2 lượt. Bị strip khỏi text hiển thị. KHÔNG dùng cơ chế permission blocking.
_DEPLOY_SENTINEL = "[[LUNA_DEPLOY_MAIN]]"

# Từ khoá xác nhận/huỷ cho cổng deploy-main (local — tránh import vòng với dispatcher).
_W_YES = {"ok", "oke", "okay", "đồng ý", "dong y", "duyệt", "duyet", "yes", "y", "ừ", "u",
          "deploy", "triển khai", "trien khai"}
_W_NO = {"không", "khong", "no", "n", "huỷ", "huy", "hủy", "cancel", "thôi", "thoi", "bỏ", "bo"}
_W_CLEAR = {"/clear", "/new", "/reset"}


def tenant_dev_mode(tenant: Tenant | None) -> bool:
    """Tenant có bật dev-mode không (đọc settings_json['dev_mode'], mặc định False)."""
    return bool((getattr(tenant, "settings_json", None) or {}).get("dev_mode"))


def _dev_system_prompt(base: str, prod: str) -> str:
    return (
        "Bạn là trợ lý lập trình chạy trong workspace của một developer qua chat, có TOÀN "
        f"QUYỀN đọc/sửa/chạy lệnh trong repo này. Đang ở nhánh `{base}`; tự commit & push "
        f"`{base}` khi hợp lý. Trả lời ngắn gọn, đúng trọng tâm kỹ thuật.\n"
        f"TUYỆT ĐỐI KHÔNG tự push/merge lên nhánh production `{prod}`. Khi người dùng yêu "
        f"cầu deploy/đưa lên `{prod}`, ĐỪNG tự làm — hãy tóm tắt thay đổi rồi kết thúc lượt "
        f"bằng ĐÚNG một dòng marker `{_DEPLOY_SENTINEL}` ở cuối để hệ thống xin xác nhận."
    )


# --------------------------------------------------------------------------- #
# Chọn repo & phiên
# --------------------------------------------------------------------------- #
def _pick_repo(db: Session, user: User) -> Repository | None:
    """Repo dev-mode làm việc: `active_repo_id` nếu hợp lệ, else repo duy nhất của tenant."""
    if user.active_repo_id:
        r = db.get(Repository, user.active_repo_id)
        if r is not None and r.tenant_id == user.tenant_id:
            return r
    repos = db.scalars(
        select(Repository).where(Repository.tenant_id == user.tenant_id)
        .order_by(Repository.id)
    ).all()
    return repos[0] if len(repos) == 1 else None


def _get_session(db: Session, user_id: int, repo_id: int) -> DevSession:
    sess = db.scalar(select(DevSession).where(
        DevSession.user_id == user_id, DevSession.repo_id == repo_id))
    if sess is None:
        sess = DevSession(user_id=user_id, repo_id=repo_id, pending_json={})
        db.add(sess)
        db.flush()
    return sess


async def _ensure_repo(github, repo: Repository) -> Path:
    """Clone/fetch nhánh base với token mới (remote authed để Claude tự push được), cài
    pre-push hook chặn prod. Dùng chung thư mục với FSM (workspace/<tenant>/<repo>)."""
    if github is None:
        raise RuntimeError("GitHub App chưa cấu hình (thiếu token).")
    token = await github.installation_token(repo.gh_installation_id)
    url = github.authed_remote_url(token, repo.repo_full_name)
    safe = repo.repo_full_name.replace("/", "__")
    repo_dir = Path(get_settings().workspace) / str(repo.tenant_id) / safe
    await git_ops.ensure_clone(repo_dir, url, repo.base_branch, [repo.prod_branch])
    return repo_dir


# --------------------------------------------------------------------------- #
# Chạy Claude stream-json + gom recap hành động
# --------------------------------------------------------------------------- #
def _summarize_tool(name: str, inp: dict) -> str:
    """1 dòng recap cho 1 lần dùng tool (đọc/sửa file, chạy lệnh…)."""
    inp = inp or {}
    if name in ("Read", "Edit", "Write", "NotebookEdit"):
        return f"{name} {inp.get('file_path', '')}".strip()
    if name in ("Grep", "Glob"):
        return f"{name} {inp.get('pattern', '')}".strip()
    if name == "Bash":
        cmd = " ".join((inp.get("command") or "").split())
        return f"$ {cmd[:100]}"
    return name


def _parse_stream(stdout: str, session_id: str | None) -> dict:
    """Parse JSONL của `--output-format stream-json`: gom `tool_use` (hành động) + event
    `result` cuối (text + session_id + usage). Dòng lỗi/không-JSON → bỏ qua an toàn."""
    actions: list[str] = []
    final: dict = {}
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        typ = ev.get("type")
        if typ == "assistant":
            for block in (ev.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    actions.append(_summarize_tool(block.get("name", "?"), block.get("input")))
        elif typ == "result":
            final = ev
    new_sid = final.get("session_id") or session_id
    text = final.get("result") or final.get("error") or ""
    is_err = bool(final.get("is_error")) or not final
    return {"actions": actions, "text": text, "session_id": new_sid,
            "final": final, "is_error": is_err}


async def _run_stream(*, prompt: str, cwd: Path, system_prompt: str,
                      session_id: str | None, model: str | None) -> dict:
    """Chạy `claude -p --output-format stream-json` (bypassPermissions), trả dict đã parse
    + `res` (ClaudeResult cho usage). Lỗi hạ tầng/timeout ⇒ is_error=True, không raise."""
    settings = get_settings()
    args = [
        "claude", "-p", prompt,
        "--output-format", "stream-json", "--verbose",
        "--permission-mode", "bypassPermissions",
    ]
    if model:
        args += ["--model", model]
    args += ["--append-system-prompt", system_prompt]
    if session_id:
        args += ["--resume", session_id]

    log.info("dev run: cwd=%s resume=%s prompt_len=%d", cwd, bool(session_id), len(prompt))
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, cwd=str(cwd), env=_build_env(),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return _err_out(session_id, "❌ Không tìm thấy lệnh 'claude'. CLI đã cài chưa?")

    try:
        out, err = await asyncio.wait_for(
            proc.communicate(), timeout=settings.claude_timeout_s)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        log.warning("dev claude timeout %ds (cwd=%s)", settings.claude_timeout_s, cwd)
        return _err_out(session_id, f"⏱ Tác vụ vượt {settings.claude_timeout_s // 60} phút, đã huỷ.")

    stdout = out.decode(errors="replace")
    parsed = _parse_stream(stdout, session_id)
    if not parsed["final"]:
        log.error("dev claude không có event result (rc=%s): %s",
                  proc.returncode, err.decode(errors="replace")[:300])
        parsed["text"] = parsed["text"] or "❌ Claude không trả kết quả (xem log)."
    final = parsed["final"]
    parsed["res"] = ClaudeResult(
        ok=not parsed["is_error"], result=parsed["text"], session_id=parsed["session_id"],
        is_error=parsed["is_error"], returncode=proc.returncode,
        num_turns=final.get("num_turns"), total_cost_usd=final.get("total_cost_usd"),
        raw=final,
    )
    return parsed


def _err_out(session_id: str | None, msg: str) -> dict:
    return {"actions": [], "text": msg, "session_id": session_id, "final": {},
            "is_error": True,
            "res": ClaudeResult(ok=False, is_error=True, result=msg, session_id=session_id)}


def _compose(actions: list[str], text: str) -> str:
    """Ghép recap hành động + câu trả lời (giống panel 'đã làm gì' của extension)."""
    text = scrub_meta((text or "").replace(_DEPLOY_SENTINEL, "").strip())
    parts: list[str] = []
    if actions:
        shown = actions[:25]
        lines = "\n".join(f"• {a}" for a in shown)
        if len(actions) > 25:
            lines += f"\n• … (+{len(actions) - 25})"
        parts.append(f"🔧 {t('dev.acted')}:\n{lines}")
    if text:
        parts.append(f"💬 {text}")
    return "\n\n".join(parts) or t("dev.empty")


# --------------------------------------------------------------------------- #
# Deploy production (PR base→prod + merge, idempotent) — chỉ chạy sau xác nhận
# --------------------------------------------------------------------------- #
async def _deploy_main(github, repo: Repository) -> None:
    """Tạo PR `base`→`prod` (idempotent nếu 422) rồi merge (retry 1 lần khi 405 race)."""
    try:
        pr = await github.create_pull_request(
            repo.gh_installation_id, repo.repo_full_name,
            head=repo.base_branch, base=repo.prod_branch,
            title=f"[luna] dev deploy {repo.base_branch}→{repo.prod_branch}",
            body="Dev-mode deploy (đã xác nhận qua chat).")
    except GitHubAppError as exc:
        if exc.status_code == 422:
            pr = await github.find_open_pull_request(
                repo.gh_installation_id, repo.repo_full_name,
                head=repo.base_branch, base=repo.prod_branch)
            if not pr:
                raise
        else:
            raise
    for attempt in range(2):
        try:
            await github.merge_pull_request(
                repo.gh_installation_id, repo.repo_full_name, pr["number"])
            return
        except GitHubAppError as exc:
            if exc.status_code == 405 and attempt == 0:
                await asyncio.sleep(2)
                continue
            raise


async def _handle_deploy(db: Session, adapter, github, repo: Repository,
                         sess: DevSession, reply_to: str) -> None:
    sess.pending_json = {}
    db.commit()
    try:
        await _deploy_main(github, repo)
    except Exception as exc:  # noqa: BLE001 — báo lỗi rõ, không sập dispatcher
        log.warning("dev deploy main repo=%s lỗi: %s", repo.id, exc)
        await adapter.send(reply_to, t("dev.deploy_error", prod=repo.prod_branch,
                                       err=str(exc)[:200]))
        return
    await adapter.send(reply_to, t("dev.deploy_done", prod=repo.prod_branch))


# --------------------------------------------------------------------------- #
# Entrypoint — gọi từ dispatcher khi tenant.dev_mode
# --------------------------------------------------------------------------- #
async def dev_chat(db: Session, adapter, github, user: User, inbound, reply_to: str) -> None:
    """Pipe 1 tin của user (dev-mode) vào Claude, relay recap + câu trả lời. Chỉ chặn
    `/clear` (reset phiên) và cổng xác nhận deploy `main`."""
    set_lang_for(user)
    text = (inbound.text or "").strip()
    low = strip_symbols(text).lower()          # bỏ ký hiệu/emoji → khớp từ khoá (ok/huỷ…)
    first = text.split(maxsplit=1)[0].lower() if text else ""   # token đầu (giữ '/' cho lệnh)

    repo = _pick_repo(db, user)
    if repo is None:
        await adapter.send(reply_to, t("dev.no_repo"))
        return
    sess = _get_session(db, user.id, repo.id)

    if first in _W_CLEAR:
        sess.claude_session_id = None
        sess.pending_json = {}
        db.commit()
        await adapter.send(reply_to, t("dev.cleared"))
        return

    # Cổng deploy-main: tin trước bot đã hỏi xác nhận → tin này quyết định.
    if (sess.pending_json or {}).get("await_main"):
        if low in _W_YES:
            await _handle_deploy(db, adapter, github, repo, sess, reply_to)
            return
        if low in _W_NO:
            sess.pending_json = {}
            db.commit()
            await adapter.send(reply_to, t("dev.deploy_cancelled"))
            return
        # Text khác → coi như lệnh mới: huỷ ngầm lời mời deploy rồi xử lý bình thường.
        sess.pending_json = {}
        db.commit()

    if not text:
        return

    try:
        repo_dir = await _ensure_repo(github, repo)
    except Exception as exc:  # noqa: BLE001
        log.warning("dev ensure_repo repo=%s lỗi: %s", repo.id, exc)
        await adapter.send(reply_to, t("dev.error", err=str(exc)[:200]))
        return

    out = await _run_stream(
        prompt=text, cwd=repo_dir,
        system_prompt=_dev_system_prompt(repo.base_branch, repo.prod_branch),
        session_id=sess.claude_session_id,
        model=((repo.tenant.settings_json or {}).get("claude_model") or "").strip()
        or (get_settings().claude_model_default or "").strip() or None,
    )
    usage.record(db, tenant_id=user.tenant_id, phase="dev", res=out["res"])

    if out["session_id"]:
        sess.claude_session_id = out["session_id"]
    deploy_requested = _DEPLOY_SENTINEL in (out["text"] or "") and not out["is_error"]
    if deploy_requested:
        sess.pending_json = {"await_main": True}
    db.commit()

    await adapter.send(reply_to, _compose(out["actions"], out["text"]))
    if deploy_requested:
        await adapter.send(reply_to, t("dev.deploy_ask", prod=repo.prod_branch))
