"""Unit tests cho claude_runner — dùng fake `claude` binary (script tạm), không cần CLI thật.

Phủ: success + parse session/result, truyền đúng flag (--resume / --permission-mode /
--append-system-prompt), parse fail, returncode≠0, timeout, is_error.
"""
import os
import stat
from pathlib import Path

import pytest

from app.claude_runner import PermissionMode, run_claude


def _make_fake(tmp_path: Path, name: str, body: str) -> str:
    """Tạo 1 executable python script đóng vai 'claude', trả về path."""
    p = tmp_path / name
    p.write_text("#!/usr/bin/env python3\n" + body)
    p.chmod(p.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return str(p)


# Fake echo lại argv vào field result → kiểm tra việc dựng flag.
ECHO_ARGS = (
    "import sys, json\n"
    "print(json.dumps({'session_id': 's-new', 'result': ' '.join(sys.argv[1:]), "
    "'is_error': False, 'num_turns': 3, 'total_cost_usd': 0.02}))\n"
)


@pytest.mark.asyncio
async def test_success_parses_fields(tmp_path):
    fake = _make_fake(tmp_path, "claude", ECHO_ARGS)
    res = await run_claude(prompt="fix bug", cwd=tmp_path, claude_bin=fake)
    assert res.ok is True
    assert res.is_error is False
    assert res.session_id == "s-new"
    assert res.num_turns == 3
    assert res.total_cost_usd == 0.02
    # prompt + flag mặc định nằm trong argv được echo lại.
    assert "fix bug" in res.result
    assert "--output-format json" in res.result
    assert "--permission-mode default" in res.result  # mặc định = READONLY (default, KHÔNG plan)


@pytest.mark.asyncio
async def test_flags_resume_bypass_systemprompt(tmp_path):
    fake = _make_fake(tmp_path, "claude", ECHO_ARGS)
    res = await run_claude(
        prompt="go",
        cwd=tmp_path,
        permission_mode=PermissionMode.BYPASS,
        session_id="s-old",
        system_prompt="RULES",
        claude_bin=fake,
    )
    assert "--permission-mode bypassPermissions" in res.result
    assert "--resume s-old" in res.result
    assert "--append-system-prompt RULES" in res.result


@pytest.mark.asyncio
async def test_parse_error(tmp_path):
    fake = _make_fake(tmp_path, "claude", "print('not json at all')\n")
    res = await run_claude(prompt="x", cwd=tmp_path, claude_bin=fake)
    assert res.ok is False
    assert res.is_error is True
    assert "Không parse" in res.result


@pytest.mark.asyncio
async def test_nonzero_exit_no_stdout(tmp_path):
    body = "import sys\nsys.stderr.write('boom')\nsys.exit(2)\n"
    fake = _make_fake(tmp_path, "claude", body)
    res = await run_claude(prompt="x", cwd=tmp_path, claude_bin=fake)
    assert res.ok is False
    assert res.returncode == 2
    assert "boom" in res.result


@pytest.mark.asyncio
async def test_is_error_flag(tmp_path):
    body = (
        "import json\n"
        "print(json.dumps({'session_id': 's1', 'error': 'rate limited', "
        "'is_error': True}))\n"
    )
    fake = _make_fake(tmp_path, "claude", body)
    res = await run_claude(prompt="x", cwd=tmp_path, claude_bin=fake)
    assert res.ok is False
    assert res.is_error is True
    assert res.result == "rate limited"
    assert res.session_id == "s1"


@pytest.mark.asyncio
async def test_timeout(tmp_path):
    body = "import time\ntime.sleep(5)\n"
    fake = _make_fake(tmp_path, "claude", body)
    res = await run_claude(prompt="x", cwd=tmp_path, claude_bin=fake, timeout_s=1)
    assert res.ok is False
    assert res.timed_out is True


@pytest.mark.asyncio
async def test_missing_binary(tmp_path):
    res = await run_claude(
        prompt="x", cwd=tmp_path, claude_bin=str(tmp_path / "nope-does-not-exist")
    )
    assert res.ok is False
    assert "Không tìm thấy" in res.result
