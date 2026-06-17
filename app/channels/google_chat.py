"""GoogleChatAdapter — hiện thực ChannelAdapter qua Google Chat API (HTTP endpoint).

Khác Telegram ở 2 điểm cốt lõi (xem tasks/google-chat.md):
- **Outbound async**: FSM trả lời sau vài phút (Claude chạy xong) ⇒ KHÔNG thể trả trong
  HTTP response webhook (đã đóng). Dùng service account (OAuth2 JWT-bearer) gọi Chat REST.
  Map user→space bằng `spaces:findDirectMessage` (DB-free, dùng được cả cho manager).
- **Nút bấm = cardsV2** (event `CARD_CLICKED`), giữ nguyên convention callback_data
  ("action:rid") nên Orchestrator/dispatcher không đổi.

Auth inbound: verify Bearer JWT do chat@system.gserviceaccount.com ký (verify_google_jwt).
Token outbound tự ký bằng PyJWT[crypto] (đã có) — không thêm dependency google-auth.
Test: inject token_provider (bỏ ký thật) + httpx.MockTransport cho REST.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import httpx
import jwt

from app.channels.base import Attachment, Button, InboundMessage

log = logging.getLogger("luna.google_chat")

_CHAT_API = "https://chat.googleapis.com"
_TOKEN_URI = "https://oauth2.googleapis.com/token"
_SCOPE = "https://www.googleapis.com/auth/chat.bot"
# Chat app dạng "Workspace add-on / Interactive features" gửi **Google OIDC ID token**:
# iss=accounts.google.com, aud=<URL webhook>, email=service-<pn>@gcp-sa-gsuiteaddons...,
# ký bằng khoá OIDC chuẩn của Google (certs ở oauth2/v1/certs).
_GOOGLE_OIDC_CERTS = "https://www.googleapis.com/oauth2/v1/certs"
_GOOGLE_ISSUER = "https://accounts.google.com"
_ADDON_SA_TMPL = "service-{pn}@gcp-sa-gsuiteaddons.iam.gserviceaccount.com"
_MAX_LEN = 4000          # Chat ~4096/text widget — chừa biên.
_CB_PARAM = "cb"         # key trong button parameters chứa callback_data
_CB_FUNCTION = "luna_action"


# --------------------------------------------------------------------------- #
# Helpers (module-level, không trạng thái adapter)
# --------------------------------------------------------------------------- #
def load_sa_credentials(value: str | None) -> dict:
    """Đọc service account JSON từ đường dẫn file hoặc chuỗi JSON inline."""
    if not value:
        return {}
    p = Path(value)
    if p.exists():
        return json.loads(p.read_text())
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        log.warning("GOOGLE_CHAT_SA_JSON không phải path hợp lệ cũng không phải JSON.")
        return {}


def _parse_attachments(items: list) -> list[Attachment]:
    """message.attachment[] → list Attachment (chỉ giữ ảnh). resourceName để tải qua media API."""
    out: list[Attachment] = []
    for a in items:
        ct = a.get("contentType", "")
        if not ct.startswith("image/"):
            continue
        rn = a.get("attachmentDataRef", {}).get("resourceName")
        if rn:
            out.append(Attachment(a.get("contentName") or "image", ct, {"resource_name": rn}))
    return out


def _space_is_group(space_obj: dict) -> bool:
    """Space ROOM/SPACE (nhiều người) vs DM 1:1. Hỗ trợ cả `type` (classic) lẫn `spaceType` (mới)."""
    if not isinstance(space_obj, dict):
        return False
    return (space_obj.get("type") == "ROOM"
            or space_obj.get("spaceType") in ("SPACE", "GROUP_CHAT"))


def _extract_callback(raw: dict) -> str | None:
    """Lấy callback_data từ event CARD_CLICKED (hỗ trợ 2 shape API)."""
    params = raw.get("action", {}).get("parameters")
    if params:
        for p in params:
            if p.get("key") == _CB_PARAM:
                return p.get("value")
    common = raw.get("common", {}).get("parameters")
    if isinstance(common, dict) and _CB_PARAM in common:
        return common[_CB_PARAM]
    return None


_certs_cache: dict[str, dict] = {}   # keyed theo URL certs
_certs_exp: dict[str, float] = {}


async def _fetch_certs(url: str, client: httpx.AsyncClient | None = None) -> dict:
    """Lấy public x509 certs ({kid: PEM}) từ 1 URL (cache 1h)."""
    now = time.time()
    if url in _certs_cache and now < _certs_exp.get(url, 0):
        return _certs_cache[url]
    owns = client is None
    client = client or httpx.AsyncClient(timeout=15)
    try:
        resp = await client.get(url)
        _certs_cache[url] = resp.json()
        _certs_exp[url] = now + 3600
        return _certs_cache[url]
    finally:
        if owns:
            await client.aclose()


def _pem_to_pubkey(cert_pem: str):
    from cryptography.x509 import load_pem_x509_certificate

    return load_pem_x509_certificate(cert_pem.encode()).public_key()


async def verify_google_jwt(
    token: str, audience: str, *, expected_email: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> None:
    """Verify Google OIDC ID token Google gửi kèm webhook (Workspace add-on). Raise nếu sai.

    iss=accounts.google.com; aud=URL webhook; ký bằng khoá OIDC Google (oauth2/v1/certs).
    expected_email (tuỳ chọn): xác nhận token do đúng SA gsuiteaddons của project phát hành.
    """
    certs = await _fetch_certs(_GOOGLE_OIDC_CERTS, client)
    kid = jwt.get_unverified_header(token).get("kid")
    cert_pem = certs.get(kid or "")
    if not cert_pem:
        raise ValueError("kid không khớp cert Google")
    claims = jwt.decode(
        token,
        _pem_to_pubkey(cert_pem),
        algorithms=["RS256"],
        audience=audience,
        issuer=_GOOGLE_ISSUER,
    )
    if expected_email and claims.get("email") != expected_email:
        raise ValueError(f"email không khớp: {claims.get('email')}")


# --------------------------------------------------------------------------- #
# Adapter
# --------------------------------------------------------------------------- #
@dataclass
class GoogleChatAdapter:
    sa_credentials: dict = field(default_factory=dict)
    api_base: str = _CHAT_API
    client: httpx.AsyncClient | None = None
    # Test inject: trả thẳng access token, bỏ ký JWT + gọi mạng.
    token_provider: Callable[[], str] | None = None
    name: str = "google_chat"
    _token: str | None = field(default=None, init=False)
    _token_exp: float = field(default=0.0, init=False)
    _space_cache: dict[str, str] = field(default_factory=dict, init=False)
    # space → thread gần nhất thấy ở space đó. Để reply nằm cùng thread tin đến (space threaded).
    _thread_cache: dict[str, str] = field(default_factory=dict, init=False)

    @classmethod
    def from_settings(cls, settings=None) -> "GoogleChatAdapter":
        from app.config import get_settings

        s = settings or get_settings()
        return cls(sa_credentials=load_sa_credentials(s.google_chat_sa_json))

    def _http(self) -> httpx.AsyncClient:
        if self.client is None:
            self.client = httpx.AsyncClient(base_url=self.api_base, timeout=30)
        return self.client

    async def aclose(self) -> None:
        if self.client is not None:
            await self.client.aclose()
            self.client = None

    # ----- Auth (service account → access token) -----
    def _make_jwt(self) -> str:
        now = int(time.time())
        payload = {
            "iss": self.sa_credentials["client_email"],
            "scope": _SCOPE,
            "aud": _TOKEN_URI,
            "iat": now,
            "exp": now + 3600,
        }
        return jwt.encode(payload, self.sa_credentials["private_key"], algorithm="RS256")

    async def _access_token(self) -> str:
        if self.token_provider is not None:
            return self.token_provider()
        now = time.time()
        if self._token and now < self._token_exp - 60:
            return self._token
        resp = await self._http().post(
            _TOKEN_URI,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": self._make_jwt(),
            },
        )
        data = resp.json()
        self._token = data["access_token"]
        self._token_exp = now + data.get("expires_in", 3600)
        return self._token

    async def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {await self._access_token()}"}

    # ----- Inbound -----
    def parse_inbound(self, raw: dict) -> InboundMessage:
        if "chat" in raw:                       # Workspace add-on (định dạng thật)
            return self._parse_addon(raw)
        return self._parse_classic(raw)         # classic Chat API (fallback/tests)

    def _parse_addon(self, raw: dict) -> InboundMessage:
        """Event Workspace add-on: user/space/text/attachment lồng dưới chat.*."""
        chat = raw.get("chat", {})
        uid = chat.get("user", {}).get("name", "")
        text, callback, space_obj, thread = "", None, {}, None
        attachments: list[Attachment] = []
        if "messagePayload" in chat:
            mp = chat["messagePayload"]
            msg = mp.get("message", {})
            space_obj = mp.get("space") or msg.get("space") or {}
            thread = (msg.get("thread") or {}).get("name")
            # Trong group, msg["text"] dính mention bot ("@Luna ok"); argumentText là phần
            # đã bỏ mention ("ok") → ưu tiên nó để khớp từ khoá hành động (ok/sửa/huỷ).
            text = (msg.get("argumentText") or msg.get("text") or "").strip()
            attachments = _parse_attachments(msg.get("attachment") or [])
        elif "buttonClickedPayload" in chat:
            bp = chat["buttonClickedPayload"]
            bmsg = bp.get("message", {})
            space_obj = bp.get("space") or bmsg.get("space") or {}
            thread = (bmsg.get("thread") or {}).get("name")
            params = raw.get("commonEventObject", {}).get("parameters", {})
            callback = params.get(_CB_PARAM) or _extract_callback(bp)
            text = callback or ""
        elif "addedToSpacePayload" in chat:
            space_obj = chat["addedToSpacePayload"].get("space", {})
        space = space_obj.get("name")
        if space and uid:
            self._space_cache[uid] = space      # nhớ space để reply trong cùng flow
        if space and thread:
            self._thread_cache[space] = thread  # nhớ thread để reply cùng mạch (space threaded)
        return InboundMessage(
            platform=self.name, platform_user_id=uid, text=text,
            callback_data=callback, chat_id=space, is_group=_space_is_group(space_obj),
            attachments=attachments, raw=raw,
        )

    def _parse_classic(self, raw: dict) -> InboundMessage:
        uid = raw.get("user", {}).get("name", "")
        space_obj = raw.get("space", {})
        space = space_obj.get("name")
        is_group = _space_is_group(space_obj)
        thread = (raw.get("message", {}).get("thread") or {}).get("name")
        if space and uid:
            self._space_cache[uid] = space
        if space and thread:
            self._thread_cache[space] = thread
        if raw.get("type") == "CARD_CLICKED":
            cbdata = _extract_callback(raw)
            return InboundMessage(
                platform=self.name, platform_user_id=uid, text=cbdata or "",
                callback_data=cbdata, chat_id=space, is_group=is_group, raw=raw,
            )
        msg = raw.get("message", {})
        return InboundMessage(
            platform=self.name, platform_user_id=uid,
            text=msg.get("text", "") or "", callback_data=None, chat_id=space,
            is_group=is_group, raw=raw,
        )

    # ----- Outbound -----
    async def _resolve_space(self, platform_user_id: str) -> str | None:
        """user (users/123) → DM space (spaces/AAA). Cache theo user."""
        if platform_user_id in self._space_cache:
            return self._space_cache[platform_user_id]
        resp = await self._http().get(
            "/v1/spaces:findDirectMessage",
            params={"name": platform_user_id},
            headers=await self._headers(),
        )
        if resp.status_code != 200:
            log.warning("findDirectMessage %s lỗi %s: %s",
                        platform_user_id, resp.status_code, resp.text[:200])
            return None
        space = resp.json().get("name")
        if space:
            self._space_cache[platform_user_id] = space
        return space

    def _cards(self, buttons: list[list[Button]] | None) -> list[dict] | None:
        if not buttons:
            return None
        widgets = [
            {"buttonList": {"buttons": [
                {"text": b.text, "onClick": {"action": {
                    "function": _CB_FUNCTION,
                    "parameters": [{"key": _CB_PARAM, "value": b.callback_data}],
                }}}
                for b in row
            ]}}
            for row in buttons
        ]
        return [{"card": {"sections": [{"widgets": widgets}]}}]

    async def send(
        self,
        destination: str,
        text: str,
        buttons: list[list[Button]] | None = None,
    ) -> dict:
        """Gửi tin tới `destination` (chunk nếu dài; cards gắn chunk cuối). `destination` là
        space sẵn (`spaces/...`, vd group/origin) → gửi thẳng; là user (`users/...`) → resolve DM."""
        space = destination if destination.startswith("spaces/") else await self._resolve_space(destination)
        if not space:
            log.warning("Không tìm được space cho %s — bỏ gửi.", destination)
            return {}
        headers = await self._headers()
        # Reply cùng thread tin đến (space threaded). FALLBACK_TO_NEW_THREAD: space flat thì
        # tham số vô hại, không có thread thì gửi như thường.
        thread = self._thread_cache.get(space)
        params = {"messageReplyOption": "REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"} if thread else None
        chunks = [text[i : i + _MAX_LEN] for i in range(0, len(text), _MAX_LEN)] or [""]
        result: dict = {}
        for idx, chunk in enumerate(chunks):
            payload: dict[str, Any] = {"text": chunk}
            if thread:
                payload["thread"] = {"name": thread}
            if idx == len(chunks) - 1:
                cards = self._cards(buttons)
                if cards:
                    payload["cardsV2"] = cards
            resp = await self._http().post(
                f"/v1/{space}/messages", json=payload, headers=headers, params=params
            )
            if resp.status_code >= 300:
                log.warning("Chat sendMessage lỗi %s: %s", resp.status_code, resp.text[:200])
            else:
                result = resp.json()
        return result

    async def answer_callback(self, callback_id: str, text: str | None = None) -> dict:
        """Google Chat không có spinner để tắt — no-op cho hợp protocol."""
        return {}

    async def download_attachment(self, attachment: Attachment) -> bytes:
        """Tải nội dung attachment qua Chat media API: GET /v1/media/{resourceName}?alt=media."""
        from urllib.parse import quote

        rn = attachment.ref.get("resource_name", "")
        resp = await self._http().get(
            f"/v1/media/{quote(rn, safe='')}",
            params={"alt": "media"}, headers=await self._headers(),
        )
        if resp.status_code != 200:
            raise RuntimeError(f"media download lỗi {resp.status_code}: {resp.text[:200]}")
        return resp.content
