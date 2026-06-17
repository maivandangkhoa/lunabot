"""Smoke tests M0 — đảm bảo app import được, healthz sống, models/FSM khai báo đúng.

Chạy: pytest -q  (không cần DB thật; healthz không chạm DB).
"""
from fastapi.testclient import TestClient

from app.main import app
from app.models import RequestStatus, UserRole


def test_healthz():
    client = TestClient(app)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_webhook_stubs_respond():
    from app.config import get_settings

    client = TestClient(app)
    # Nếu secret được cấu hình (vd qua .env dev), phải kèm header đúng mới qua cổng verify.
    headers = {}
    if get_settings().telegram_webhook_secret:
        headers["X-Telegram-Bot-Api-Secret-Token"] = get_settings().telegram_webhook_secret
    # Telegram luôn 200 (kể cả lỗi nội bộ) để Telegram không retry bão.
    assert client.post("/webhook/telegram", json={}, headers=headers).status_code == 200
    assert client.post("/webhook/github", json={}).status_code == 204


def test_fsm_has_full_lifecycle():
    # Các state cốt lõi của vòng đời request phải tồn tại.
    expected = {
        "NEW", "ANALYZING", "CLARIFYING", "PLAN_REVIEW", "EXECUTING",
        "VERIFY", "MERGED_DEV", "AWAIT_MANAGER", "MERGED_MAIN", "CLOSED",
        "CANCELLED",
    }
    assert {s.name for s in RequestStatus} == expected


def test_roles():
    assert {r.value for r in UserRole} == {"employee", "manager", "admin"}
