"""Dọn side-effect git/GitHub khi request bị huỷ/từ chối — tách khỏi orchestrator để
giữ orchestrator gọn (≤500 LOC). Best-effort: lỗi không làm hỏng FSM (đã CANCELLED),
chỉ gom warns để báo người dùng.
"""
from __future__ import annotations

import logging

from app.models import Request

log = logging.getLogger("luna.cleanup")


async def cleanup_branch(orch, req: Request, *, revert_dev: bool) -> list[str]:
    """revert dev (nếu đã merge), đóng PR, xoá nhánh. `orch` là Orchestrator (dùng github/
    git/_ensure_repo_cloned của nó). Trả danh sách cảnh báo cho các bước thất bại."""
    warns: list[str] = []
    if orch.github is None:
        return warns
    from app.orchestrator import _repo_locks  # tránh import vòng (orchestrator import module này)

    repo = orch._repo(req)
    iid = repo.gh_installation_id
    if revert_dev and req.dev_merge_sha:
        try:
            async with _repo_locks[repo.id]:
                repo_dir = await orch._ensure_repo_cloned(repo)
                await orch.git.revert_merge(repo_dir, repo.base_branch, req.dev_merge_sha)
        except Exception as exc:  # noqa: BLE001
            log.warning("revert dev req %s lỗi: %s", req.id, exc)
            warns.append(f"hoàn tác `{repo.base_branch}` thất bại — cần kiểm tra thủ công")
    ops = []
    if req.pr_number:
        ops.append(("đóng PR", orch.github.close_pull_request(iid, repo.repo_full_name, req.pr_number)))
    if req.branch_name:
        ops.append(("xoá nhánh", orch.github.delete_branch(iid, repo.repo_full_name, req.branch_name)))
    for what, coro in ops:
        try:
            await coro
        except Exception as exc:  # noqa: BLE001
            log.warning("%s req %s lỗi: %s", what, req.id, exc)
    return warns
