"""Tests gói báo cáo nghiệp vụ (app/report.py) — CLAUDE_WORKFLOW.md.

Bất biến: tin cho NGƯỜI TẠO YÊU CẦU không lộ PR/commit/diff; gói cho MANAGER có đủ
10.1–10.10 (loại thay đổi/nguyên nhân/giải pháp/phạm vi/test/file/thống kê/diff).
"""
from app import report
from app.models import Repository, Request, User, UserRole

DATA = {
    "action": "implemented",
    "summary": "Thêm giới hạn số lần đăng nhập sai",
    "change_type": "feature",
    "problem": "Người dùng có thể thử mật khẩu vô hạn",
    "root_cause": "Chưa có cơ chế khoá tạm",
    "solution": "Khoá 5 phút sau 5 lần sai",
    "scope": ["Authentication", "API"],
    "changes": ["Khoá tài khoản tạm sau 5 lần sai", "Hiện thông báo còn lại bao nhiêu lần"],
    "self_test": ["✓ Đăng nhập đúng vẫn vào được", "✓ Sai 5 lần thì bị khoá"],
    "self_test_conclusion": "PASS",
}
DIFF = {"files": [{"path": "auth/login.py", "status": "modified", "added": 12, "deleted": 3}],
        "files_changed": 1, "insertions": 12, "deletions": 3}


def test_build_report_merges_signal_and_diff():
    r = report.build_report(DATA, DIFF)
    assert r["change_type"] == "feature"
    assert r["scope"] == ["Authentication", "API"]
    assert r["self_test_conclusion"] == "PASS"
    assert r["diff"]["files_changed"] == 1 and r["diff"]["insertions"] == 12


def test_build_report_drops_empty_and_ignores_bad_types():
    # changes=[] (rỗng) và scope=chuỗi (sai kiểu) đều bị loại; không có diff → không có key diff.
    r = report.build_report({"summary": "x", "changes": [], "scope": "not-a-list"}, None)
    assert r == {"summary": "x"}


def _req(report_json=None, pr_url="https://github.com/acme/widgets/pull/7"):
    return Request(id=1, title="Giới hạn đăng nhập", pr_url=pr_url, report_json=report_json)


def _repo():
    return Repository(repo_full_name="acme/widgets", prod_branch="main",
                      settings_json={"dev_url_auto": "https://acme-dev.web.app"})


def test_self_test_message_is_business_no_tech():
    r = report.build_report(DATA, DIFF)
    msg = report.self_test_message(_req(r))
    # Có nội dung nghiệp vụ.
    assert "Khoá tài khoản tạm sau 5 lần sai" in msg
    assert "Kết quả tự kiểm thử" in msg and "PASS" in msg
    # KHÔNG lộ kỹ thuật cho người tạo yêu cầu.
    assert "pull/7" not in msg
    assert "auth/login.py" not in msg
    assert "+12" not in msg


def test_manager_packet_has_full_1010():
    r = report.build_report(DATA, DIFF)
    requester = User(display_name="Bob", role=UserRole.EMPLOYEE)
    msg = report.manager_packet(_req(r), _repo(), requester=requester)
    assert "sẵn sàng merge" in msg                      # header
    assert "Tính năng mới" in msg                        # 10.1 change_type đã dịch
    assert "Người dùng có thể thử mật khẩu vô hạn" in msg  # 10.2 problem
    assert "Chưa có cơ chế khoá tạm" in msg              # 10.3 root cause
    assert "Khoá 5 phút" in msg                          # 10.4 solution
    assert "Authentication" in msg                        # 10.5 scope
    assert "Bob" in msg                                   # 10.6 UAT người xác nhận
    assert "auth/login.py" in msg                         # 10.7 file list
    assert "+12" in msg and "-3" in msg                   # 10.8 stats
    assert "pull/7" in msg                                # 10.9 diff (PR) — manager ĐƯỢC xem
    assert "acme-dev.web.app" in msg                      # 10.10 dev link


def test_manager_packet_survives_missing_fields():
    # report_json tối thiểu (chỉ summary) không được làm vỡ gói duyệt.
    msg = report.manager_packet(_req({"summary": "x"}), _repo())
    assert "sẵn sàng merge" in msg
