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
    if not protected:                       # dev-mode: không chặn nhánh nào (tự do push)
        return "#!/bin/sh\nexit 0\n"
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
    """Clone nếu chưa có (nhánh base), else fetch + đưa working tree về base mới nhất.

    Bản clone được tái dùng xuyên nhiều request, và base có thể bị nguồn khác push lên.
    `fetch` chỉ cập nhật ref nên working tree còn cũ → phase đọc (analyze/ask) sẽ thấy code
    lỗi thời. Vì thế reset cứng về `origin/base` để mọi phase luôn nhìn code mới nhất. An
    toàn: caller EXECUTING gọi `prepare_branch` ngay sau (dựng lại nhánh làm việc từ base)."""
    repo_dir = Path(repo_dir)
    if not (repo_dir / ".git").exists():
        repo_dir.parent.mkdir(parents=True, exist_ok=True)
        await run_git(["clone", "--branch", base_branch, clone_url, str(repo_dir)])
    else:
        await run_git(["remote", "set-url", "origin", clone_url], cwd=repo_dir)
        await run_git(["fetch", "origin", base_branch], cwd=repo_dir)
        await run_git(["checkout", base_branch], cwd=repo_dir, check=False)
        await run_git(["reset", "--hard", f"origin/{base_branch}"], cwd=repo_dir)
    install_pre_push_hook(repo_dir, protected)
    return repo_dir


def exclude_local(repo_dir: Path, pattern: str) -> None:
    """Thêm pattern vào .git/info/exclude (gitignore local, KHÔNG commit) — idempotent.

    Dùng cho thư mục tạm (vd ảnh đính kèm) để `git add -A` không stage vào repo khách.
    """
    info = Path(repo_dir) / ".git" / "info"
    info.mkdir(parents=True, exist_ok=True)
    f = info / "exclude"
    lines = f.read_text().splitlines() if f.exists() else []
    if pattern not in lines:
        with f.open("a") as fh:
            fh.write(f"\n{pattern}\n")


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


_STATUS_LABEL = {"A": "added", "M": "modified", "D": "deleted",
                 "R": "renamed", "C": "copied", "T": "type-changed"}


async def diff_summary(repo_dir: Path, base_branch: str, remote: str = "origin") -> dict:
    """Thống kê thay đổi của nhánh hiện tại so với base (cho gói duyệt manager — mục 10.7/10.8).

    Nguồn sự thật là GIT, không tin số liệu Claude tự khai. Trả:
      {files: [{path, status, added, deleted}], files_changed, insertions, deletions}
    Lỗi (chưa có ref base, repo lạ…) → trả rỗng an toàn, KHÔNG raise (báo cáo chỉ là phụ trợ).
    """
    rng = f"{remote}/{base_branch}...HEAD"
    empty = {"files": [], "files_changed": 0, "insertions": 0, "deletions": 0}
    try:
        numstat = await run_git(["diff", "--numstat", rng], cwd=repo_dir, check=False)
        namestat = await run_git(["diff", "--name-status", rng], cwd=repo_dir, check=False)
    except Exception as exc:  # noqa: BLE001 — báo cáo phụ trợ, không được làm hỏng luồng
        log.warning("diff_summary lỗi: %s", exc)
        return empty
    if numstat.returncode != 0 or namestat.returncode != 0:
        return empty

    # path → (added, deleted); "-" cho file nhị phân.
    counts: dict[str, tuple[int, int]] = {}
    ins = dels = 0
    for line in numstat.stdout.splitlines():
        cols = line.split("\t")
        if len(cols) < 3:
            continue
        a, d, path = cols[0], cols[1], cols[-1]
        ai = int(a) if a.isdigit() else 0
        di = int(d) if d.isdigit() else 0
        ins += ai
        dels += di
        counts[path] = (ai, di)

    files: list[dict] = []
    for line in namestat.stdout.splitlines():
        cols = line.split("\t")
        if len(cols) < 2:
            continue
        code, path = cols[0], cols[-1]
        added, deleted = counts.get(path, (0, 0))
        files.append({"path": path, "status": _STATUS_LABEL.get(code[0], code),
                      "added": added, "deleted": deleted})
    return {"files": files, "files_changed": len(files),
            "insertions": ins, "deletions": dels}


async def fetch_branch(repo_dir: Path, branch: str, remote: str = "origin") -> None:
    await run_git(["fetch", remote, branch], cwd=repo_dir)


async def divergence(
    repo_dir: Path, base_branch: str, prod_branch: str, remote: str = "origin"
) -> int:
    """Số commit trên prod chưa nằm trong base (human push thẳng prod ngoài luồng bot).

    ensure_clone chỉ fetch base → phải fetch prod trước khi đếm. GitError propagate —
    caller quyết định (check phân kỳ là phụ trợ, không được chặn luồng chính).
    """
    await fetch_branch(repo_dir, prod_branch, remote)
    res = await run_git(
        ["rev-list", "--count", f"{remote}/{base_branch}..{remote}/{prod_branch}"],
        cwd=repo_dir)
    return int(res.stdout.strip() or "0")


async def merge_branch(
    repo_dir: Path, into_branch: str, from_ref: str, remote: str = "origin"
) -> bool:
    """Merge `remote/from_ref` vào `into_branch` local. True = sạch (đã commit, CHƯA push);
    False = conflict (repo đang GIỮA merge, caller resolve rồi commit_all hoặc abort_merge).

    Đồng bộ into_branch về remote trước (reset --hard) — cùng lý do revert_merge: merge
    vào dev bình thường đi qua GitHub API nên bản local có thể cũ.
    """
    await run_git(["fetch", remote, into_branch], cwd=repo_dir)
    await run_git(["checkout", into_branch], cwd=repo_dir)
    await run_git(["reset", "--hard", f"{remote}/{into_branch}"], cwd=repo_dir)
    res = await run_git(
        ["merge", "--no-ff", "--no-edit", f"{remote}/{from_ref}"],
        cwd=repo_dir, check=False)
    if res.returncode == 0:
        return True
    if await conflicted_files(repo_dir):
        return False
    raise GitError(f"git merge lỗi (code {res.returncode}): {res.stderr[:500] or res.stdout[:500]}")


async def conflicted_files(repo_dir: Path) -> list[str]:
    res = await run_git(["diff", "--name-only", "--diff-filter=U"], cwd=repo_dir, check=False)
    return [ln.strip() for ln in res.stdout.splitlines() if ln.strip()]


async def abort_merge(repo_dir: Path) -> None:
    await run_git(["merge", "--abort"], cwd=repo_dir, check=False)


def has_conflict_markers(repo_dir: Path, files: list[str]) -> bool:
    """Kiểm chứng sau khi Claude resolve: file nào còn `<<<<<<<` là chưa xong."""
    for f in files:
        fp = Path(repo_dir) / f
        try:
            if "<<<<<<<" in fp.read_text(errors="replace"):
                return True
        except OSError:
            continue
    return False


async def revert_merge(
    repo_dir: Path, base_branch: str, merge_sha: str, remote: str = "origin"
) -> None:
    """Revert merge commit `merge_sha` trên `base_branch` rồi push.

    Đồng bộ về remote trước (reset --hard) vì merge vào dev làm qua GitHub API ⇒ bản
    local có thể cũ. `-m 1`: revert giữ phía base_branch làm mainline. base_branch KHÔNG
    nằm danh sách protected nên pre-push hook không chặn.
    """
    await run_git(["fetch", remote, base_branch], cwd=repo_dir)
    await run_git(["checkout", base_branch], cwd=repo_dir)
    await run_git(["reset", "--hard", f"{remote}/{base_branch}"], cwd=repo_dir)
    await run_git(["revert", "-m", "1", "--no-edit", merge_sha], cwd=repo_dir)
    await run_git(["push", remote, base_branch], cwd=repo_dir)
