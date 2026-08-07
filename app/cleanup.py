"""Dọn side-effect git/GitHub khi request bị huỷ/từ chối — tách khỏi orchestrator để
giữ orchestrator gọn (≤500 LOC). Best-effort: lỗi không làm hỏng FSM (đã CANCELLED),
chỉ gom warns để báo người dùng.
"""
from __future__ import annotations

import logging

from app.models import Request
from app.web.i18n import t

log = logging.getLogger("luna.cleanup")

# Sổ ghi MỌI merge commit lên dev của 1 request. Mỗi vòng "Cần sửa"/auto-fix mở PR mới
# (prepare_branch reset nhánh về dev) ⇒ thêm 1 merge commit riêng; chỉ nhớ sha cuối thì
# revert sót các vòng trước và chúng rò lên main ở lần approve kế tiếp.
# Khoá "_" = nội bộ FSM, được build_report giữ lại (xem orchestrator._execute).
_SHAS_KEY = "_dev_merge_shas"


def remember_dev_merge(req: Request, sha: str | None) -> None:
    """Ghi nhận 1 lần merge lên dev: `dev_merge_sha` = sha MỚI NHẤT (poll deploy/reconcile
    dùng nó), sổ `_dev_merge_shas` giữ ĐỦ các vòng theo thứ tự cũ → mới để revert sạch."""
    prev = req.dev_merge_sha
    req.dev_merge_sha = sha
    if not sha:
        return
    rj = req.report_json or {}
    ledger = [s for s in (rj.get(_SHAS_KEY) or []) if s]
    # Sổ rỗng mà đã có sha cũ = request dang dở lúc deploy bản này → nạp sha đó vào sổ,
    # nếu không vòng merge cũ mất dấu và ở lại dev sau khi revert.
    if not ledger and prev:
        ledger = [prev]
    req.report_json = {**rj, _SHAS_KEY: [*(s for s in ledger if s != sha), sha]}


def dev_merge_shas(req: Request) -> list[str]:
    """Các sha cần revert, thứ tự MỚI → CŨ (revert ngược chiều merge).
    Fallback `dev_merge_sha` cho request tạo trước khi có sổ."""
    shas = [s for s in ((req.report_json or {}).get(_SHAS_KEY) or []) if s]
    if not shas:
        return [req.dev_merge_sha] if req.dev_merge_sha else []
    return list(reversed(shas))


async def cleanup_branch(orch, req: Request, *, revert_dev: bool) -> list[str]:
    """revert dev (nếu đã merge), đóng PR, xoá nhánh. `orch` là Orchestrator (dùng github/
    git/_ensure_repo_cloned của nó). Trả danh sách cảnh báo cho các bước thất bại."""
    warns: list[str] = []
    if orch.github is None:
        return warns
    from app.orchestrator import _repo_locks  # tránh import vòng (orchestrator import module này)

    repo = orch._repo(req)
    iid = repo.gh_installation_id
    shas = dev_merge_shas(req) if revert_dev else []
    if shas:
        try:
            async with _repo_locks[repo.id]:
                repo_dir = await orch._ensure_repo_cloned(repo)
                await orch.git.revert_merges(repo_dir, repo.base_branch, shas)
        except Exception as exc:  # noqa: BLE001
            log.warning("revert dev req %s (%s sha) lỗi: %s", req.id, len(shas), exc)
            warns.append(t("ops.revert_failed", base=repo.base_branch))
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
