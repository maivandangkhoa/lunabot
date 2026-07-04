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


def _fernet(enc_key: str | None):
    """Fernet để mã hoá NỘI DUNG cookie (gồm token OAuth GitHub) khi có key. None = chỉ ký,
    không mã hoá (tương thích cũ). Mã hoá thêm lớp phòng khi khoá ký lộ vẫn không đọc được token."""
    if not enc_key:
        return None
    from cryptography.fernet import Fernet
    return Fernet(enc_key if isinstance(enc_key, bytes) else enc_key.encode())


def dumps(data: dict, secret: str, enc_key: str | None = None) -> str:
    data = {**data, "_ts": int(time.time())}
    body = json.dumps(data, separators=(",", ":")).encode()
    f = _fernet(enc_key)
    if f is not None:
        body = f.encrypt(body)
    payload = _b64e(body)
    return f"{payload}.{_sign(payload, secret)}"


def loads(cookie: str | None, secret: str, enc_key: str | None = None) -> dict | None:
    if not cookie or "." not in cookie:
        return None
    payload, sig = cookie.rsplit(".", 1)
    if not hmac.compare_digest(sig, _sign(payload, secret)):
        return None
    try:
        raw = _b64d(payload)
        f = _fernet(enc_key)
        if f is not None:
            raw = f.decrypt(raw)          # cookie cũ (chưa mã hoá) sẽ fail → None → đăng nhập lại
        data = json.loads(raw)
    except Exception:  # noqa: BLE001
        return None
    if int(time.time()) - int(data.get("_ts", 0)) > _MAX_AGE_S:
        return None
    return data
