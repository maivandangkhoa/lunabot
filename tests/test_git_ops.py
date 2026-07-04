"""Tests git_ops — chạy git thật trên 1 bare repo local đóng vai 'remote' (không mạng,
không token). Phủ: clone, branch, commit, push nhánh bot/*; pre-push hook CHẶN push `main`.
"""
from pathlib import Path

import pytest

from app.git_ops import (
    abort_merge,
    commit_all,
    conflicted_files,
    divergence,
    ensure_clone,
    has_conflict_markers,
    merge_branch,
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
async def test_ensure_clone_refreshes_worktree_on_reclone(tmp_path):
    """Bản clone tái dùng phải thấy code mới khi nguồn khác push lên base (không chỉ fetch ref)."""
    remote = await _seed_remote(tmp_path)
    repo_dir = tmp_path / "ws_refresh"
    await ensure_clone(repo_dir, str(remote), "dev", PROTECTED)
    assert not (repo_dir / "new.txt").exists()

    # Nguồn khác đẩy commit mới lên dev qua 1 clone độc lập.
    other = tmp_path / "other"
    await run_git(["clone", "--branch", "dev", str(remote), str(other)])
    await _config_identity(other)
    (other / "new.txt").write_text("from elsewhere\n")
    await commit_all(other, "feat: external change")
    await push_branch(other, "dev")

    # Gọi lại ensure_clone trên bản cũ → working tree phải có file mới.
    await ensure_clone(repo_dir, str(remote), "dev", PROTECTED)
    assert (repo_dir / "new.txt").read_text() == "from elsewhere\n"


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


async def _push_to_main(tmp_path: Path, remote: Path, fname: str, content: str) -> None:
    """Human đẩy commit thẳng lên main qua clone độc lập (không hook)."""
    other = tmp_path / f"human_{fname}"
    await run_git(["clone", "--branch", "main", str(remote), str(other)])
    await _config_identity(other)
    (other / fname).write_text(content)
    await commit_all(other, f"hotfix: {fname}")
    await run_git(["push", "origin", "main"], cwd=other)


@pytest.mark.asyncio
async def test_divergence_counts_prod_only_commits(tmp_path):
    remote = await _seed_remote(tmp_path)
    repo_dir = tmp_path / "ws_div"
    await ensure_clone(repo_dir, str(remote), "dev", PROTECTED)
    assert await divergence(repo_dir, "dev", "main") == 0

    await _push_to_main(tmp_path, remote, "hotfix.txt", "hot\n")
    assert await divergence(repo_dir, "dev", "main") == 1


@pytest.mark.asyncio
async def test_merge_branch_clean(tmp_path):
    remote = await _seed_remote(tmp_path)
    repo_dir = tmp_path / "ws_mc"
    await ensure_clone(repo_dir, str(remote), "dev", PROTECTED)
    await _config_identity(repo_dir)
    await _push_to_main(tmp_path, remote, "hotfix.txt", "hot\n")
    await run_git(["fetch", "origin", "main"], cwd=repo_dir)

    assert await merge_branch(repo_dir, "dev", "main") is True
    assert (repo_dir / "hotfix.txt").exists()
    await push_branch(repo_dir, "dev")
    assert await divergence(repo_dir, "dev", "main") == 0


@pytest.mark.asyncio
async def test_merge_branch_conflict_resolve_and_abort(tmp_path):
    remote = await _seed_remote(tmp_path)
    repo_dir = tmp_path / "ws_cf"
    await ensure_clone(repo_dir, str(remote), "dev", PROTECTED)
    await _config_identity(repo_dir)
    # dev sửa README một kiểu…
    (repo_dir / "README.md").write_text("dev version\n")
    await commit_all(repo_dir, "dev change")
    await push_branch(repo_dir, "dev")
    # …human sửa cùng file trên main kiểu khác.
    await _push_to_main(tmp_path, remote, "README.md", "main hotfix\n")
    await run_git(["fetch", "origin", "main"], cwd=repo_dir)

    assert await merge_branch(repo_dir, "dev", "main") is False
    files = await conflicted_files(repo_dir)
    assert files == ["README.md"]
    assert has_conflict_markers(repo_dir, files) is True

    # abort đưa worktree về sạch.
    await abort_merge(repo_dir)
    assert await conflicted_files(repo_dir) == []
    assert (repo_dir / "README.md").read_text() == "dev version\n"

    # resolve tay (đóng vai Claude) rồi commit hoàn tất merge.
    assert await merge_branch(repo_dir, "dev", "main") is False
    (repo_dir / "README.md").write_text("dev version + main hotfix\n")
    assert has_conflict_markers(repo_dir, ["README.md"]) is False
    assert await commit_all(repo_dir, "merge main into dev (resolved)") is True
    await push_branch(repo_dir, "dev")
    assert await divergence(repo_dir, "dev", "main") == 0
