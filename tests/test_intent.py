"""Tests Lớp 2 — classify_intent: câu tự nhiên → Intent(word canonical, confidence) hoặc None."""
import pytest

from app.claude_runner import ClaudeResult
from app.intent import Intent, _extract, classify_intent


def _run_returning(block: str | None, ok: bool = True):
    """Fake run_claude: trả output chứa khối json `block` (None = không có json)."""
    async def _run(**kw):
        body = f"Mình hiểu rồi.\n```json\n{block}\n```" if block is not None else "..."
        return ClaudeResult(ok=ok, result=body, session_id=None)
    return _run


@pytest.mark.asyncio
@pytest.mark.parametrize("intent,word", [
    ('{"intent":"approve","confidence":0.9}', "ok"),
    ('{"intent":"edit","confidence":0.8}', "sửa"),
    ('{"intent":"cancel","confidence":0.7}', "huỷ"),
    ('{"intent":"reject","confidence":0.6}', "từ chối"),
])
async def test_maps_intent_to_canonical_word(intent, word):
    got = await classify_intent("được rồi triển khai đi", ["PLAN_REVIEW"],
                                run=_run_returning(intent))
    assert isinstance(got, Intent) and got.word == word


@pytest.mark.asyncio
async def test_carries_confidence():
    got = await classify_intent("ok làm đi", ["PLAN_REVIEW"],
                                run=_run_returning('{"intent":"approve","confidence":0.93}'))
    assert got.confidence == pytest.approx(0.93)


@pytest.mark.asyncio
async def test_confidence_missing_defaults_mid_and_clamps():
    # Thiếu confidence → 0.5 (mơ hồ).
    got = await classify_intent("ừ", ["PLAN_REVIEW"], run=_run_returning('{"intent":"approve"}'))
    assert got.confidence == pytest.approx(0.5)
    # Quá biên → kẹp về [0,1].
    got = await classify_intent("ừ", ["PLAN_REVIEW"],
                                run=_run_returning('{"intent":"approve","confidence":9}'))
    assert got.confidence == 1.0


@pytest.mark.asyncio
async def test_none_intent_returns_none():
    got = await classify_intent("fix bug đăng nhập giúp em", ["PLAN_REVIEW"],
                                run=_run_returning('{"intent":"none","confidence":0.9}'))
    assert got is None


@pytest.mark.asyncio
async def test_invalid_or_missing_json_returns_none():
    assert await classify_intent("x", ["PLAN_REVIEW"], run=_run_returning(None)) is None
    assert await classify_intent("x", ["PLAN_REVIEW"],
                                 run=_run_returning('{"intent":"bogus"}')) is None


@pytest.mark.asyncio
async def test_run_not_ok_returns_none():
    got = await classify_intent("ừ", ["VERIFY"],
                                run=_run_returning('{"intent":"approve","confidence":0.9}', ok=False))
    assert got is None


@pytest.mark.asyncio
async def test_run_exception_is_swallowed():
    async def _boom(**kw):
        raise RuntimeError("claude died")
    assert await classify_intent("ừ", ["VERIFY"], run=_boom) is None


@pytest.mark.asyncio
async def test_empty_text_or_no_pending_skips_llm():
    called = False
    async def _run(**kw):
        nonlocal called
        called = True
        return ClaudeResult(ok=True, result='```json\n{"intent":"approve","confidence":1}\n```',
                            session_id=None)
    assert await classify_intent("", ["PLAN_REVIEW"], run=_run) is None
    assert await classify_intent("ok", [], run=_run) is None
    assert called is False                          # không tốn 1 lần gọi LLM vô ích


def test_extract_takes_last_valid_object():
    # Có nhiều object — lấy cái CUỐI hợp lệ (giống quy ước parse khối json cuối của Claude).
    out = 'rác {"foo":1} rồi ```json\n{"intent":"cancel","confidence":0.8}\n```'
    assert _extract(out) == ("cancel", 0.8)
    assert _extract("không có json") is None
