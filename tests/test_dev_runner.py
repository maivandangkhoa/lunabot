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
async def test_dev_chat_deploy_flow_confirm(db, fakes, monkeypatch):
    _, r, u = _dev_tenant(db)
    gh = fakes["github"]
    # Lượt 1: Claude phát sentinel → bot xin xác nhận, set pending.
    _patch_run(monkeypatch, text=f"Sẵn sàng. {dev_runner._DEPLOY_SENTINEL}")
    adapter = fakes["adapter"]
    await dev_runner.dev_chat(db, adapter, gh, u, _inbound("deploy lên main"), "99")
    sess = db.query(DevSession).filter_by(user_id=u.id).one()
    assert sess.pending_json.get("await_main") is True
    assert dev_runner._DEPLOY_SENTINEL not in adapter.sent[-2][1]   # sentinel bị strip
    assert any("main" in s[1] for s in adapter.sent)               # có lời mời xác nhận

    # Lượt 2: "ok" → merge PR base→prod.
    await dev_runner.dev_chat(db, adapter, gh, u, _inbound("ok"), "99")
    assert gh.merged, "phải merge PR khi xác nhận deploy"
    assert gh.created_prs[0]["head"] == r.base_branch and gh.created_prs[0]["base"] == r.prod_branch
    db.refresh(sess)
    assert sess.pending_json == {}


@pytest.mark.asyncio
async def test_dev_chat_deploy_cancel(db, fakes, monkeypatch):
    _, r, u = _dev_tenant(db)
    db.add(DevSession(user_id=u.id, repo_id=r.id, pending_json={"await_main": True}))
    db.commit()
    _patch_run(monkeypatch)
    await dev_runner.dev_chat(db, fakes["adapter"], fakes["github"], u, _inbound("huỷ"), "99")
    assert fakes["github"].merged == []
    sess = db.query(DevSession).filter_by(user_id=u.id).one()
    assert sess.pending_json == {}


@pytest.mark.asyncio
async def test_deploy_main_idempotent_on_422(db, fakes):
    _, r, _u = _dev_tenant(db)
    gh = fakes["github"]
    # PR đã tồn tại từ lần trước → create 422, find lại rồi merge.
    await gh.create_pull_request(r.gh_installation_id, r.repo_full_name,
                                 head=r.base_branch, base=r.prod_branch, title="old")
    gh.fail_create_422 = 1
    await dev_runner._deploy_main(gh, r)
    assert gh.merged == [7]


@pytest.mark.asyncio
async def test_deploy_main_retries_405_race(db, fakes, monkeypatch):
    _, r, _u = _dev_tenant(db)
    gh = fakes["github"]
    gh.fail_merge_405 = 1

    async def _fast(*_a, **_k):
        return None
    monkeypatch.setattr(dev_runner.asyncio, "sleep", _fast)   # không chờ retry thật
    await dev_runner._deploy_main(gh, r)
    assert gh.merged == [7]


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
