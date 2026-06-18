"""Tests prompts — build-gate trong executing prompt (Claude tự dò lệnh kiểm tra env-free)."""
from app.prompts import executing_system_prompt


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
