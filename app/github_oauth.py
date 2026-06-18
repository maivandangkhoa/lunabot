"""GitHub OAuth (user-to-server của GitHub App) + liệt kê repo đã cấp quyền.

Dùng cho web wizard:
- Đăng nhập: redirect `authorize_url` → callback `exchange_code` → `get_user`.
- Cấp quyền repo: nút "Cài đặt" trỏ `install_url` (GitHub App install page) → người dùng chọn
  repo → GitHub redirect về /setup. Sau đó liệt kê repo bằng token user (`list_installations`
  + `list_installation_repos`).

KHÔNG log token. httpx async, test được bằng MockTransport (như TelegramAdapter).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

log = logging.getLogger("luna.github_oauth")

_GH = "https://github.com"
_API = "https://api.github.com"
_API_VERSION = "2022-11-28"


class GitHubOAuthError(RuntimeError):
    """Lỗi luồng OAuth (kèm message đã loại bí mật)."""


@dataclass
class GitHubOAuth:
    client_id: str
    client_secret: str
    app_slug: str
    api_base: str = _API
    web_base: str = _GH
    client: httpx.AsyncClient | None = None

    @classmethod
    def from_settings(cls, settings, client: httpx.AsyncClient | None = None) -> "GitHubOAuth":
        if not (settings.github_oauth_client_id and settings.github_oauth_client_secret
                and settings.github_app_slug):
            raise GitHubOAuthError(
                "Thiếu GITHUB_OAUTH_CLIENT_ID/SECRET hoặc GITHUB_APP_SLUG — web wizard chưa bật."
            )
        return cls(
            client_id=settings.github_oauth_client_id,
            client_secret=settings.github_oauth_client_secret,
            app_slug=settings.github_app_slug,
            client=client,
        )

    def _http(self) -> httpx.AsyncClient:
        if self.client is None:
            self.client = httpx.AsyncClient(timeout=30)
        return self.client

    async def aclose(self) -> None:
        if self.client is not None:
            await self.client.aclose()
            self.client = None

    # ----- Đăng nhập -----
    def authorize_url(self, redirect_uri: str, state: str) -> str:
        q = urlencode({
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "state": state,
        })
        return f"{self.web_base}/login/oauth/authorize?{q}"

    def install_url(self, state: str) -> str:
        """URL trang cài GitHub App (chọn repo để cấp quyền)."""
        q = urlencode({"state": state})
        return f"{self.web_base}/apps/{self.app_slug}/installations/new?{q}"

    async def exchange_code(self, code: str, redirect_uri: str) -> str:
        resp = await self._http().post(
            f"{self.web_base}/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
            },
        )
        data = resp.json()
        token = data.get("access_token")
        if not token:
            raise GitHubOAuthError(f"Đổi code lấy token thất bại: {data.get('error_description') or data.get('error')}")
        return token

    async def _get(self, token: str, path: str) -> dict:
        resp = await self._http().get(
            f"{self.api_base}{path}",
            headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": _API_VERSION,
            },
        )
        if resp.status_code >= 300:
            raise GitHubOAuthError(f"GET {path} → HTTP {resp.status_code}")
        return resp.json() if resp.content else {}

    async def get_user(self, token: str) -> dict:
        """{login, id, name} — danh tính cho session."""
        u = await self._get(token, "/user")
        return {"login": u.get("login"), "id": u.get("id"), "name": u.get("name") or u.get("login")}

    async def list_installations(self, token: str) -> list[dict]:
        data = await self._get(token, "/user/installations")
        return data.get("installations", [])

    async def list_installation_repos(self, token: str, installation_id: int) -> list[dict]:
        data = await self._get(token, f"/user/installations/{installation_id}/repositories")
        return data.get("repositories", [])

    async def accessible_repos(self, token: str) -> list[dict]:
        """Gộp mọi repo người dùng đã cấp qua các installation → [{full_name, installation_id}]."""
        out: list[dict] = []
        for inst in await self.list_installations(token):
            iid = inst.get("id")
            for r in await self.list_installation_repos(token, iid):
                out.append({"full_name": r.get("full_name"), "installation_id": iid,
                            "default_branch": r.get("default_branch", "main")})
        return out
