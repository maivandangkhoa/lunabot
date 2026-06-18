"""Cookie phiên ký bằng HMAC (stdlib, không thêm dep itsdangerous).

Lưu danh tính GitHub (login/id/name) + token OAuth (để liệt kê repo trong wizard) + `state`
chống CSRF. Cookie httponly, ký HMAC-SHA256 → client không sửa được. Token OAuth GitHub App
ngắn hạn nên đặt trong cookie chấp nhận được cho MVP.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

COOKIE_NAME = "luna_session"
_MAX_AGE_S = 8 * 3600  # khớp TTL token user GitHub App (~8h)


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sign(payload: str, secret: str) -> str:
    return _b64e(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())


def dumps(data: dict, secret: str) -> str:
    data = {**data, "_ts": int(time.time())}
    payload = _b64e(json.dumps(data, separators=(",", ":")).encode())
    return f"{payload}.{_sign(payload, secret)}"


def loads(cookie: str | None, secret: str) -> dict | None:
    if not cookie or "." not in cookie:
        return None
    payload, sig = cookie.rsplit(".", 1)
    if not hmac.compare_digest(sig, _sign(payload, secret)):
        return None
    try:
        data = json.loads(_b64d(payload))
    except Exception:  # noqa: BLE001
        return None
    if int(time.time()) - int(data.get("_ts", 0)) > _MAX_AGE_S:
        return None
    return data
