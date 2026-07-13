"""Catalog dịch chatbot — post_deploy + cleanup (deploy-gate, dọn nhánh). Xem app/web/i18n/__init__.py."""
from __future__ import annotations

TEXTS: dict[str, dict[str, str]] = {
    # ── post_deploy: notify_managers — gói duyệt 10.x dựng ở app/report.py:manager_packet ──
    "ops.btn.approve_merge": {"vi": "✅ Cho merge", "en": "✅ Approve merge", "ko": "✅ 머지 승인"},
    "ops.btn.reject": {"vi": "❌ Từ chối", "en": "❌ Reject", "ko": "❌ 거절"},

    # ── post_deploy: notify_other_approvers — báo approver còn lại khi request đã chốt ──
    "ops.resolved_by_other.approved": {
        "vi": "ℹ️ Yêu cầu #{id} đã được {name} duyệt và triển khai lên production.",
        "en": "ℹ️ Request #{id} was approved and deployed to production by {name}.",
        "ko": "ℹ️ #{id} 요청은 {name}님이 승인하여 운영 환경에 배포되었습니다.",
    },
    "ops.resolved_by_other.rejected": {
        "vi": "ℹ️ Yêu cầu #{id} đã bị {name} từ chối và hoàn tác.",
        "en": "ℹ️ Request #{id} was rejected and rolled back by {name}.",
        "ko": "ℹ️ #{id} 요청은 {name}님이 거절하여 되돌려졌습니다.",
    },

    # ── post_deploy: enter_await_manager ──
    "ops.await_manager.default": {
        "vi": "✅ Em đã trình yêu cầu lên manager để duyệt triển khai production. "
              "Em sẽ báo anh/chị ngay khi có kết quả.",
        "en": "✅ I've submitted the request to the manager for production approval. "
              "I'll let you know as soon as there's a decision.",
        "ko": "✅ 운영 배포 승인을 위해 매니저에게 요청을 올렸습니다. "
              "결과가 나오는 대로 알려드리겠습니다.",
    },

    # ── post_deploy: enter_uat (preview-first: mời requester UAT trên URL dev thật) ──
    "ops.uat.deployed_link": {
        "vi": "✅ Em đã đưa thay đổi lên môi trường thử nghiệm (dev). "
              "Anh/chị mở kiểm tra thực tế tại:\n{url}",
        "en": "✅ I've deployed the change to the test (dev) environment. "
              "Please check it live here:\n{url}",
        "ko": "✅ 변경 사항을 테스트(dev) 환경에 배포했습니다. "
              "실제 화면을 여기에서 확인해 주세요:\n{url}",
    },
    "ops.uat.deployed": {
        "vi": "✅ Em đã đưa thay đổi lên môi trường thử nghiệm (dev) để anh/chị kiểm tra.",
        "en": "✅ I've deployed the change to the test (dev) environment for you to check.",
        "ko": "✅ 변경 사항을 테스트(dev) 환경에 배포했으니 확인해 주세요.",
    },

    # ── post_deploy: _run_verify_loop ──
    "ops.deploy_retry": {
        "vi": "🔧 Deploy/kiểm thử dev chưa đạt ({reason}). Em tự sửa lại (lần {round})…",
        "en": "🔧 Dev deploy/test not passing yet ({reason}). I'll fix it myself (attempt {round})…",
        "ko": "🔧 dev 배포/테스트가 아직 통과하지 못했습니다 ({reason}). 제가 직접 수정합니다 ({round}번째)…",
    },

    # ── post_deploy: _give_up ──
    "ops.give_up": {
        "vi": "⚠️ Thay đổi chưa chạy ổn trên môi trường thử nghiệm.{extra}\n"
              "Em CHƯA báo manager. Anh/chị muốn em sửa tiếp (bấm 'Cần sửa' rồi mô tả) hay huỷ?",
        "en": "⚠️ The change isn't running smoothly on the test environment yet.{extra}\n"
              "I have NOT notified the manager. Do you want me to keep fixing (tap 'Needs fix' then describe) or cancel?",
        "ko": "⚠️ 변경 사항이 아직 테스트 환경에서 원활히 작동하지 않습니다.{extra}\n"
              "아직 매니저에게 알리지 않았습니다. 계속 수정할까요('수정 필요'를 누른 뒤 설명) 아니면 취소할까요?",
    },
    "ops.give_up.extra_fix_failed": {
        "vi": " Em đã thử tự sửa nhưng vẫn chưa được.",
        "en": " I tried to fix it myself but it still didn't work.",
        "ko": " 제가 직접 수정해 봤지만 여전히 해결되지 않았습니다.",
    },
    "ops.btn.needs_fix": {"vi": "🔧 Cần sửa", "en": "🔧 Needs fix", "ko": "🔧 수정 필요"},
    "ops.btn.cancel": {"vi": "❌ Huỷ", "en": "❌ Cancel", "ko": "❌ 취소"},

    # ── cleanup: warns ──
    "ops.revert_failed": {
        "vi": "hoàn tác `{base}` thất bại — cần kiểm tra thủ công",
        "en": "reverting `{base}` failed — manual check needed",
        "ko": "`{base}` 되돌리기 실패 — 수동 확인이 필요합니다",
    },
}
