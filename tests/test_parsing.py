"""Tests parsing — trích khối JSON cuối, validate, fallback an toàn."""
from app.parsing import Action, parse_signal


def test_plan_ok():
    text = 'phân tích...\n```json\n{"action":"plan","summary":"x","steps":["a","b"],"risk":"low"}\n```'
    sig = parse_signal(text)
    assert sig.ok and sig.action == Action.PLAN
    assert sig.data["steps"] == ["a", "b"]


def test_clarify_ok_normalizes_string_to_list():
    sig = parse_signal('```json\n{"action":"clarify","questions":"chỉ 1 câu?"}\n```')
    assert sig.ok and sig.action == Action.CLARIFY
    assert sig.data["questions"] == ["chỉ 1 câu?"]


def test_takes_last_block():
    text = '```json\n{"action":"clarify","questions":["a"]}\n```\nrồi\n```json\n{"action":"plan","summary":"s","steps":["x"]}\n```'
    sig = parse_signal(text)
    assert sig.action == Action.PLAN


def test_no_block():
    assert parse_signal("không có json").ok is False


def test_bad_json():
    assert parse_signal("```json\n{nope}\n```").ok is False


def test_unknown_action():
    sig = parse_signal('```json\n{"action":"frobnicate"}\n```')
    assert sig.ok is False and "action không hợp lệ" in sig.error


def test_missing_required_field():
    sig = parse_signal('```json\n{"action":"plan","summary":"x"}\n```')
    assert sig.ok is False and sig.action == Action.PLAN


def test_empty():
    assert parse_signal("").ok is False


def test_strip_json_block():
    from app.parsing import strip_json_block
    assert strip_json_block("Câu trả lời.\n```json\n{\"action\":\"clarify\"}\n```") == "Câu trả lời."
    assert strip_json_block("Chỉ text").strip() == "Chỉ text"
    assert strip_json_block("") == ""


def test_scrub_meta_removes_tooling_leak():
    from app.parsing import scrub_meta
    leaked = (
        "Đây là kế hoạch của bạn:\n"
        "Nếu bạn dùng terminal, gõ: claude --dangerously-skip-permissions\n"
        "Hoặc mở claude.ai/code và bấm nút 🔒 chọn Trust this project.\n"
        "Bạn đang dùng Claude Code ở đâu?\n"
        "Tôi sẽ thêm 2 hàng tài khoản ngân hàng."
    )
    out = scrub_meta(leaked)
    for bad in ("dangerously-skip-permissions", "claude.ai/code", "🔒",
                "Trust this project", "Claude Code"):
        assert bad not in out
    # Nội dung nghiệp vụ hợp lệ được giữ lại.
    assert "thêm 2 hàng tài khoản ngân hàng" in out
    assert "kế hoạch của bạn" in out


def test_scrub_meta_noop_on_clean_text():
    from app.parsing import scrub_meta
    clean = "Bạn muốn thêm mấy tài khoản ngân hàng vào trang thanh toán?"
    assert scrub_meta(clean) == clean
    assert scrub_meta("") == ""
