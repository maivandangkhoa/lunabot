"""Fixtures + fakes dùng chung: DB SQLite in-memory, adapter/claude/github/git giả lập."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401 — đăng ký metadata
from app.channels.google_chat import GoogleChatAdapter
from app.channels.telegram import TelegramAdapter
from app.claude_runner import ClaudeResult
from app.db import Base


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


class RecordingTelegram(TelegramAdapter):
    """Kế thừa parse_inbound/callback_id thật, ghi lại outbound thay vì gọi HTTP."""

    def __init__(self):
        super().__init__(token="test-token")
        self.sent: list[tuple] = []
        self.answered: list[str] = []

    async def send(self, platform_user_id, text, buttons=None):
        self.sent.append((platform_user_id, text, buttons))
        return {"ok": True}

    async def answer_callback(self, callback_id, text=None):
        self.answered.append(callback_id)
        return {"ok": True}


class RecordingGoogleChat(GoogleChatAdapter):
    """Kế thừa parse_inbound thật, ghi outbound thay vì gọi Chat REST."""

    def __init__(self):
        super().__init__(sa_credentials={}, token_provider=lambda: "tok")
        self.sent: list[tuple] = []

    async def send(self, platform_user_id, text, buttons=None):
        self.sent.append((platform_user_id, text, buttons))
        return {"name": "spaces/X/messages/1"}


class FakeClaude:
    """Trả lần lượt các ClaudeResult đã nạp sẵn."""

    def __init__(self, results: list[ClaudeResult]):
        self.results = list(results)
        self.calls: list[dict] = []

    async def __call__(self, **kw) -> ClaudeResult:
        self.calls.append(kw)
        return self.results.pop(0)


class FakeGitHub:
    def __init__(self):
        self.created_prs: list[dict] = []
        self.merged: list[int] = []

    async def installation_token(self, installation_id):
        return "ghs_fake"

    def authed_remote_url(self, token, repo_full_name):
        return f"https://x-access-token:{token}@github.com/{repo_full_name}.git"

    async def create_pull_request(self, installation_id, repo_full_name, *, head, base, title, body=""):
        n = len(self.created_prs) + 7
        self.created_prs.append({"head": head, "base": base, "title": title})
        return {"number": n, "html_url": f"https://github.com/{repo_full_name}/pull/{n}"}

    async def merge_pull_request(self, installation_id, repo_full_name, number, *, method="merge"):
        self.merged.append(number)
        return {"merged": True}

    async def aclose(self):
        pass


class FakeGit:
    """No-op git: orchestrator chỉ cần các hàm này không raise."""

    def __init__(self):
        self.has_changes = True

    async def ensure_clone(self, *a, **k):
        return None

    async def prepare_branch(self, *a, **k):
        return None

    async def commit_all(self, *a, **k):
        return self.has_changes

    async def push_branch(self, *a, **k):
        return None


def claude_json(action_block: str, session_id="s1", ok=True) -> ClaudeResult:
    return ClaudeResult(ok=ok, result=f"Mình đã xong.\n```json\n{action_block}\n```",
                        session_id=session_id)


@pytest.fixture
def fakes():
    return {
        "adapter": RecordingTelegram(),
        "github": FakeGitHub(),
        "git": FakeGit(),
    }
