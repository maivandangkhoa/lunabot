"""Tests github_app — JWT hợp lệ, installation token (cache + refresh), create/merge PR,
xử lý lỗi. Dùng httpx.MockTransport (không mạng) + RSA key sinh tại chỗ.
"""
from datetime import datetime, timedelta, timezone

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.github_app import GitHubApp, GitHubAppError

APP_ID = "123456"
INSTALL_ID = 42
REPO = "acme/widgets"


def _rsa_pem() -> tuple[str, bytes]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    pub = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return priv, pub


def _future_iso(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat().replace(
        "+00:00", "Z"
    )


def _app(handler, priv: str) -> GitHubApp:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.github.com"
    )
    return GitHubApp(app_id=APP_ID, private_key=priv, client=client)


def test_app_jwt_signed_correctly():
    priv, pub = _rsa_pem()
    app = GitHubApp(app_id=APP_ID, private_key=priv)
    decoded = jwt.decode(app._app_jwt(), pub, algorithms=["RS256"])
    assert decoded["iss"] == APP_ID
    assert decoded["exp"] > decoded["iat"]


@pytest.mark.asyncio
async def test_installation_token_caches(monkeypatch):
    priv, _ = _rsa_pem()
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == f"/app/installations/{INSTALL_ID}/access_tokens"
        assert req.headers["Authorization"].startswith("Bearer ")
        calls["n"] += 1
        return httpx.Response(201, json={"token": "ghs_secret", "expires_at": _future_iso(3600)})

    app = _app(handler, priv)
    t1 = await app.installation_token(INSTALL_ID)
    t2 = await app.installation_token(INSTALL_ID)
    assert t1 == t2 == "ghs_secret"
    assert calls["n"] == 1  # lần 2 lấy từ cache


@pytest.mark.asyncio
async def test_installation_token_refreshes_when_near_expiry():
    priv, _ = _rsa_pem()
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(201, json={"token": "ghs_x", "expires_at": _future_iso(60)})

    app = _app(handler, priv)
    await app.installation_token(INSTALL_ID)
    await app.installation_token(INSTALL_ID)
    assert calls["n"] == 2  # còn <5 phút → sinh lại


@pytest.mark.asyncio
async def test_create_and_merge_pr():
    priv, _ = _rsa_pem()

    def handler(req: httpx.Request) -> httpx.Response:
        p = req.url.path
        if p.endswith("/access_tokens"):
            return httpx.Response(201, json={"token": "ghs_x", "expires_at": _future_iso(3600)})
        if p == f"/repos/{REPO}/pulls" and req.method == "POST":
            return httpx.Response(201, json={"number": 7, "html_url": f"https://github.com/{REPO}/pull/7"})
        if p == f"/repos/{REPO}/pulls/7/merge" and req.method == "PUT":
            return httpx.Response(200, json={"merged": True, "sha": "abc"})
        return httpx.Response(404, json={"message": "not found"})

    app = _app(handler, priv)
    pr = await app.create_pull_request(
        INSTALL_ID, REPO, head="bot/req-1", base="dev", title="Fix", body="b"
    )
    assert pr["number"] == 7
    merged = await app.merge_pull_request(INSTALL_ID, REPO, 7, method="squash")
    assert merged["merged"] is True


@pytest.mark.asyncio
async def test_error_raises_without_leaking_token():
    priv, _ = _rsa_pem()

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/access_tokens"):
            return httpx.Response(201, json={"token": "ghs_secret", "expires_at": _future_iso(3600)})
        return httpx.Response(422, json={"message": "Validation failed"})

    app = _app(handler, priv)
    with pytest.raises(GitHubAppError) as exc:
        await app.create_pull_request(INSTALL_ID, REPO, head="h", base="dev", title="t")
    msg = str(exc.value)
    assert "422" in msg and "Validation failed" in msg
    assert "ghs_secret" not in msg
