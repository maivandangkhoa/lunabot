"""Tests prompts — build-gate trong executing prompt (Claude tự dò lệnh kiểm tra env-free)."""
from app.prompts import analyzing_system_prompt, ask_system_prompt, executing_system_prompt


def test_analyze_prompt_has_identity_guard():
    """Phase read-only phải cấm Claude rò rỉ meta tooling/permission ra khách."""
    p = analyzing_system_prompt("acme/x", "dev")
    assert "BACKEND" in p
    assert "dangerously-skip-permissions" in p  # nằm trong danh sách CẤM nhắc
    assert "BỊ CHẶN LÀ ĐÚNG THIẾT KẾ" in p


def test_ask_prompt_has_identity_guard():
    p = ask_system_prompt("acme/x", "dev")
    assert "BACKEND" in p and "claude.ai" in p


def test_executing_prompt_default_auto_detects_checks():
    """Không có build_cmd → mặc định dặn Claude TỰ dò lệnh kiểm tra không cần env."""
    p = executing_system_prompt("acme/x", "dev", "bot/req-1", ["main"])
    assert "TỰ phát hiện" in p
    assert 'không trả "implemented"' in p
    assert "BỎ QUA mọi lỗi do" in p  # bỏ qua lỗi thiếu env/secret


def test_executing_prompt_build_cmd_overrides_auto_detect():
    p = executing_system_prompt("acme/x", "dev", "bot/req-1", ["main"],
                                build_cmd="npm run typecheck && npm run lint")
    assert "npm run typecheck && npm run lint" in p
    assert "TỰ phát hiện" not in p   # build_cmd override → không tự đoán
    assert 'không trả "implemented"' in p


def test_executing_prompt_warns_against_verbatim_boilerplate():
    """Văn bản chuẩn (license) phải TẢI từ nguồn chính thức, không gõ nguyên văn → né
    content filter của API (lỗi '400 Output blocked by content filtering policy')."""
    p = executing_system_prompt("acme/x", "dev", "bot/req-1", ["main"])
    assert "BOILERPLATE" in p and "curl" in p
    assert "content filter" in p
