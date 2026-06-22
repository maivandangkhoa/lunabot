"""Phát hiện ngôn ngữ từ nội dung người dùng gõ (Cách A) + áp vào _sync_user_language."""
from __future__ import annotations

import pytest

from app.channels.base import InboundMessage
from app.dispatcher import _sync_user_language
from app.models import User
from app.web.i18n import detect, get_lang


@pytest.mark.parametrize(
    "text,expected",
    [
        ("please fix the login bug now", "en"),
        ("sửa lỗi đăng nhập giúp em", "vi"),
        ("toi muon sua loi dang nhap", "vi"),       # tiếng Việt KHÔNG dấu
        ("로그인 버그를 고쳐주세요", "ko"),
        ("ok", None),                                # quá ngắn → không đoán bừa
        ("y", None),
        ("fix bug", None),                           # < 8 chữ cái → chưa chắc
        ("123 #45", None),
        ("", None),
        (None, None),
    ],
)
def test_detect(text, expected):
    assert detect(text) == expected


class _StubDB:
    def commit(self) -> None:  # _sync gọi commit khi đổi ngôn ngữ
        pass


def _inbound(text="", *, cb=None, lang=None) -> InboundMessage:
    return InboundMessage(platform="telegram", platform_user_id="1", text=text,
                          callback_data=cb, language_code=lang)


def test_sync_sets_language_from_content():
    u = User(language=None)
    _sync_user_language(_StubDB(), u, _inbound("please fix the login page right now"))
    assert u.language == "en"
    assert get_lang() == "en"


def test_sync_switches_language_on_confident_content():
    u = User(language="en")
    _sync_user_language(_StubDB(), u, _inbound("vui lòng sửa giúp trang đăng nhập"))
    assert u.language == "vi"


def test_sync_skips_command():
    u = User(language="vi")
    _sync_user_language(_StubDB(), u, _inbound("/repos"))
    assert u.language == "vi"          # lệnh không đại diện ngôn ngữ → giữ nguyên


def test_sync_skips_callback():
    u = User(language="vi")
    _sync_user_language(_StubDB(), u, _inbound("verify_ok:5", cb="verify_ok:5"))
    assert u.language == "vi"          # bấm nút không đại diện ngôn ngữ → giữ nguyên


def test_sync_keeps_language_when_unsure():
    u = User(language="ko")
    _sync_user_language(_StubDB(), u, _inbound("ok"))
    assert u.language == "ko"          # tín hiệu yếu → không đổi
