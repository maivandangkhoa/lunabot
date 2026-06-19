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

from app.web.i18n.catalog_app import TEXTS as _APP
from app.web.i18n.catalog_landing import TEXTS as _LANDING

# Mã ISO 639-1 → tên hiển thị (đúng ngôn ngữ bản địa)
LANGS: dict[str, str] = {"vi": "Tiếng Việt", "en": "English", "ko": "한국어"}
DEFAULT = "vi"
COOKIE = "luna_lang"

TEXTS: dict[str, dict[str, str]] = {**_APP, **_LANDING}

_current: contextvars.ContextVar[str] = contextvars.ContextVar("luna_lang", default=DEFAULT)


def normalize(code: str | None) -> str:
    """Chuẩn hoá mã ngôn ngữ về 1 trong LANGS, fallback DEFAULT."""
    if not code:
        return DEFAULT
    c = code.strip().lower()[:2]
    return c if c in LANGS else DEFAULT


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
