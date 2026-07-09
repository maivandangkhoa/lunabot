"""Dev-mode runner — "Claude Code extension qua chat" (per-tenant).

Khi tenant bật `Tenant.settings_json['dev_mode']`, mọi tin nhắn đi THẲNG vào Claude Code
headless (`bypassPermissions`, `--resume`) như một trợ lý coding agentic — KHÔNG qua FSM.
Toàn quyền như Claude Code client trên repo của chính developer: làm thẳng trên nhánh chính
(`prod_branch`), tự commit & push nhánh chính; tự tạo/push nhánh riêng khi user yêu cầu.
KHÔNG có cổng confirm-deploy và KHÔNG cài pre-push hook chặn — bot tự do.

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
from app.models import DevSession, Repository, Tenant, User
from app.parsing import scrub_meta
from app.web.i18n import set_lang_for, t

log = logging.getLogger("luna.dev")

_W_CLEAR = {"/clear", "/new", "/reset"}


def tenant_dev_mode(tenant: Tenant | None) -> bool:
    """Tenant có bật dev-mode không (đọc settings_json['dev_mode'], mặc định False)."""
    return bool((getattr(tenant, "settings_json", None) or {}).get("dev_mode"))


def _dev_system_prompt(main: str) -> str:
    """Prompt dev-mode: tự do như Claude Code client trên repo của chính developer —
    làm thẳng trên nhánh chính, tự commit & push; chỉ rẽ nhánh khi user yêu cầu."""
    return (
        "Bạn là trợ lý lập trình chạy trong workspace của một developer qua chat, có TOÀN "
        "QUYỀN đọc/sửa/chạy lệnh trong repo này (giống Claude Code client). Đang làm việc "
        f"trên nhánh `{main}` — tự commit & `git push origin {main}` khi hoàn tất thay đổi. "
        "Nếu người dùng yêu cầu làm trên nhánh riêng, hãy tự tạo nhánh mới "
        "(`git checkout -b <tên>`) và push nhánh đó. Trả lời ngắn gọn, đúng trọng tâm kỹ thuật."
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
    """Clone/fetch nhánh chính (`prod_branch`) với token mới (remote authed để Claude tự
    push được). Dev-mode làm thẳng trên nhánh chính như Claude Code client → KHÔNG cài
    pre-push hook chặn (protected rỗng). Dùng chung thư mục với FSM (workspace/<tenant>/<repo>)."""
    if github is None:
        raise RuntimeError("GitHub App chưa cấu hình (thiếu token).")
    token = await github.installation_token(repo.gh_installation_id)
    url = github.authed_remote_url(token, repo.repo_full_name)
    safe = repo.repo_full_name.replace("/", "__")
    repo_dir = Path(get_settings().workspace) / str(repo.tenant_id) / safe
    await git_ops.ensure_clone(repo_dir, url, repo.prod_branch, [])
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
    text = scrub_meta((text or "").strip())
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
# Entrypoint — gọi từ dispatcher khi tenant.dev_mode
# --------------------------------------------------------------------------- #
async def dev_chat(db: Session, adapter, github, user: User, inbound, reply_to: str) -> None:
    """Pipe 1 tin của user (dev-mode) vào Claude, relay recap + câu trả lời. Chỉ chặn
    `/clear` (reset phiên); còn lại toàn quyền như Claude Code client (tự push nhánh chính)."""
    set_lang_for(user)
    text = (inbound.text or "").strip()
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
        system_prompt=_dev_system_prompt(repo.prod_branch),
        session_id=sess.claude_session_id,
        model=((repo.tenant.settings_json or {}).get("claude_model") or "").strip()
        or (get_settings().claude_model_default or "").strip() or None,
    )
    usage.record(db, tenant_id=user.tenant_id, phase="dev", res=out["res"])

    if out["session_id"]:
        sess.claude_session_id = out["session_id"]
    db.commit()

    await adapter.send(reply_to, _compose(out["actions"], out["text"]))
