"""Lớp 2 (LLM fallback) cho hành động cổng FSM bằng câu tự nhiên.

Lớp 1 là từ khoá cứng trong `dispatcher` (_W_CONFIRM/_W_EDIT/…): nhanh, tất định, kiểm
chứng được — dùng cho mọi quyết định ở cổng duyệt (duyệt KH / xác nhận đạt / cho merge).
Nhược điểm: user gõ "được rồi em ơi, triển khai đi" sẽ trượt vì không khớp từ khoá.

Lớp 2 chỉ vá NHƯỢC ĐIỂM đó, KHÔNG thay Lớp 1: khi từ khoá trượt mà user ĐANG có việc chờ
cổng, nhờ Claude chuẩn hoá câu tự nhiên về MỘT từ khoá canonical (ok/sửa/huỷ/từ chối) hoặc
"none". Từ khoá đó đi tiếp qua đúng pipeline keyword cũ (`_keyword_action` lọc theo status),
nên LLM KHÔNG BAO GIỜ tự bịa được action mà status không cho phép — nó chỉ MỞ RỘNG độ phủ
ngôn ngữ, không phải người gác cổng. App vẫn LUÔN xin xác nhận trước hành động không hoàn tác.

Cố ý KHÔNG dùng Anthropic API trực tiếp: tái dùng `run_claude` (CLI headless + OAuth
subscription) như phần còn lại của app — không thêm dependency/secret. Phân loại là việc nhẹ
→ session mới (không --resume), permission chỉ-đọc, timeout ngắn.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from textwrap import dedent

from app.claude_runner import PermissionMode, run_claude
from app.config import get_settings

log = logging.getLogger("luna.intent")


@dataclass
class Intent:
    """Kết quả phân loại: từ khoá canonical + độ chắc chắn LLM tự đánh giá (0..1).

    Caller (dispatcher) dùng `confidence` để quyết: đủ chắc → làm luôn; chưa chắc → xin xác
    nhận. Hành động KHÔNG hoàn tác (merge production) vẫn luôn xác nhận bất kể điểm số."""

    word: str
    confidence: float

# Ý định generic (LLM trả) → từ khoá canonical (Lớp 1 hiểu). `_keyword_action` đã mã hoá
# nghĩa-theo-status của các từ này: vd "ok" ở PLAN_REVIEW=duyệt, ở VERIFY=đạt, ở AWAIT_MANAGER
# =cho merge. Nhờ vậy chỉ cần ánh xạ ý định generic, status tự quyết nghĩa cụ thể.
_INTENT_TO_WORD: dict[str, str] = {
    "approve": "ok",        # đồng ý / chấp thuận / cho làm tiếp
    "edit": "sửa",          # muốn chỉnh sửa kế hoạch/kết quả
    "cancel": "huỷ",        # huỷ bỏ yêu cầu
    "reject": "từ chối",    # từ chối / không cho merge
}
_VALID = set(_INTENT_TO_WORD) | {"none"}

# Bắt object JSON phẳng (không lồng) — output phân loại là {"intent":"approve"}.
_OBJ = re.compile(r"\{[^{}]*\}", re.DOTALL)


def _system_prompt(statuses: str) -> str:
    """Ràng buộc Claude: KHÔNG dùng tool, chỉ phân loại 1 câu → 1 ý định, conservative."""
    return dedent(
        f"""
        Bạn là bộ PHÂN LOẠI Ý ĐỊNH. Người dùng đang có việc chờ ở cổng duyệt (trạng thái:
        {statuses}) và vừa nhắn một câu. Hãy xác định họ muốn làm gì với việc đang chờ đó.

        KHÔNG dùng bất kỳ công cụ nào (không Read/Grep/Bash). Chỉ đọc câu rồi phân loại.

        Các ý định:
        - "approve": đồng ý / chấp thuận / cho làm tiếp (duyệt kế hoạch, xác nhận đã đạt, cho merge).
          Vd: "ok làm đi", "được rồi triển khai", "nhìn ổn rồi nhé", "go ahead", "looks good".
        - "edit": muốn CHỈNH SỬA kế hoạch/kết quả trước khi đồng ý. Vd: "sửa lại bước 2", "đổi cách làm".
        - "cancel": muốn HUỶ BỎ yêu cầu này. Vd: "thôi bỏ đi", "huỷ nhé", "không cần nữa".
        - "reject": TỪ CHỐI / không cho merge. Vd: "không duyệt", "chưa cho lên production".
        - "none": KHÔNG thuộc các ý trên — đang mô tả yêu cầu mới, đặt câu hỏi, hay phản hồi chi
          tiết kỹ thuật. ĐÂY LÀ MẶC ĐỊNH khi không thật sự chắc chắn.

        Quy tắc an toàn: nếu PHÂN VÂN giữa một hành động và "none" → chọn "none". Thà bỏ sót còn
        hơn đoán nhầm một hành động không hoàn tác (app sẽ xin xác nhận lại nếu bạn chọn hành động).

        Kèm "confidence" = độ chắc chắn của BẠN về ý định, số thực 0..1. Hãy hiệu chỉnh THẬT:
        - ~0.9+ chỉ khi câu nói RÕ RÀNG, dứt khoát, không thể hiểu khác (vd "ok làm đi", "duyệt nhé").
        - ~0.6–0.8 khi nghiêng về một ý nhưng còn chỗ mơ hồ (vd "chắc ổn rồi", "thử xem sao").
        - < 0.6 khi khá lưỡng lự. KHÔNG bao giờ thổi điểm — app dựa vào đó để quyết có hỏi lại không.

        Trả lời bằng ĐÚNG MỘT khối ```json, không thêm chữ nào sau nó:
        ```json
        {{"intent":"approve|edit|cancel|reject|none","confidence":0.0}}
        ```
        """
    ).strip()


def _extract(out: str) -> tuple[str, float] | None:
    """Lấy (intent, confidence) từ object JSON CUỐI hợp lệ. None nếu không có/không hợp lệ.
    Confidence khuyết/sai kiểu → mặc định 0.5 (mơ hồ) và bị kẹp về [0,1]."""
    for block in reversed(_OBJ.findall(out or "")):
        try:
            data = json.loads(block)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(data, dict):
            val = str(data.get("intent", "")).strip().lower()
            if val in _VALID:
                try:
                    conf = float(data.get("confidence", 0.5))
                except (TypeError, ValueError):
                    conf = 0.5
                return val, max(0.0, min(1.0, conf))
    return None


async def classify_intent(text: str, statuses: list[str], *, run=run_claude) -> Intent | None:
    """Câu tự nhiên `text` → Intent(word canonical, confidence) cho `statuses` đang chờ, hoặc
    None nếu không phải hành động cổng / không chắc / lỗi.

    Cơ chế thuần: KHÔNG tự quyết bật-tắt (caller lo, xem config.intent_llm_enabled + token) —
    để unit-test tiêm `run` giả mà không phụ thuộc settings. KHÔNG raise.
    """
    text = (text or "").strip()
    if not text or not statuses:
        return None
    settings = get_settings()
    sys = _system_prompt(", ".join(sorted(set(statuses))))
    try:
        res = await run(
            prompt=text[:2000],
            cwd=settings.workspace,
            permission_mode=PermissionMode.READONLY,
            system_prompt=sys,
            timeout_s=settings.intent_timeout_s,
        )
    except Exception:  # noqa: BLE001 — phân loại lỗi KHÔNG được làm hỏng luồng chat
        log.exception("classify_intent: run_claude lỗi")
        return None
    if not res.ok:
        log.info("classify_intent: bỏ qua (run not ok)")
        return None
    parsed = _extract(res.result or "")
    if parsed is None or parsed[0] == "none":
        return None
    return Intent(word=_INTENT_TO_WORD[parsed[0]], confidence=parsed[1])
