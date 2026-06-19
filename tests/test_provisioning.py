"""Provisioning self-service: tạo bot chung & bot riêng, mã hoá token, enforce link đúng bot."""
from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from app.config import Settings
from app.models import Bot, Repository, User, UserRole
from app.onboarding import get_user_by_platform, link_user
from app.provisioning import ProvisioningError, provision
from app.token_crypto import decrypt_token, encrypt_token


def _settings(**over):
    base = dict(
        _env_file=None,
        bot_token_enc_key=Fernet.generate_key().decode(),
        public_base_url="https://luna.example.com",
        telegram_bot_username="LunaShared",
    )
    base.update(over)
    return Settings(**base)


class FakeBotAdapter:
    """Adapter giả cho bot riêng: getMe trả username, ghi lại setWebhook."""

    def __init__(self, token, username="newshopbot"):
        self.token = token
        self._username = username
        self.webhooks: list[tuple] = []

    async def get_me(self):
        return {"username": self._username, "id": 555}

    async def set_webhook(self, url, secret_token=None):
        self.webhooks.append((url, secret_token))
        return {"ok": True}

    async def aclose(self):
        pass


def test_token_crypto_roundtrip():
    key = Fernet.generate_key().decode()
    ct = encrypt_token("123:ABC", key)
    assert ct != "123:ABC"
    assert decrypt_token(ct, key) == "123:ABC"


@pytest.mark.asyncio
async def test_provision_shared_bot(db):
    s = _settings()
    res = await provision(
        db, s, owner_github_id=42, owner_github_login="alice", owner_name="Alice",
        repo_full_name="alice/shop", installation_id=999,
        bot_choice="shared", hosting_choice="shared_instance",
    )
    bot = db.get(Bot, res.bot_id)
    assert bot.mode == "shared" and bot.token_encrypted is None
    assert res.bot_username == "LunaShared"
    assert res.deeplink == f"https://t.me/LunaShared?start={res.link_token}"
    user = db.get(User, res.user_id)
    assert user.role == UserRole.ADMIN and user.bot_id is None   # bot chung ⇒ NULL
    assert db.get(Repository, res.repo_id).repo_full_name == "alice/shop"


@pytest.mark.asyncio
async def test_provision_own_bot_encrypts_and_sets_webhook(db):
    s = _settings()
    captured = {}

    def factory(token):
        a = FakeBotAdapter(token)
        captured["adapter"] = a
        return a

    res = await provision(
        db, s, owner_github_id=7, owner_github_login="bob", owner_name="Bob",
        repo_full_name="bob/api", installation_id=111,
        bot_choice="own", hosting_choice="shared_instance",
        bot_token="123456:REAL-TOKEN", adapter_factory=factory,
    )
    bot = db.get(Bot, res.bot_id)
    assert bot.mode == "own" and bot.username == "newshopbot"
    assert bot.token_encrypted and decrypt_token(bot.token_encrypted, s.bot_token_enc_key) == "123456:REAL-TOKEN"
    assert bot.webhook_secret
    url, secret = captured["adapter"].webhooks[0]
    assert url == f"https://luna.example.com/webhook/telegram/{bot.id}" and secret == bot.webhook_secret
    assert db.get(User, res.user_id).bot_id == bot.id   # own ⇒ user gắn bot


@pytest.mark.asyncio
async def test_provision_own_bot_rejects_duplicate(db):
    """Token/username đã đăng ký (1 Telegram bot = 1 webhook) → chặn, KHÔNG tạo tenant thừa."""
    s = _settings()
    kw = dict(owner_github_id=7, owner_github_login="bob", owner_name="Bob",
              repo_full_name="bob/api", installation_id=111, bot_choice="own",
              hosting_choice="shared_instance", bot_token="t",
              adapter_factory=lambda t: FakeBotAdapter(t))
    await provision(db, s, **kw)
    from app.models import Tenant
    n_before = len(db.query(Tenant).all())
    with pytest.raises(ProvisioningError):
        await provision(db, s, **kw)            # cùng username "newshopbot" → chặn
    assert len(db.query(Tenant).all()) == n_before   # không sinh tenant mồ côi


@pytest.mark.asyncio
async def test_provision_own_bot_requires_token(db):
    with pytest.raises(ProvisioningError):
        await provision(
            db, _settings(), owner_github_id=1, owner_github_login="x", owner_name="X",
            repo_full_name="x/y", installation_id=1,
            bot_choice="own", hosting_choice="shared_instance", bot_token=None,
        )


@pytest.mark.asyncio
async def test_link_token_only_works_on_correct_bot(db):
    s = _settings()
    res = await provision(
        db, s, owner_github_id=7, owner_github_login="bob", owner_name="Bob",
        repo_full_name="bob/api", installation_id=111, bot_choice="own",
        hosting_choice="shared_instance", bot_token="t", adapter_factory=lambda t: FakeBotAdapter(t),
    )
    # Dùng token trên bot SAI (bot chung, bot_id=None) → từ chối.
    assert link_user(db, res.link_token, "500", platform="telegram", bot_id=None) is None
    # Đúng bot → link OK.
    u = link_user(db, res.link_token, "500", platform="telegram", bot_id=res.bot_id)
    assert u is not None and u.id == res.user_id
    assert get_user_by_platform(db, "telegram", "500", bot_id=res.bot_id).id == res.user_id
