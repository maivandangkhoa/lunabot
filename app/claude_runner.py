"""Claude Code CLI runner (headless subprocess).

Port từ bot.py:130-172, nhưng tách sạch khỏi Telegram/state:
chỉ là 1 hàm thuần `run_claude(...)` để Orchestrator (M4) gọi ở mỗi phase FSM.

Khác biệt so với ops-bot:
- `permission_mode` là tham số (plan cho phase chỉ-đọc, bypassPermissions cho EXECUTING).
- Trả về `ClaudeResult` có cấu trúc thay vì tuple, kèm `raw` để parser (M5) dùng.
- Token Claude truyền qua ENV (không bao giờ vào argv/log).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from app.config import get_settings

log = logging.getLogger("luna.claude")

# Danh sách model cho admin chọn per-tenant (value = --model; "" = mặc định CLI).
# Nguồn sự thật duy nhất: web (dropdown + validate) import từ đây.
MODEL_CHOICES: list[tuple[str, str]] = [
    ("", "Default (CLI)"),
    ("claude-sonnet-4-6", "Sonnet 4.6"),
    ("claude-opus-4-8", "Opus 4.8"),
    ("claude-haiku-4-5", "Haiku 4.5"),
]
MODEL_IDS: frozenset[str] = frozenset(v for v, _ in MODEL_CHOICES)


def model_label(value: str | None) -> str:
    """Nhãn hiển thị cho 1 model id ('' → 'Default (CLI)'). Không khớp ⇒ trả chính id."""
    v = (value or "").strip()
    for mid, label in MODEL_CHOICES:
        if mid == v:
            return label
    return v


class PermissionMode(str, Enum):
    """Map phase FSM → quyền của Claude.

    LƯU Ý: KHÔNG dùng "plan" của Claude Code cho phase phân tích — đó là chế độ tương
    tác, Claude sẽ chờ người bấm "Approve" trên UI để thoát, kẹt khi chạy headless.
    Dùng "default": Claude đọc bằng Read/Grep/Glob không cần prompt, không sửa file
    (system prompt ràng buộc chỉ-đọc).
    """

    READONLY = "default"              # chỉ-đọc: ANALYZING / CLARIFYING / PLAN_REVIEW
    BYPASS = "bypassPermissions"      # thực thi: EXECUTING


@dataclass
class ClaudeResult:
    """Kết quả 1 lần chạy Claude. `ok=False` ⇒ Orchestrator KHÔNG được tự chuyển state."""

    ok: bool
    result: str                       # text trả về (hoặc thông báo lỗi để hiển thị)
    session_id: str | None            # dùng cho --resume lần sau
    is_error: bool = False            # cờ is_error do Claude báo
    timed_out: bool = False
    returncode: int | None = None
    num_turns: int | None = None
    total_cost_usd: float | None = None
    raw: dict = field(default_factory=dict)  # JSON gốc, cho parser M5


def _build_env() -> dict[str, str]:
    """ENV cho subprocess. Inject OAuth token nếu có; KHÔNG log token."""
    env = os.environ.copy()
    token = get_settings().claude_code_oauth_token
    if token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = token
    return env


async def run_claude(
    *,
    prompt: str,
    cwd: Path | str,
    permission_mode: PermissionMode = PermissionMode.READONLY,
    session_id: str | None = None,
    system_prompt: str | None = None,
    timeout_s: int | None = None,
    claude_bin: str = "claude",
    model: str | None = None,
) -> ClaudeResult:
    """Chạy `claude -p` trong `cwd`, trả ClaudeResult.

    - `system_prompt`: nối thêm qua --append-system-prompt (ràng buộc phase, format JSON).
    - `session_id`: có ⇒ --resume để giữ ngữ cảnh xuyên vòng đời request.
    - `model`: có ⇒ --model để ghim model (per-tenant); rỗng/None ⇒ mặc định CLI.
    - Lỗi (timeout / returncode≠0 / parse fail / is_error) ⇒ ok=False, không raise.
    """
    settings = get_settings()
    timeout = timeout_s if timeout_s is not None else settings.claude_timeout_s
    cwd = Path(cwd)

    args = [
        claude_bin, "-p", prompt,
        "--output-format", "json",
        "--permission-mode", permission_mode.value,
    ]
    if model:
        args += ["--model", model]
    if system_prompt:
        args += ["--append-system-prompt", system_prompt]
    if session_id:
        args += ["--resume", session_id]

    log.info(
        "claude run: cwd=%s mode=%s resume=%s prompt_len=%d",
        cwd, permission_mode.value, bool(session_id), len(prompt),
    )

    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=str(cwd),
            env=_build_env(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return ClaudeResult(
            ok=False, is_error=True, session_id=session_id,
            result=f"❌ Không tìm thấy lệnh '{claude_bin}'. Claude CLI đã cài chưa?",
        )

    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        log.warning("claude timeout sau %ds (cwd=%s)", timeout, cwd)
        return ClaudeResult(
            ok=False, is_error=True, timed_out=True, session_id=session_id,
            result=f"⏱ Tác vụ vượt {timeout // 60} phút, đã huỷ.",
        )

    rc = proc.returncode
    stdout = out.decode(errors="replace")
    stderr = err.decode(errors="replace")

    # returncode≠0 và không có stdout JSON → lỗi hạ tầng (auth, crash…).
    if rc != 0 and not stdout.strip():
        log.error("claude exit %s, stderr=%s", rc, stderr[:500])
        return ClaudeResult(
            ok=False, is_error=True, returncode=rc, session_id=session_id,
            result=f"❌ Claude lỗi (code {rc}):\n{stderr[:1500]}",
        )

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        log.error("claude output không parse được (rc=%s)", rc)
        return ClaudeResult(
            ok=False, is_error=True, returncode=rc, session_id=session_id,
            result=f"❌ Không parse được output:\n{stdout[:1500]}",
        )

    new_sid = data.get("session_id") or session_id
    result = data.get("result") or data.get("error") or "(rỗng)"
    is_err = bool(data.get("is_error"))

    return ClaudeResult(
        ok=not is_err,
        result=result,
        session_id=new_sid,
        is_error=is_err,
        returncode=rc,
        num_turns=data.get("num_turns"),
        total_cost_usd=data.get("total_cost_usd"),
        raw=data,
    )
