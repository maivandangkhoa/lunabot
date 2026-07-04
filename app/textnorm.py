"""Chuẩn hoá text người dùng gõ trước khi khớp từ khoá hành động (dùng chung
dispatcher + branch_sync — KHÔNG import lẫn nhau để tránh vòng import).

Nhãn nút của bot có tiền tố emoji ("✅ Gộp vào", "✅ Đạt"…). Kênh không route click
về endpoint (Messenger/Zalo: quick-reply ephemeral, user hay gõ/echo lại NHÃN nút)
⇒ inbound tới dạng text "✅ Gộp vào" — nếu so thô sẽ trượt từ khoá "gộp vào".
"""
from __future__ import annotations

import unicodedata


def strip_symbols(s: str) -> str:
    """Giữ chữ (gồm dấu tiếng Việt/Hàn), số, khoảng trắng; bỏ emoji/ký hiệu; gộp khoảng
    trắng. Khớp vẫn theo NGUYÊN CỤM (không tách token) nên "fix bug" không lọt."""
    kept = "".join(ch if (unicodedata.category(ch)[0] in ("L", "N", "M") or ch.isspace())
                   else " " for ch in s)
    return " ".join(kept.split())
