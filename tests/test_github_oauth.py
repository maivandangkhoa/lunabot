"""GitHub OAuth client — mock httpx (MockTransport) như adapter Telegram, không gọi mạng thật."""
from __future__ import annotations

import httpx
import pytest

from app.github_oauth import GitHubOAuth


def _handler(request: httpx.Request) -> httpx.Response:
    p = request.url.path
    if p == "/login/oauth/access_token":
        return httpx.Response(200, json={"access_token": "gho_test"})
    if p == "/user":
        return httpx.Response(200, json={"login": "alice", "id": 42, "name": "Alice"})
    if p == "/user/installations":
        return httpx.Response(200, json={"installations": [{"id": 9}]})
    if p == "/user/installations/9/repositories":
        return httpx.Response(200, json={"repositories": [
            {"full_name": "alice/shop", "default_branch": "main"}]})
    return httpx.Response(404)


def _client():
    return httpx.AsyncClient(transport=httpx.MockTransport(_handler))


def test_authorize_and_install_url():
    o = GitHubOAuth(client_id="cid", client_secret="sec", app_slug="luna-bot")
    assert "client_id=cid" in o.authorize_url("https://x/cb", "st8")
    assert "state=st8" in o.authorize_url("https://x/cb", "st8")
    assert o.install_url("st8") == "https://github.com/apps/luna-bot/installations/new?state=st8"


@pytest.mark.asyncio
async def test_exchange_get_user_and_repos():
    o = GitHubOAuth(client_id="cid", client_secret="sec", app_slug="luna-bot", client=_client())
    token = await o.exchange_code("code123", "https://x/cb")
    assert token == "gho_test"
    user = await o.get_user(token)
    assert user == {"login": "alice", "id": 42, "name": "Alice"}
    repos = await o.accessible_repos(token)
    assert repos == [{"full_name": "alice/shop", "installation_id": 9, "default_branch": "main"}]
    await o.aclose()
