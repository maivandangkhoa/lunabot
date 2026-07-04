"""Tests đo lượng dùng Claude (app/usage.py + wiring orchestrator/dispatcher).

Khẳng định: record() trích đúng token/cost/modelUsage từ raw JSON, phát hiện limit-hit,
nuốt lỗi (không raise), và orchestrator ghi 1 dòng cho mỗi lần chạy Claude (analyze/execute)
gắn đúng tenant/request/phase.
"""
import pytest

from app import usage
from app.claude_runner import ClaudeResult
from app.models import RequestStatus, UsageRecord, UserRole
from app.onboarding import add_repository, create_tenant, create_user
from app.orchestrator import Orchestrator, cb
from tests.conftest import FakeClaude, claude_json

RAW = {
    "session_id": "s1",
    "total_cost_usd": 0.4321,
    "duration_ms": 12345,
    "num_turns": 7,
    "usage": {
        "input_tokens": 100,
        "output_tokens": 2000,
        "cache_read_input_tokens": 50000,
        "cache_creation_input_tokens": 3000,
    },
    "modelUsage": {"claude-sonnet-5": {"inputTokens": 100, "outputTokens": 2000}},
}


def _res(ok=True, result="xong", raw=None, num_turns=7):
    return ClaudeResult(ok=ok, result=result, session_id="s1", is_error=not ok,
                        num_turns=num_turns, total_cost_usd=(raw or {}).get("total_cost_usd"),
                        raw=raw if raw is not None else RAW)


# ── record(): trích xuất ──────────────────────────────────────────────────────
def test_record_extracts_tokens_cost_and_models(db):
    rec = usage.record(db, tenant_id=1, phase="analyze", res=_res(), request_id=None)
    assert rec is not None
    assert rec.input_tokens == 100 and rec.output_tokens == 2000
    assert rec.cache_read_tokens == 50000 and rec.cache_creation_tokens == 3000
    assert float(rec.cost_usd) == pytest.approx(0.4321)
    assert rec.duration_ms == 12345 and rec.num_turns == 7
    assert rec.model_usage == RAW["modelUsage"]
    assert rec.status == "ok"
    assert rec.auth_mode in ("subscription", "api")


def test_record_error_run_still_recorded(db):
    """Lần chạy lỗi (timeout/crash, raw rỗng) vẫn ghi — để thấy tần suất lỗi/limit."""
    rec = usage.record(db, tenant_id=1, phase="execute",
                       res=_res(ok=False, result="❌ Claude lỗi (code 1)", raw={}))
    assert rec.status == "error"
    assert rec.input_tokens == 0 and rec.cost_usd is None


@pytest.mark.parametrize("msg", [
    "Claude AI usage limit reached|1751600000",
    "5-hour limit reached ∙ resets 3pm",
    "API Error: rate limit exceeded",
])
def test_record_detects_limit_hit(db, msg):
    rec = usage.record(db, tenant_id=1, phase="execute", res=_res(ok=False, result=msg, raw={}))
    assert rec.status == "limit"


def test_record_never_raises(db, monkeypatch):
    """Đo lường không được làm hỏng FSM: lỗi DB → trả None, không raise."""
    monkeypatch.setattr(db, "commit", lambda: (_ for _ in ()).throw(RuntimeError("db down")))
    assert usage.record(db, tenant_id=1, phase="x", res=_res()) is None


# ── wiring orchestrator ───────────────────────────────────────────────────────
PLAN = '{"action":"plan","summary":"do x","steps":["a"],"risk":"low"}'
IMPL = '{"action":"implemented","summary":"done","branch":"bot/req-1"}'


def _seed(db):
    t = create_tenant(db, "Acme")
    repo = add_repository(db, t, "acme/widgets", 12345)
    repo.settings_json = {"deploy_gate": False}
    emp = create_user(db, t, role=UserRole.EMPLOYEE, display_name="Bob")
    emp.platform_user_id = "emp-1"
    db.commit()
    return t, repo, emp


def _with_raw(result: ClaudeResult) -> ClaudeResult:
    result.raw = {**RAW, "session_id": result.session_id}
    return result


@pytest.mark.asyncio
async def test_orchestrator_records_analyze_and_execute(db, fakes, tmp_path):
    t, repo, emp = _seed(db)
    claude = FakeClaude([_with_raw(claude_json(PLAN, "s1")),
                         _with_raw(claude_json(IMPL, "s2"))])
    orch = Orchestrator(db, fakes["adapter"], github=fakes["github"],
                        claude_run=claude, git=fakes["git"])
    orch.workspace = tmp_path

    req = await orch.create_request(repo, emp, "Sửa nút lưu", None)
    await orch.handle_callback(req, emp, cb("confirm", req.id))
    assert req.status == RequestStatus.VERIFY

    recs = db.query(UsageRecord).order_by(UsageRecord.id).all()
    assert [r.phase for r in recs] == ["analyze", "execute"]
    assert all(r.tenant_id == t.id and r.request_id == req.id for r in recs)
    assert all(float(r.cost_usd) == pytest.approx(0.4321) for r in recs)


@pytest.mark.asyncio
async def test_orchestrator_records_failed_run(db, fakes, tmp_path):
    """Lần analyze lỗi vẫn có dòng usage (status=error) — không mất dấu chi phí."""
    t, repo, emp = _seed(db)
    claude = FakeClaude([ClaudeResult(ok=False, result="boom", session_id="s1",
                                      is_error=True, raw={})])
    orch = Orchestrator(db, fakes["adapter"], github=fakes["github"],
                        claude_run=claude, git=fakes["git"])
    orch.workspace = tmp_path

    await orch.create_request(repo, emp, "Sửa nút lưu", None)
    recs = db.query(UsageRecord).all()
    assert len(recs) == 1 and recs[0].status == "error" and recs[0].phase == "analyze"


# ── wiring dispatcher (intent) ────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_recording_run_wraps_and_records(db, monkeypatch):
    from app import dispatcher

    async def _fake_run(**kw):
        return _res()

    monkeypatch.setattr(dispatcher, "run_claude", _fake_run)
    run = dispatcher._recording_run(db, tenant_id=99)
    res = await run(prompt="ok làm đi")
    assert res.ok
    recs = db.query(UsageRecord).all()
    assert len(recs) == 1
    assert recs[0].tenant_id == 99 and recs[0].phase == "intent" and recs[0].request_id is None
