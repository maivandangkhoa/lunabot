"""GitHub App — JWT → installation token (ngắn hạn) → REST tạo/merge PR.

Multi-tenant: mỗi repo của khách neo `gh_installation_id`. Ta KHÔNG dùng PAT dùng chung
(như ops-bot) mà sinh **installation access token** scoped + TTL ~1h cho từng installation.

An toàn:
- JWT ký bằng private key của App (RS256), TTL ngắn (9 phút).
- Token cache theo installation, **tự sinh lại** trước khi hết hạn (buffer 5 phút).
- KHÔNG bao giờ log token / Authorization header.

Git filesystem (clone/push) ở module riêng: app/git_ops.py.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx
import jwt

from app.config import get_settings

log = logging.getLogger("luna.github")

API_BASE = "https://api.github.com"
API_VERSION = "2022-11-28"
_TOKEN_REFRESH_BUFFER_S = 300  # sinh lại nếu còn < 5 phút


class GitHubAppError(RuntimeError):
    """Lỗi gọi GitHub API (kèm status + message đã loại token)."""


@dataclass
class _CachedToken:
    token: str
    expires_at: datetime


@dataclass
class GitHubApp:
    app_id: str
    private_key: str                       # nội dung PEM
    api_base: str = API_BASE
    client: httpx.AsyncClient | None = None
    _cache: dict[int, _CachedToken] = field(default_factory=dict, repr=False)

    @classmethod
    def from_settings(cls, client: httpx.AsyncClient | None = None) -> "GitHubApp":
        s = get_settings()
        if not s.github_app_id or not s.github_app_private_key_path:
            raise GitHubAppError("Thiếu GITHUB_APP_ID / GITHUB_APP_PRIVATE_KEY_PATH.")
        pem = s.github_app_private_key_path.read_text()
        return cls(app_id=s.github_app_id, private_key=pem, client=client)

    # ----- HTTP client -----
    def _http(self) -> httpx.AsyncClient:
        if self.client is None:
            self.client = httpx.AsyncClient(base_url=self.api_base, timeout=30)
        return self.client

    async def aclose(self) -> None:
        if self.client is not None:
            await self.client.aclose()
            self.client = None

    # ----- Auth -----
    def _app_jwt(self) -> str:
        """JWT của App (RS256). iat lùi 60s tránh lệch giờ, exp +9 phút (<10 phút max)."""
        now = int(time.time())
        payload = {"iat": now - 60, "exp": now + 540, "iss": self.app_id}
        return jwt.encode(payload, self.private_key, algorithm="RS256")

    @staticmethod
    def _parse_expiry(s: str) -> datetime:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))

    async def installation_token(self, installation_id: int) -> str:
        """Token scoped cho 1 installation. Cache + tự refresh trước khi hết hạn."""
        cached = self._cache.get(installation_id)
        now = datetime.now(timezone.utc)
        if cached and (cached.expires_at - now).total_seconds() > _TOKEN_REFRESH_BUFFER_S:
            return cached.token

        resp = await self._http().post(
            f"/app/installations/{installation_id}/access_tokens",
            headers={
                "Authorization": f"Bearer {self._app_jwt()}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": API_VERSION,
            },
        )
        if resp.status_code != 201:
            raise GitHubAppError(
                f"Tạo installation token thất bại (HTTP {resp.status_code}): "
                f"{_safe_msg(resp)}"
            )
        data = resp.json()
        token = data["token"]
        self._cache[installation_id] = _CachedToken(token, self._parse_expiry(data["expires_at"]))
        log.info("installation token mới cho id=%s (hết hạn %s)", installation_id, data["expires_at"])
        return token

    def authed_remote_url(self, token: str, repo_full_name: str) -> str:
        """Remote HTTPS có token để clone/push. KHÔNG log chuỗi này."""
        return f"https://x-access-token:{token}@github.com/{repo_full_name}.git"

    # ----- REST: Pull Requests -----
    async def _request(self, installation_id: int, method: str, path: str, **kw) -> dict:
        token = await self.installation_token(installation_id)
        resp = await self._http().request(
            method, path,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": API_VERSION,
            },
            **kw,
        )
        if resp.status_code >= 300:
            raise GitHubAppError(f"{method} {path} → HTTP {resp.status_code}: {_safe_msg(resp)}")
        return resp.json() if resp.content else {}

    async def create_pull_request(
        self, installation_id: int, repo_full_name: str,
        *, head: str, base: str, title: str, body: str = "",
    ) -> dict:
        """Tạo PR head→base. Trả dict GitHub (number, html_url, ...)."""
        return await self._request(
            installation_id, "POST", f"/repos/{repo_full_name}/pulls",
            json={"title": title, "head": head, "base": base, "body": body},
        )

    async def merge_pull_request(
        self, installation_id: int, repo_full_name: str, number: int,
        *, method: str = "merge",
    ) -> dict:
        """Merge PR. method: merge|squash|rebase. Trả dict GitHub (có `sha` merge commit)."""
        return await self._request(
            installation_id, "PUT", f"/repos/{repo_full_name}/pulls/{number}/merge",
            json={"merge_method": method},
        )

    async def close_pull_request(
        self, installation_id: int, repo_full_name: str, number: int,
    ) -> dict:
        """Đóng PR (không merge). No-op an toàn nếu PR đã đóng/đã merge."""
        return await self._request(
            installation_id, "PATCH", f"/repos/{repo_full_name}/pulls/{number}",
            json={"state": "closed"},
        )

    async def delete_branch(
        self, installation_id: int, repo_full_name: str, branch: str,
    ) -> dict:
        """Xoá nhánh trên remote (DELETE git ref)."""
        return await self._request(
            installation_id, "DELETE", f"/repos/{repo_full_name}/git/refs/heads/{branch}",
        )

    # ----- REST: Actions (CI/deploy) -----
    async def list_workflow_runs(
        self, installation_id: int, repo_full_name: str, *, head_sha: str,
    ) -> list[dict]:
        """Các workflow run gắn với commit `head_sha`. Mỗi run có status/conclusion/html_url/name."""
        data = await self._request(
            installation_id, "GET", f"/repos/{repo_full_name}/actions/runs",
            params={"head_sha": head_sha, "per_page": 50},
        )
        return data.get("workflow_runs", [])

    async def run_failure_summary(
        self, installation_id: int, repo_full_name: str, run_id: int,
    ) -> str:
        """Tóm tắt step lỗi của 1 run (job + step conclusion=failure) để feed Claude sửa.

        Dùng API jobs thay vì tải zip log (nặng). Best-effort: lỗi gọi API → chuỗi rỗng.
        """
        try:
            data = await self._request(
                installation_id, "GET",
                f"/repos/{repo_full_name}/actions/runs/{run_id}/jobs",
                params={"per_page": 50},
            )
        except GitHubAppError:
            return ""
        lines: list[str] = []
        for job in data.get("jobs", []):
            if job.get("conclusion") in (None, "success", "skipped"):
                continue
            bad_steps = [s["name"] for s in job.get("steps", [])
                         if s.get("conclusion") == "failure"]
            steps = f" (step lỗi: {', '.join(bad_steps)})" if bad_steps else ""
            lines.append(f"- job '{job.get('name')}' → {job.get('conclusion')}{steps}")
        return "\n".join(lines)


def _safe_msg(resp: httpx.Response) -> str:
    """Trích message lỗi từ body, cắt ngắn. Body GitHub không chứa token."""
    try:
        return str(resp.json().get("message", ""))[:300]
    except Exception:
        return resp.text[:300]
