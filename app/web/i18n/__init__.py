"""i18n cho web UI — đa ngôn ngữ Việt / Anh / Hàn.

Không thêm dependency: dùng `contextvars` để giữ ngôn ngữ hiện tại theo từng request
(async-safe), nên các hàm render trong styles/templates/landing_sections GIỮ NGUYÊN chữ ký
— chỉ cần gọi `t("key")` để lấy chuỗi đã dịch. Route set ngôn ngữ 1 lần đầu mỗi request
(đọc cookie → Accept-Language → mặc định vi).

Catalog tách theo nhóm để mỗi file ≤500 LOC: `catalog_app` (shell/wizard/done/dashboard)
và `catalog_landing` (landing hero + các section marketing).
"""
from __future__ import annotations

import contextvars
import re

from app.web.i18n.catalog_app import TEXTS as _APP
from app.web.i18n.catalog_bot_admin import TEXTS as _BOT_ADMIN
from app.web.i18n.catalog_bot_core import TEXTS as _BOT_CORE
from app.web.i18n.catalog_bot_ops import TEXTS as _BOT_OPS
from app.web.i18n.catalog_bot_orch import TEXTS as _BOT_ORCH
from app.web.i18n.catalog_bot_report import TEXTS as _BOT_REPORT
from app.web.i18n.catalog_landing import TEXTS as _LANDING

# Mã ISO 639-1 → tên hiển thị (đúng ngôn ngữ bản địa)
LANGS: dict[str, str] = {"vi": "Tiếng Việt", "en": "English", "ko": "한국어"}
DEFAULT = "vi"
COOKIE = "luna_lang"

TEXTS: dict[str, dict[str, str]] = {
    **_APP, **_LANDING, **_BOT_ORCH, **_BOT_CORE, **_BOT_ADMIN, **_BOT_OPS, **_BOT_REPORT,
}

_current: contextvars.ContextVar[str] = contextvars.ContextVar("luna_lang", default=DEFAULT)


def normalize(code: str | None) -> str:
    """Chuẩn hoá mã ngôn ngữ về 1 trong LANGS, fallback DEFAULT."""
    if not code:
        return DEFAULT
    c = code.strip().lower()[:2]
    return c if c in LANGS else DEFAULT


# Phát hiện ngôn ngữ từ NỘI DUNG người dùng gõ (heuristic, không gọi API):
#   Hangul → ko · dấu Latin (tiếng Việt có dấu) hoặc từ-khoá Việt không dấu → vi · đủ Latin → en.
_HANGUL = re.compile(r"[가-힣ᄀ-ᇿ㄰-㆏]")
_VI_DIACRITIC = re.compile(r"[À-ɏḀ-ỿ]")
# Từ tiếng Việt KHÔNG DẤU đặc trưng (tránh trùng từ tiếng Anh phổ biến) — bắt câu Việt gõ không dấu.
_VI_WORD = re.compile(
    r"\b(toi|minh|ban|khong|duoc|sua|loi|giup|gium|nhe|voi|muon|lam|dang|nhap|"
    r"hinh|trang|chuc|nang|hay|xoa|sai|chay|tinh|loi|nut|man)\b"
)
_ASCII_LETTER = re.compile(r"[A-Za-z]")


def detect(text: str | None) -> str | None:
    """Suy ngôn ngữ (vi/en/ko) từ nội dung người dùng gõ. Trả None khi KHÔNG đủ tín hiệu
    chắc chắn — caller giữ ngôn ngữ đã biết thay vì đoán bừa (vd 'ok', 'y', emoji, số)."""
    if not text:
        return None
    if _HANGUL.search(text):
        return "ko"
    if _VI_DIACRITIC.search(text):
        return "vi"
    if _VI_WORD.search(text.lower()):
        return "vi"
    if len(_ASCII_LETTER.findall(text)) >= 8:   # đủ dài để chắc tiếng Anh (tránh từ ngắn 'ok'/'no')
        return "en"
    return None


def pick(cookie: str | None, accept_language: str | None) -> str:
    """Chọn ngôn ngữ: cookie người dùng đã chọn > Accept-Language của trình duyệt > vi."""
    if cookie:
        c = cookie.strip().lower()
        if c in LANGS:
            return c
    if accept_language:
        for part in accept_language.split(","):
            c = part.split(";")[0].strip().lower()[:2]
            if c in LANGS:
                return c
    return DEFAULT


def set_lang(code: str | None) -> str:
    lang = normalize(code)
    _current.set(lang)
    return lang


def get_lang() -> str:
    return _current.get()


def t(key: str, /, **fmt: object) -> str:
    """Trả chuỗi đã dịch cho ngôn ngữ hiện tại. Thiếu key → trả về chính key (dễ phát hiện)."""
    entry = TEXTS.get(key)
    if entry is None:
        return key
    lang = get_lang()
    s = entry.get(lang) or entry.get(DEFAULT) or entry.get("en") or key
    return s.format(**fmt) if fmt else s
