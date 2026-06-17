"""Git filesystem ops — clone/fetch, branch, commit, push + pre-push hook chặn `main`.

Tách khỏi github_app.py (auth/REST). Dùng subprocess git async. Isolation: mỗi repo
clone tại WORKSPACE/<tenant>/<repo>. `clone_url` có thể là HTTPS-token (prod) hoặc
đường dẫn local (test) — KHÔNG log url vì có thể chứa token.

pre-push hook là lớp phòng vệ thứ 2 (cùng GitHub branch protection) chặn push thẳng
nhánh protected. Port logic từ bot.py:62-75.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import asyncio

log = logging.getLogger("luna.git")


class GitError(RuntimeError):
    pass


@dataclass
class GitResult:
    returncode: int
    stdout: str
    stderr: str


async def run_git(args: list[str], cwd: Path | str | None = None, check: bool = True) -> GitResult:
    """Chạy `git <args>`. Log theo subcommand (không log url chứa token)."""
    log.info("git %s (cwd=%s)", args[0] if args else "?", cwd)
    proc = await asyncio.create_subprocess_exec(
        "git", *args,
        cwd=str(cwd) if cwd else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    res = GitResult(proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace"))
    if check and res.returncode != 0:
        raise GitError(f"git {args[0]} lỗi (code {res.returncode}): {res.stderr[:500]}")
    return res


def _pre_push_hook(protected: list[str]) -> str:
    cases = "|".join(f"refs/heads/{b}" for b in protected)
    return (
        "#!/bin/sh\n"
        "# luna policy: chặn push thẳng các nhánh protected.\n"
        "while read _l _ls remote_ref _rs; do\n"
        '  case "$remote_ref" in\n'
        f"    {cases})\n"
        '      echo "pre-push BLOCKED: push \'$remote_ref\' bị cấm bởi luna policy." >&2\n'
        "      exit 1 ;;\n"
        "  esac\n"
        "done\n"
        "exit 0\n"
    )


def install_pre_push_hook(repo_dir: Path, protected: list[str]) -> None:
    hook = repo_dir / ".git" / "hooks" / "pre-push"
    hook.write_text(_pre_push_hook(protected))
    hook.chmod(0o755)


async def ensure_clone(
    repo_dir: Path, clone_url: str, base_branch: str, protected: list[str],
) -> Path:
    """Clone nếu chưa có (nhánh base), else fetch cập nhật. Luôn (cài lại) pre-push hook."""
    repo_dir = Path(repo_dir)
    if not (repo_dir / ".git").exists():
        repo_dir.parent.mkdir(parents=True, exist_ok=True)
        await run_git(["clone", "--branch", base_branch, clone_url, str(repo_dir)])
    else:
        await run_git(["remote", "set-url", "origin", clone_url], cwd=repo_dir)
        await run_git(["fetch", "origin", base_branch], cwd=repo_dir)
    install_pre_push_hook(repo_dir, protected)
    return repo_dir


async def prepare_branch(repo_dir: Path, branch: str, base_branch: str) -> None:
    """Tạo/đưa về nhánh làm việc từ base mới nhất (idempotent)."""
    await run_git(["checkout", base_branch], cwd=repo_dir)
    await run_git(["pull", "--rebase", "origin", base_branch], cwd=repo_dir, check=False)
    existing = await run_git(["rev-parse", "--verify", branch], cwd=repo_dir, check=False)
    if existing.returncode == 0:
        await run_git(["checkout", branch], cwd=repo_dir)
    else:
        await run_git(["checkout", "-b", branch], cwd=repo_dir)


async def commit_all(repo_dir: Path, message: str) -> bool:
    """Stage tất cả + commit. Trả False nếu không có gì để commit."""
    await run_git(["add", "-A"], cwd=repo_dir)
    status = await run_git(["status", "--porcelain"], cwd=repo_dir)
    if not status.stdout.strip():
        return False
    await run_git(["commit", "-m", message], cwd=repo_dir)
    return True


async def push_branch(repo_dir: Path, branch: str, remote: str = "origin") -> None:
    """Push nhánh làm việc. pre-push hook sẽ chặn nếu là nhánh protected."""
    await run_git(["push", "-u", remote, branch], cwd=repo_dir)
