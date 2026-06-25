"""Gói báo cáo nghiệp vụ (CLAUDE_WORKFLOW.md) — dựng từ tín hiệu Claude + thống kê git,
rồi định dạng 2 góc nhìn:

  • self_test_message(req)  → cho NGƯỜI TẠO YÊU CẦU lúc bàn giao (VERIFY/UAT): ngôn ngữ
    nghiệp vụ, KHÔNG lộ PR/commit/log/cấu trúc nội bộ.
  • manager_packet(req,…)   → cho NGƯỜI DUYỆT lúc duyệt merge (mục 10.1–10.10): loại thay
    đổi, vấn đề, nguyên nhân, giải pháp, phạm vi, kết quả test, danh sách file, thống kê,
    diff (PR). Đây là NƠI DUY NHẤT được phép kèm chi tiết kỹ thuật.

Tách khỏi orchestrator.py để giữ file < 500 LOC. Báo cáo là phụ trợ: thiếu field thì bỏ
qua mục đó, KHÔNG bao giờ raise.
"""
from __future__ import annotations

from app.models import Repository, Request, User
from app.web.i18n import t

# Field nghiệp vụ Claude trả ở action "implemented" (xem prompts.executing_system_prompt).
_TEXT_FIELDS = ("summary", "change_type", "problem", "root_cause", "solution",
                "self_test_conclusion")
_LIST_FIELDS = ("scope", "changes", "self_test")


def build_report(data: dict, diff: dict | None = None) -> dict:
    """Gộp tín hiệu Claude (data) + thống kê git (diff) thành report lưu vào requests.report_json.

    Số liệu file/diff lấy từ GIT (nguồn sự thật), không tin con số Claude tự khai.
    """
    report: dict = {}
    for k in _TEXT_FIELDS:
        v = data.get(k)
        if isinstance(v, str) and v.strip():
            report[k] = v.strip()
    for k in _LIST_FIELDS:
        v = data.get(k)
        if isinstance(v, list):
            items = [str(x).strip() for x in v if str(x).strip()]
            if items:
                report[k] = items
    if diff:
        report["diff"] = {
            "files": diff.get("files", []),
            "files_changed": diff.get("files_changed", 0),
            "insertions": diff.get("insertions", 0),
            "deletions": diff.get("deletions", 0),
        }
    return report


def _bullets(items: list[str]) -> str:
    return "\n".join(t("rpt.bullet", x=x) for x in items)


def _ctype_label(code: str | None) -> str | None:
    if not code:
        return None
    key = f"rpt.ctype.{code.strip().lower()}"
    label = t(key)
    return label if label != key else code  # thiếu trong catalog → giữ nguyên giá trị Claude


# --------------------------------------------------------------------------- #
# Góc nhìn NGƯỜI TẠO YÊU CẦU (bàn giao UAT) — chỉ ngôn ngữ nghiệp vụ
# --------------------------------------------------------------------------- #
def self_test_message(req: Request) -> str:
    """Tin bàn giao cho người tạo yêu cầu ở bước VERIFY (tự kiểm thử + mời xác nhận)."""
    r = req.report_json or {}
    parts = [t("rpt.uat.header")]
    summary = r.get("summary")
    if summary:
        parts.append(summary)
    if r.get("changes"):
        parts.append(t("rpt.uat.changes_label") + "\n" + _bullets(r["changes"]))
    if r.get("self_test"):
        block = t("rpt.uat.selftest_label") + "\n" + _bullets(r["self_test"])
        if r.get("self_test_conclusion"):
            block += "\n" + t("rpt.uat.conclusion", c=r["self_test_conclusion"])
        parts.append(block)
    parts.append(t("rpt.uat.ask"))
    return "\n\n".join(parts)


# --------------------------------------------------------------------------- #
# Góc nhìn NGƯỜI DUYỆT (manager) — gói duyệt 10.1–10.10 (được kèm chi tiết kỹ thuật)
# --------------------------------------------------------------------------- #
def _dev_url(repo: Repository) -> str | None:
    s = repo.settings_json or {}
    return s.get("dev_url") or s.get("dev_url_auto")


def _files_block(diff: dict) -> str:
    files = diff.get("files") or []
    shown = files[:20]
    lines = [t("rpt.mgr.file_line", status=f.get("status", "?"), path=f.get("path", "?"),
               added=f.get("added", 0), deleted=f.get("deleted", 0)) for f in shown]
    if len(files) > len(shown):
        lines.append(t("rpt.mgr.files_more", n=len(files) - len(shown)))
    return "\n".join(lines)


def manager_packet(req: Request, repo: Repository, *, requester: User | None = None) -> str:
    """Gói duyệt đầy đủ cho manager (10.1–10.10). req.report_json dựng ở EXECUTING."""
    r = req.report_json or {}
    diff = r.get("diff") or {}
    sections: list[str] = [t("rpt.mgr.header", id=req.id, title=req.title, prod=repo.prod_branch)]

    def add(label_key: str, value: str | None) -> None:
        if value:
            sections.append(t(label_key) + " " + value)

    add("rpt.mgr.change_type", _ctype_label(r.get("change_type")))   # 10.1
    add("rpt.mgr.problem", r.get("problem"))                          # 10.2
    add("rpt.mgr.root_cause", r.get("root_cause"))                    # 10.3
    add("rpt.mgr.solution", r.get("solution"))                       # 10.4
    if r.get("scope"):                                                # 10.5
        sections.append(t("rpt.mgr.scope") + " " + ", ".join(r["scope"]))

    # 10.6 kết quả kiểm thử (Self/DEV/UAT) — tới được đây nghĩa là user đã xác nhận (UAT) và
    # dev đã merge/deploy.
    who = requester.display_name if requester and getattr(requester, "display_name", None) else None
    sections.append(t("rpt.mgr.tests",
                      selftest=r.get("self_test_conclusion") or t("rpt.mgr.tests_done"),
                      uat=t("rpt.mgr.uat_by", who=who) if who else t("rpt.mgr.uat_yes")))

    if diff.get("files"):                                             # 10.7 danh sách file
        sections.append(t("rpt.mgr.files_label") + "\n" + _files_block(diff))
    if diff:                                                          # 10.8 thống kê
        sections.append(t("rpt.mgr.stats", files=diff.get("files_changed", 0),
                          ins=diff.get("insertions", 0), dels=diff.get("deletions", 0)))
    if req.pr_url:                                                    # 10.9 diff review
        sections.append(t("rpt.mgr.diff", pr=req.pr_url))

    dev = _dev_url(repo)                                              # 10.10 thông tin triển khai
    if dev:
        sections.append(t("rpt.mgr.dev_link", url=dev))

    sections.append(t("rpt.mgr.ask"))
    return "\n\n".join(sections)
