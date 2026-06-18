"""Mã hoá token bot BYO trước khi lưu DB (Fernet, đối xứng).

Token bot Telegram của khách là bí mật như mật khẩu — KHÔNG lưu plaintext, KHÔNG log.
Dùng `cryptography.fernet` (đã đi kèm PyJWT[crypto], không thêm dep). Khoá lấy từ
settings.bot_token_enc_key (sinh: `Fernet.generate_key()`).
"""
from __future__ import annotations

from cryptography.fernet import Fernet


class TokenCryptoError(RuntimeError):
    """Thiếu/khoá mã hoá sai — chặn provisioning bot riêng thay vì lưu token hớ."""


def _fernet(key: str | None) -> Fernet:
    if not key:
        raise TokenCryptoError(
            "Thiếu BOT_TOKEN_ENC_KEY — cần để mã hoá token bot riêng. "
            "Sinh: python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\""
        )
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception as exc:  # noqa: BLE001
        raise TokenCryptoError(f"BOT_TOKEN_ENC_KEY không hợp lệ: {exc!r}") from exc


def encrypt_token(plaintext: str, key: str | None) -> str:
    return _fernet(key).encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str, key: str | None) -> str:
    return _fernet(key).decrypt(ciphertext.encode()).decode()
