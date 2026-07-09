"""Tests dev-mode (app/dev_runner.py) — pipe thẳng vào Claude, recap, cổng deploy-main.

Không chạy subprocess `claude` thật: monkeypatch `_run_stream` + `_ensure_repo`.
Bất biến chính: dev-mode KHÔNG đụng FSM (không tạo Request).
"""
import json

import pytest

from app import dev_runner
from app.dev_runner import _parse_stream, _pick_repo, tenant_dev_mode
from app.models import DevSession, Request, Tenant
from app.onboarding import add_repository, create_tenant, create_user
from tests.conftest import RecordingTelegram


def _dev_tenant(db, *, dev_mode=True, repo="acme/widgets"):
    t = create_tenant(db, "Acme")
    t.settings_json = {"dev_mode": dev_mode}
    r = add_repository(db, t, repo, 123)
    u = create_user(db, t)
    u.platform_user_id = "99"
    u.active_repo_id = r.id
    db.commit()
    return t, r, u


def _inbound(text):
    return RecordingTelegram().parse_inbound(
        {"message": {"text": text, "from": {"id": 99}, "chat": {"id": 99}}})


# --------------------------------------------------------------------------- #
# Unit
# --------------------------------------------------------------------------- #
def test_tenant_dev_mode_flag(db):
    on = Tenant(name="A", settings_json={"dev_mode": True})
    off = Tenant(name="B", settings_json={"claude_model": "x"})
    assert tenant_dev_mode(on) is True
    assert tenant_dev_mode(off) is False
    assert tenant_dev_mode(None) is False


def test_parse_stream_collects_actions_and_result():
    lines = [
        {"type": "system", "subtype": "init"},
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Read", "input": {"file_path": "app/x.py"}},
            {"type": "text", "text": "ok"},
        ]}},
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": "pytest -q\n"}},
        ]}},
        {"type": "result", "result": "Đã thêm rate-limit.", "session_id": "sid9",
         "is_error": False, "num_turns": 3, "total_cost_usd": 0.01},
    ]
    out = _parse_stream("\n".join(json.dumps(x) for x in lines), None)
    assert out["session_id"] == "sid9"
    assert out["text"] == "Đã thêm rate-limit."
    assert out["is_error"] is False
    assert out["actions"] == ["Read app/x.py", "$ pytest -q"]


def test_parse_stream_no_result_is_error():
    out = _parse_stream('{"type":"system"}\nnot-json\n', "keep")
    assert out["is_error"] is True
    assert out["session_id"] == "keep"      # giữ session cũ khi không có result


def test_pick_repo_prefers_active(db):
    _, r, u = _dev_tenant(db)
    assert _pick_repo(db, u).id == r.id
    u.active_repo_id = None
    db.commit()
    assert _pick_repo(db, u).id == r.id      # tenant 1 repo → fallback


# --------------------------------------------------------------------------- #
# dev_chat — patch _run_stream + _ensure_repo
# --------------------------------------------------------------------------- #
def _patch_run(monkeypatch, *, text="Xong.", actions=None, session_id="sid1",
               is_error=False):
    from app.claude_runner import ClaudeResult

    async def fake_run(**kw):
        fake_run.calls.append(kw)
        return {"actions": actions or [], "text": text, "session_id": session_id,
                "final": {"num_turns": 1}, "is_error": is_error,
                "res": ClaudeResult(ok=not is_error, result=text, session_id=session_id)}
    fake_run.calls = []
    monkeypatch.setattr(dev_runner, "_run_stream", fake_run)

    async def fake_repo(github, repo):
        from pathlib import Path
        return Path("/tmp/x")
    monkeypatch.setattr(dev_runner, "_ensure_repo", fake_repo)
    return fake_run


@pytest.mark.asyncio
async def test_dev_chat_pipes_saves_session_and_recaps(db, fakes, monkeypatch):
    _, r, u = _dev_tenant(db)
    run = _patch_run(monkeypatch, text="Đã sửa auth.", actions=["Edit app/auth.py"])
    adapter = fakes["adapter"]

    await dev_runner.dev_chat(db, adapter, fakes["github"], u, _inbound("sửa auth"), "99")

    assert run.calls and run.calls[0]["session_id"] is None       # phiên đầu
    sess = db.query(DevSession).filter_by(user_id=u.id, repo_id=r.id).one()
    assert sess.claude_session_id == "sid1"                        # đã lưu để --resume
    body = adapter.sent[-1][1]
    assert "Edit app/auth.py" in body and "Đã sửa auth." in body   # recap + trả lời
    # BẤT BIẾN: không tạo Request (không đụng FSM).
    assert db.query(Request).count() == 0


@pytest.mark.asyncio
async def test_dev_chat_resumes_existing_session(db, fakes, monkeypatch):
    _, r, u = _dev_tenant(db)
    db.add(DevSession(user_id=u.id, repo_id=r.id,
                      claude_session_id="old", pending_json={}))
    db.commit()
    run = _patch_run(monkeypatch, session_id="new")
    await dev_runner.dev_chat(db, fakes["adapter"], fakes["github"], u, _inbound("tiếp"), "99")
    assert run.calls[0]["session_id"] == "old"                     # --resume phiên cũ
    sess = db.query(DevSession).filter_by(user_id=u.id).one()
    assert sess.claude_session_id == "new"


@pytest.mark.asyncio
async def test_dev_chat_clear_resets_session(db, fakes, monkeypatch):
    _, r, u = _dev_tenant(db)
    db.add(DevSession(user_id=u.id, repo_id=r.id, claude_session_id="x",
                      pending_json={"await_main": True}))
    db.commit()
    run = _patch_run(monkeypatch)
    await dev_runner.dev_chat(db, fakes["adapter"], fakes["github"], u, _inbound("/clear"), "99")
    assert run.calls == []                                         # không gọi Claude
    sess = db.query(DevSession).filter_by(user_id=u.id).one()
    assert sess.claude_session_id is None and sess.pending_json == {}


@pytest.mark.asyncio
async def test_dev_chat_no_deploy_gate_works_on_prod_branch(db, fakes, monkeypatch):
    """Dev-mode làm thẳng trên nhánh chính (prod_branch), không còn cổng confirm deploy:
    không tự merge/PR, và system prompt hướng làm việc trên nhánh chính."""
    _, r, u = _dev_tenant(db)
    gh = fakes["github"]
    run = _patch_run(monkeypatch, text="Đã đẩy lên main.")
    await dev_runner.dev_chat(db, fakes["adapter"], gh, u, _inbound("sửa và push"), "99")
    assert gh.merged == []                                   # không tự deploy/merge
    assert r.prod_branch in run.calls[0]["system_prompt"]    # prompt làm trên nhánh chính


@pytest.mark.asyncio
async def test_ensure_repo_clones_prod_branch_no_protection(db, fakes, monkeypatch):
    """_ensure_repo clone nhánh chính (prod_branch) và KHÔNG chặn nhánh nào (protected rỗng)
    → Claude được tự do push nhánh chính như Claude Code client."""
    _, r, _u = _dev_tenant(db)
    captured = {}

    async def fake_clone(repo_dir, url, base_branch, protected):
        captured.update(base=base_branch, protected=protected)
        return repo_dir
    monkeypatch.setattr(dev_runner.git_ops, "ensure_clone", fake_clone)

    await dev_runner._ensure_repo(fakes["github"], r)
    assert captured["base"] == r.prod_branch
    assert captured["protected"] == []


# --------------------------------------------------------------------------- #
# Qua dispatcher — routing + chế độ thường bất biến
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_dispatcher_routes_devmode_no_fsm(db, fakes, monkeypatch):
    from app.dispatcher import handle_telegram_update
    _, r, u = _dev_tenant(db)
    _patch_run(monkeypatch, text="Đã đọc code.", actions=["Read app/x.py"])
    await handle_telegram_update(db, fakes["adapter"], fakes["github"],
                                 {"message": {"text": "xem file x", "from": {"id": 99},
                                              "chat": {"id": 99}}})
    assert db.query(Request).count() == 0                          # KHÔNG qua FSM
    assert any("Đã đọc code." in s[1] for s in fakes["adapter"].sent)


@pytest.mark.asyncio
async def test_dispatcher_normal_tenant_untouched(db, fakes, monkeypatch):
    """Tenant KHÔNG bật dev_mode: đi đường FSM như cũ (tạo Request)."""
    from app.dispatcher import handle_telegram_update
    from tests.conftest import claude_json

    _, r, u = _dev_tenant(db, dev_mode=False)
    fake = __import__("tests.conftest", fromlist=["FakeClaude"]).FakeClaude(
        [claude_json('{"action":"clarify","questions":["a?"]}', "s1")])
    monkeypatch.setattr("app.orchestrator.run_claude", fake)

    async def _noop(*a, **k):
        return None
    for fn in ("ensure_clone", "prepare_branch"):
        monkeypatch.setattr(f"app.git_ops.{fn}", _noop)

    await handle_telegram_update(db, fakes["adapter"], fakes["github"],
                                 {"message": {"text": "fix bug", "from": {"id": 99},
                                              "chat": {"id": 99}}})
    assert db.query(Request).count() == 1                          # FSM vẫn chạy
