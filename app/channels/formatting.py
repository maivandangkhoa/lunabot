"""Chuyển markdown (kiểu GitHub) mà bot/Claude sinh ra sang định dạng từng nền tảng chat.

Bot xuất markdown chuẩn: `**đậm**`, `*nghiêng*`/`_nghiêng_`, `` `code` ``, ```` ```block``` ````,
`# heading`, `- bullet`, `[text](url)`. Mỗi nền tảng render khác nhau:
- **telegram**: dùng HTML (`<b>`,`<i>`,`<code>`,`<pre>`,`<a>`) + `parse_mode="HTML"`.
- **google_chat**: markup riêng — in đậm là **1 dấu sao** `*đậm*` (không phải `**`), `_nghiêng_`,
  `` `code` ``, link `<url|text>`.
- **messenger / zalo**: KHÔNG có rich text → strip về plain text gọn (bỏ dấu markdown).

Quy ước an toàn:
- Tách code (fenced + inline) ra placeholder TRƯỚC, convert phần còn lại, rồi chèn lại — để dấu
  `*`/`_` bên trong code không bị hiểu nhầm là định dạng.
- Lookbehind/ahead chặn `_` giữa định danh snake_case (`active_repo_id`) khỏi bị coi là nghiêng.
- `format_for` trả `(text, parse_mode)`; `parse_mode` chỉ Telegram dùng, None với platform khác.
"""
from __future__ import annotations

import html
import re

# Code: fenced ```...``` (giữ nội dung, bỏ dòng ngôn ngữ) và inline `...`.
_FENCE_RE = re.compile(r"```[^\n]*\n?(.*?)```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_PLACEHOLDER_RE = re.compile("\x00(\\d+)\x00")

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__", re.DOTALL)
_HEADING_RE = re.compile(r"(?m)^[ \t]*#{1,6}[ \t]+(.+?)[ \t]*$")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
# Nghiêng: 1 dấu `*`/`_` không kề ký tự định danh (tránh snake_case + bullet "* ").
_ITALIC_STAR_RE = re.compile(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])")
_ITALIC_US_RE = re.compile(r"(?<![\w_])_(?!\s)([^_\n]+?)(?<!\s)_(?![\w_])")


def _extract_code(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Thay code bằng placeholder \\x00N\\x00, trả (text, [(kind, content)])."""
    blocks: list[tuple[str, str]] = []

    def stash(kind: str):
        def repl(m: re.Match) -> str:
            blocks.append((kind, m.group(1)))
            return f"\x00{len(blocks) - 1}\x00"
        return repl

    text = _FENCE_RE.sub(stash("pre"), text)
    text = _INLINE_CODE_RE.sub(stash("code"), text)
    return text, blocks


def _bold(text: str, render) -> str:
    return _BOLD_RE.sub(lambda m: render(m.group(1) if m.group(1) is not None else m.group(2)), text)


def _headings(text: str, render) -> str:
    return _HEADING_RE.sub(lambda m: render(m.group(1)), text)


def _links(text: str, render) -> str:
    return _LINK_RE.sub(lambda m: render(m.group(1), m.group(2)), text)


def _italic(text: str, render) -> str:
    text = _ITALIC_STAR_RE.sub(lambda m: render(m.group(1)), text)
    return _ITALIC_US_RE.sub(lambda m: render(m.group(1)), text)


def to_telegram_html(text: str) -> str:
    """Markdown → Telegram HTML. Escape `& < >` ở phần text (và trong code) để không vỡ parse."""
    body, blocks = _extract_code(text)
    body = html.escape(body, quote=False)
    body = _headings(body, lambda t: f"<b>{t}</b>")
    body = _bold(body, lambda t: f"<b>{t}</b>")
    body = _italic(body, lambda t: f"<i>{t}</i>")
    body = _links(body, lambda t, u: f'<a href="{html.escape(u, quote=True)}">{t}</a>')

    def restore(m: re.Match) -> str:
        kind, content = blocks[int(m.group(1))]
        esc = html.escape(content, quote=False)
        return f"<pre>{esc}</pre>" if kind == "pre" else f"<code>{esc}</code>"

    return _PLACEHOLDER_RE.sub(restore, body)


def to_google_chat(text: str) -> str:
    """Markdown → Google Chat markup: `**`→`*` (đậm 1 sao), giữ `_nghiêng_`, link `<url|text>`."""
    body, blocks = _extract_code(text)
    body = _headings(body, lambda t: f"*{t}*")
    body = _bold(body, lambda t: f"*{t}*")
    body = _links(body, lambda t, u: f"<{u}|{t}>")

    def restore(m: re.Match) -> str:
        kind, content = blocks[int(m.group(1))]
        return f"```\n{content}\n```" if kind == "pre" else f"`{content}`"

    return _PLACEHOLDER_RE.sub(restore, body)


def to_slack(text: str) -> str:
    """Markdown → Slack mrkdwn: `**`→`*` (đậm), `_nghiêng_`, link `<url|text>`, code giữ nguyên.

    Stash bold+heading thành placeholder trước, xử lý italic, rồi restore — tránh _italic
    biến `*bold*` (vừa convert từ `**bold**`) thành `_bold_` nhầm.
    """
    body, blocks = _extract_code(text)

    # Stash bold / heading trước để _italic không nhầm `*bold*` kết quả là italic.
    bold_stash: list[str] = []
    _BOLD_STASH_RE = re.compile(r"\x01(\d+)\x01")

    def _stash(content: str) -> str:
        bold_stash.append(content)
        return f"\x01{len(bold_stash) - 1}\x01"

    body = _BOLD_RE.sub(lambda m: _stash(m.group(1) if m.group(1) is not None else m.group(2)), body)
    body = _HEADING_RE.sub(lambda m: _stash(m.group(1)), body)

    body = _italic(body, lambda t: f"_{t}_")
    body = _links(body, lambda t, u: f"<{u}|{t}>")

    # Restore bold/heading → Slack *bold*
    body = _BOLD_STASH_RE.sub(lambda m: f"*{bold_stash[int(m.group(1))]}*", body)

    def restore(m: re.Match) -> str:
        kind, content = blocks[int(m.group(1))]
        return f"```{content}```" if kind == "pre" else f"`{content}`"

    return _PLACEHOLDER_RE.sub(restore, body)


def to_plain(text: str) -> str:
    """Markdown → plain text gọn (messenger/zalo): bỏ dấu định dạng, link thành `text (url)`."""
    body, blocks = _extract_code(text)
    body = _headings(body, lambda t: t)
    body = _bold(body, lambda t: t)
    body = _italic(body, lambda t: t)
    body = _links(body, lambda t, u: f"{t} ({u})")

    def restore(m: re.Match) -> str:
        _, content = blocks[int(m.group(1))]
        return content

    return _PLACEHOLDER_RE.sub(restore, body)


def format_for(platform: str, text: str) -> tuple[str, str | None]:
    """Trả `(text_đã_format, parse_mode)`. `parse_mode` chỉ Telegram dùng (HTML), None còn lại."""
    if not text:
        return text, None
    if platform == "telegram":
        return to_telegram_html(text), "HTML"
    if platform == "google_chat":
        return to_google_chat(text), None
    if platform == "slack":
        return to_slack(text), None
    return to_plain(text), None  # messenger, zalo, mặc định


def split_chunks(text: str, max_len: int) -> list[str]:
    """Cắt `text` thành các đoạn ≤ max_len, ưu tiên ranh giới xuống dòng để KHÔNG cắt giữa thẻ
    inline (`<b>`/`*..*`) — các thẻ inline không chứa newline nên cắt ở `\\n` luôn an toàn."""
    if len(text) <= max_len:
        return [text] if text else [""]
    chunks: list[str] = []
    rest = text
    while len(rest) > max_len:
        cut = rest.rfind("\n", 0, max_len)
        if cut <= 0:
            cut = max_len
        chunks.append(rest[:cut])
        rest = rest[cut:].lstrip("\n")
    if rest:
        chunks.append(rest)
    return chunks or [""]
