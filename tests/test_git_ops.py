"""Tests git_ops — chạy git thật trên 1 bare repo local đóng vai 'remote' (không mạng,
không token). Phủ: clone, branch, commit, push nhánh bot/*; pre-push hook CHẶN push `main`.
"""
from pathlib import Path

import pytest

from app.git_ops import (
    commit_all,
    ensure_clone,
    prepare_branch,
    push_branch,
    run_git,
)

PROTECTED = ["main"]


async def _seed_remote(tmp_path: Path) -> Path:
    """Tạo bare remote có nhánh main + dev với 1 commit."""
    remote = tmp_path / "remote.git"
    await run_git(["init", "--bare", str(remote)])
    seed = tmp_path / "seed"
    await run_git(["init", str(seed)])
    await run_git(["config", "user.email", "t@luna.dev"], cwd=seed)
    await run_git(["config", "user.name", "t"], cwd=seed)
    (seed / "README.md").write_text("seed\n")
    await run_git(["add", "-A"], cwd=seed)
    await run_git(["commit", "-m", "init"], cwd=seed)
    await run_git(["branch", "-M", "main"], cwd=seed)
    await run_git(["remote", "add", "origin", str(remote)], cwd=seed)
    await run_git(["push", "origin", "main"], cwd=seed)
    await run_git(["checkout", "-b", "dev"], cwd=seed)
    await run_git(["push", "origin", "dev"], cwd=seed)
    return remote


async def _config_identity(repo_dir: Path) -> None:
    await run_git(["config", "user.email", "bot@luna.dev"], cwd=repo_dir)
    await run_git(["config", "user.name", "luna bot"], cwd=repo_dir)


@pytest.mark.asyncio
async def test_clone_branch_commit_push(tmp_path):
    remote = await _seed_remote(tmp_path)
    repo_dir = tmp_path / "ws" / "acme" / "widgets"

    await ensure_clone(repo_dir, str(remote), "dev", PROTECTED)
    assert (repo_dir / ".git" / "hooks" / "pre-push").exists()
    await _config_identity(repo_dir)

    await prepare_branch(repo_dir, "bot/req-1", "dev")
    (repo_dir / "feature.txt").write_text("hello\n")
    changed = await commit_all(repo_dir, "feat: add feature")
    assert changed is True

    await push_branch(repo_dir, "bot/req-1")  # không raise = push OK
    # Nhánh đã có trên remote.
    refs = await run_git(["ls-remote", "--heads", str(remote), "bot/req-1"])
    assert "bot/req-1" in refs.stdout


@pytest.mark.asyncio
async def test_commit_all_noop_when_clean(tmp_path):
    remote = await _seed_remote(tmp_path)
    repo_dir = tmp_path / "ws2"
    await ensure_clone(repo_dir, str(remote), "dev", PROTECTED)
    await _config_identity(repo_dir)
    assert await commit_all(repo_dir, "nothing") is False


@pytest.mark.asyncio
async def test_pre_push_hook_blocks_main(tmp_path):
    remote = await _seed_remote(tmp_path)
    repo_dir = tmp_path / "ws3"
    await ensure_clone(repo_dir, str(remote), "dev", PROTECTED)
    await _config_identity(repo_dir)

    await run_git(["checkout", "main"], cwd=repo_dir)
    (repo_dir / "x.txt").write_text("x\n")
    await commit_all(repo_dir, "sneaky direct commit")

    res = await run_git(["push", "origin", "main"], cwd=repo_dir, check=False)
    assert res.returncode != 0
    assert "BLOCKED" in res.stderr
