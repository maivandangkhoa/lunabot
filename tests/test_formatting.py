"""Tests app/channels/formatting.py — markdown của bot → định dạng từng nền tảng + chunk an toàn."""
from app.channels.formatting import (
    format_for,
    split_chunks,
    to_google_chat,
    to_plain,
    to_telegram_html,
)


# ── Telegram HTML ──
def test_tg_bold_italic_code():
    assert to_telegram_html("**đậm** và *nghiêng* và `code`") == (
        "<b>đậm</b> và <i>nghiêng</i> và <code>code</code>"
    )


def test_tg_double_underscore_bold_single_underscore_italic():
    assert to_telegram_html("__đậm__ _nghiêng_") == "<b>đậm</b> <i>nghiêng</i>"


def test_tg_escapes_html_specials():
    assert to_telegram_html("a < b & c > d") == "a &lt; b &amp; c &gt; d"


def test_tg_snake_case_not_italicized():
    # active_repo_id KHÔNG được hiểu là nghiêng "repo".
    assert to_telegram_html("active_repo_id") == "active_repo_id"


def test_tg_heading_to_bold():
    assert to_telegram_html("# Tiêu đề") == "<b>Tiêu đề</b>"


def test_tg_numbered_list_with_bold():
    # Đúng case trong ảnh: "1. **Tính năng này phục vụ ai?**"
    assert to_telegram_html("1. **Phục vụ ai?**") == "1. <b>Phục vụ ai?</b>"


def test_tg_link():
    assert to_telegram_html("[luna](https://x.io)") == '<a href="https://x.io">luna</a>'


def test_tg_code_block_preserves_stars_inside():
    out = to_telegram_html("```\na = b ** 2\n```")
    # `**` bên trong code KHÔNG bị coi là đậm; newline mở fence được lược bỏ.
    assert out == "<pre>a = b ** 2\n</pre>"


def test_tg_emoji_and_dashes_untouched():
    assert to_telegram_html("❓ câu hỏi\n———") == "❓ câu hỏi\n———"


# ── Google Chat (đậm = 1 dấu sao) ──
def test_gchat_bold_becomes_single_star():
    assert to_google_chat("**Phục vụ ai?**") == "*Phục vụ ai?*"


def test_gchat_keeps_italic_underscore_and_code():
    assert to_google_chat("_nghiêng_ `code`") == "_nghiêng_ `code`"


def test_gchat_link_format():
    assert to_google_chat("[luna](https://x.io)") == "<https://x.io|luna>"


def test_gchat_heading_to_bold():
    assert to_google_chat("## Mục") == "*Mục*"


# ── Plain (messenger/zalo) ──
def test_plain_strips_all_markers():
    assert to_plain("**đậm** *nghiêng* `code`") == "đậm nghiêng code"


def test_plain_link_to_text_and_url():
    assert to_plain("[luna](https://x.io)") == "luna (https://x.io)"


def test_plain_heading_kept_as_text():
    assert to_plain("# Tiêu đề") == "Tiêu đề"


# ── format_for dispatch ──
def test_format_for_telegram_sets_html_mode():
    body, mode = format_for("telegram", "**x**")
    assert body == "<b>x</b>" and mode == "HTML"


def test_format_for_other_platforms_no_parse_mode():
    assert format_for("google_chat", "**x**") == ("*x*", None)
    assert format_for("messenger", "**x**") == ("x", None)
    assert format_for("zalo", "**x**") == ("x", None)


def test_format_for_empty():
    assert format_for("telegram", "") == ("", None)


# ── split_chunks ──
def test_split_short_text_single_chunk():
    assert split_chunks("hello", 100) == ["hello"]


def test_split_empty_text():
    assert split_chunks("", 100) == [""]


def test_split_prefers_newline_boundary():
    text = "a" * 50 + "\n" + "b" * 50
    chunks = split_chunks(text, 60)
    assert chunks == ["a" * 50, "b" * 50]  # cắt ở \n, không giữa thẻ


def test_split_hard_cut_when_no_newline():
    chunks = split_chunks("x" * 9000, 4000)
    assert len(chunks) == 3 and "".join(chunks) == "x" * 9000
