"""Trích & validate khối ```json cuối trong output Claude → tín hiệu chuyển FSM.

Nguyên tắc (gotcha trong plan): JSON từ Claude KHÔNG đảm bảo 100%. Nếu thiếu/parse fail/
sai schema → trả `ok=False`; Orchestrator KHÔNG được tự ý chuyển state, phải báo người can thiệp.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum

# Bắt mọi khối fenced ```json ... ``` (ưu tiên) hoặc ``` ... ``` (fallback).
_FENCED_JSON = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)
_FENCED_ANY = re.compile(r"```\s*(\{.*?\})\s*```", re.DOTALL)


class Action(str, Enum):
    CLARIFY = "clarify"          # → CLARIFYING (gửi câu hỏi)
    PLAN = "plan"                # → PLAN_REVIEW (xin confirm)
    IMPLEMENTED = "implemented"  # → VERIFY (đã push + PR)


# Field bắt buộc cho từng action.
_REQUIRED: dict[Action, tuple[str, ...]] = {
    Action.CLARIFY: ("questions",),
    Action.PLAN: ("summary", "steps"),
    Action.IMPLEMENTED: ("summary",),
}


@dataclass
class ParsedSignal:
    ok: bool
    action: Action | None = None
    data: dict = field(default_factory=dict)
    error: str | None = None


def _last_json_block(text: str) -> str | None:
    matches = _FENCED_JSON.findall(text) or _FENCED_ANY.findall(text)
    return matches[-1] if matches else None


def strip_json_block(text: str) -> str:
    """Bỏ khối ```json cuối → phần VĂN BẢN (câu trả lời/giải thích) Claude viết trước JSON."""
    if not text:
        return ""
    for pat in (_FENCED_JSON, _FENCED_ANY):
        matches = list(pat.finditer(text))
        if matches:
            last = matches[-1]
            return (text[: last.start()] + text[last.end():]).strip()
    return text.strip()


# Dấu hiệu Claude headless "tự nhận diện" là công cụ của NGƯỜI DÙNG và rò rỉ hướng dẫn
# permission nội bộ (vd khi bị chặn ghi file ở phase read-only). Text này KHÔNG bao giờ
# được lọt ra khách — họ không chạy Claude Code, không có nút 🔒, không có terminal.
_META_LEAK = re.compile(
    r"(?im)^.*("
    r"dangerously-skip-permissions"
    r"|claude\.ai/code"
    r"|claude\s+code"
    r"|permission[- ]mode"
    r"|bypasspermissions"
    r"|--resume"
    r"|🔒"
    r"|trust this project"
    r"|allow all"
    r").*$"
)


def scrub_meta(text: str) -> str:
    """Xoá mọi DÒNG chứa dấu hiệu meta về tooling/permission của Claude headless trước khi
    relay ra khách. Phòng thủ theo lớp: prompt đã cấm sinh loại text này, đây là lưới chặn
    cuối. Gộp các dòng trống thừa sau khi cắt để không để lại khoảng trắng lộ liễu."""
    if not text:
        return text
    cleaned = _META_LEAK.sub("", text)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def parse_signal(text: str) -> ParsedSignal:
    """Trích khối JSON cuối, validate action + field bắt buộc. Không bao giờ raise."""
    if not text:
        return ParsedSignal(ok=False, error="output rỗng")

    block = _last_json_block(text)
    if block is None:
        return ParsedSignal(ok=False, error="không tìm thấy khối ```json")

    try:
        data = json.loads(block)
    except json.JSONDecodeError as exc:
        return ParsedSignal(ok=False, error=f"JSON không hợp lệ: {exc}")

    if not isinstance(data, dict):
        return ParsedSignal(ok=False, error="JSON không phải object")

    raw_action = data.get("action")
    try:
        action = Action(raw_action)
    except ValueError:
        return ParsedSignal(ok=False, data=data, error=f"action không hợp lệ: {raw_action!r}")

    missing = [k for k in _REQUIRED[action] if not data.get(k)]
    if missing:
        return ParsedSignal(
            ok=False, action=action, data=data,
            error=f"thiếu field bắt buộc cho '{action.value}': {missing}",
        )

    # Chuẩn hoá nhẹ: các field dạng danh sách phải là list (Claude đôi khi trả 1 chuỗi).
    # changes/self_test/scope thuộc gói báo cáo nghiệp vụ của action "implemented" (tuỳ chọn).
    for k in ("questions", "steps", "changes", "self_test", "scope"):
        if k in data and isinstance(data[k], str):
            data[k] = [data[k]]

    return ParsedSignal(ok=True, action=action, data=data)
