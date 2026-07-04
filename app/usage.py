"""Đo lượng dùng Claude per-tenant — ghi 1 dòng `usage_records` cho MỖI lần chạy CLI.

Nguồn dữ liệu: JSON output của `claude -p --output-format json` (đã nằm sẵn trong
`ClaudeResult.raw`): `usage` (token), `modelUsage` (breakdown theo model), `total_cost_usd`
(chi phí QUY ĐỔI API — được báo kể cả khi auth bằng OAuth subscription), `duration_ms`,
`num_turns`. `cost_usd` là đơn vị chuẩn để so tenant với quota account & định giá.

Nguyên tắc: ghi BEST-EFFORT — đo lường KHÔNG BAO GIỜ được làm hỏng FSM/luồng chat.
`record()` nuốt mọi exception (log lại), caller không cần try/except.

Phát hiện đụng trần subscription (`status="limit"`): CLI trả lỗi dạng "usage limit
reached" khi hết quota 5h/tuần — đánh dấu để calibrate quota thực tế của plan
(tổng cost_usd tích luỹ tới lúc đụng trần ≈ trần quy đổi USD).
"""
from __future__ import annotations

import logging
import re

from sqlalchemy.orm import Session

from app.claude_runner import ClaudeResult
from app.config import get_settings
from app.models import UsageRecord

log = logging.getLogger("luna.usage")

# Thông điệp CLI khi hết quota subscription / bị rate-limit API. Khớp lỏng (case-insensitive)
# vì format thay đổi theo phiên bản CLI ("Claude AI usage limit reached|<ts>", "5-hour limit
# reached", "rate limit exceeded"…).
_LIMIT_RE = re.compile(r"usage limit|limit reached|rate.?limit", re.IGNORECASE)


def _status(res: ClaudeResult) -> str:
    if _LIMIT_RE.search(res.result or ""):
        return "limit"
    return "ok" if res.ok else "error"


def _auth_mode() -> str:
    return "subscription" if get_settings().claude_code_oauth_token else "api"


def _int(val: object) -> int:
    try:
        return int(val)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def record(db: Session, *, tenant_id: int, phase: str, res: ClaudeResult,
           request_id: int | None = None) -> UsageRecord | None:
    """Ghi 1 dòng usage cho lần chạy `res` (kể cả lần lỗi — để thấy limit-hit/timeout).

    Commit NGAY (dòng usage độc lập, không chờ transaction nghiệp vụ của caller — mọi call
    site đều commit quanh đó nên không rò state dở dang). Lỗi ghi → rollback + log, trả None.
    """
    raw = res.raw or {}
    u = raw.get("usage") or {}
    try:
        rec = UsageRecord(
            tenant_id=tenant_id,
            request_id=request_id,
            phase=phase[:32],
            status=_status(res),
            auth_mode=_auth_mode(),
            input_tokens=_int(u.get("input_tokens")),
            output_tokens=_int(u.get("output_tokens")),
            cache_read_tokens=_int(u.get("cache_read_input_tokens")),
            cache_creation_tokens=_int(u.get("cache_creation_input_tokens")),
            cost_usd=raw.get("total_cost_usd"),
            duration_ms=raw.get("duration_ms"),
            num_turns=res.num_turns,
            model_usage=raw.get("modelUsage"),
        )
        db.add(rec)
        db.commit()
        return rec
    except Exception:  # noqa: BLE001 — đo lường không được chặn nghiệp vụ
        log.exception("ghi usage lỗi (tenant=%s phase=%s)", tenant_id, phase)
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return None
