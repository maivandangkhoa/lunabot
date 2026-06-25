"""Catalog dịch chatbot — gói báo cáo nghiệp vụ (app/report.py): bàn giao UAT cho người tạo
yêu cầu + gói duyệt 10.x cho manager. Xem app/web/i18n/__init__.py."""
from __future__ import annotations

TEXTS: dict[str, dict[str, str]] = {
    "rpt.bullet": {"vi": "• {x}", "en": "• {x}", "ko": "• {x}"},

    # ── loại thay đổi (10.1) ──
    "rpt.ctype.bug_fix": {"vi": "Sửa lỗi", "en": "Bug Fix", "ko": "버그 수정"},
    "rpt.ctype.feature": {"vi": "Tính năng mới", "en": "Feature", "ko": "기능 추가"},
    "rpt.ctype.improvement": {"vi": "Cải tiến", "en": "Improvement", "ko": "개선"},
    "rpt.ctype.refactor": {"vi": "Tái cấu trúc", "en": "Refactor", "ko": "리팩터링"},

    # ── bàn giao UAT cho người tạo yêu cầu (ngôn ngữ nghiệp vụ, KHÔNG lộ kỹ thuật) ──
    "rpt.uat.header": {
        "vi": "✅ Em đã hoàn thành thay đổi và tự kiểm thử xong.",
        "en": "✅ I've completed the changes and finished self-testing.",
        "ko": "✅ 변경을 완료하고 자체 테스트까지 마쳤습니다.",
    },
    "rpt.uat.changes_label": {
        "vi": "Các thay đổi:", "en": "Changes:", "ko": "변경 사항:",
    },
    "rpt.uat.selftest_label": {
        "vi": "Kết quả tự kiểm thử:", "en": "Self-test results:", "ko": "자체 테스트 결과:",
    },
    "rpt.uat.conclusion": {
        "vi": "Kết luận: {c}", "en": "Conclusion: {c}", "ko": "결론: {c}",
    },
    "rpt.uat.ask": {
        "vi": ("Anh/chị kiểm tra giúp xem đã đúng mong muốn chưa nhé. Nếu đạt, bấm "
               "**✅ Đạt** (hoặc trả lời 'ok') để em trình quản lý duyệt; chưa đúng thì bấm "
               "**🔧 Cần sửa** và mô tả thêm để em chỉnh."),
        "en": ("Please check whether this matches what you wanted. If it's good, tap "
               "**✅ Good** (or reply 'ok') so I can submit it to the manager for approval; "
               "if not, tap **🔧 Needs fix** and describe what to adjust."),
        "ko": ("원하신 대로 되었는지 확인해 주세요. 괜찮으면 **✅ 통과**를 누르거나 'ok'라고 "
               "답해 주시면 매니저 승인에 올리겠습니다. 아니라면 **🔧 수정 필요**를 누르고 "
               "수정할 점을 알려주세요."),
    },

    # ── gói duyệt cho manager (10.1–10.10) — được kèm chi tiết kỹ thuật ──
    "rpt.mgr.header": {
        "vi": "🔔 Yêu cầu #{id} «{title}» đã sẵn sàng merge `{prod}` — mời anh/chị duyệt.",
        "en": "🔔 Request #{id} «{title}» is ready to merge into `{prod}` — please review.",
        "ko": "🔔 요청 #{id} «{title}»이(가) `{prod}` 머지 준비 완료 — 검토 부탁드립니다.",
    },
    "rpt.mgr.change_type": {"vi": "📌 Loại thay đổi:", "en": "📌 Change type:", "ko": "📌 변경 유형:"},
    "rpt.mgr.problem": {"vi": "🧩 Vấn đề:", "en": "🧩 Problem:", "ko": "🧩 문제:"},
    "rpt.mgr.root_cause": {"vi": "🔍 Nguyên nhân:", "en": "🔍 Root cause:", "ko": "🔍 원인:"},
    "rpt.mgr.solution": {"vi": "🛠 Giải pháp:", "en": "🛠 Solution:", "ko": "🛠 해결책:"},
    "rpt.mgr.scope": {"vi": "🎯 Phạm vi ảnh hưởng:", "en": "🎯 Scope:", "ko": "🎯 영향 범위:"},
    "rpt.mgr.tests": {
        "vi": "🧪 Kiểm thử: Self-test {selftest} · DEV đã deploy · UAT {uat}",
        "en": "🧪 Testing: Self-test {selftest} · DEV deployed · UAT {uat}",
        "ko": "🧪 테스트: 자체 테스트 {selftest} · DEV 배포됨 · UAT {uat}",
    },
    "rpt.mgr.tests_done": {"vi": "đã làm", "en": "done", "ko": "완료"},
    "rpt.mgr.uat_yes": {"vi": "người dùng đã xác nhận", "en": "user confirmed", "ko": "사용자 확인됨"},
    "rpt.mgr.uat_by": {
        "vi": "{who} đã xác nhận", "en": "confirmed by {who}", "ko": "{who} 확인",
    },
    "rpt.mgr.files_label": {
        "vi": "📁 File thay đổi:", "en": "📁 Files changed:", "ko": "📁 변경된 파일:",
    },
    "rpt.mgr.file_line": {
        "vi": "  {status}: {path} (+{added}/-{deleted})",
        "en": "  {status}: {path} (+{added}/-{deleted})",
        "ko": "  {status}: {path} (+{added}/-{deleted})",
    },
    "rpt.mgr.files_more": {
        "vi": "  … và {n} file khác", "en": "  … and {n} more files", "ko": "  … 외 {n}개 파일",
    },
    "rpt.mgr.stats": {
        "vi": "📊 Thống kê: {files} file thay đổi, +{ins} / -{dels}",
        "en": "📊 Stats: {files} files changed, +{ins} / -{dels}",
        "ko": "📊 통계: 파일 {files}개 변경, +{ins} / -{dels}",
    },
    "rpt.mgr.diff": {"vi": "🔎 Diff: {pr}", "en": "🔎 Diff: {pr}", "ko": "🔎 Diff: {pr}"},
    "rpt.mgr.dev_link": {
        "vi": "🌐 Môi trường DEV: {url}", "en": "🌐 DEV environment: {url}", "ko": "🌐 DEV 환경: {url}",
    },
    "rpt.mgr.ask": {
        "vi": "(Bấm nút, hoặc trả lời: ok để duyệt · từ chối)",
        "en": "(Tap a button, or reply: ok to approve · reject)",
        "ko": "(버튼을 누르거나 답장하세요: ok 승인 · 거절)",
    },
}
