"""Catalog dịch chatbot — post_deploy + cleanup (deploy-gate, dọn nhánh). Xem app/web/i18n/__init__.py."""
from __future__ import annotations

TEXTS: dict[str, dict[str, str]] = {
    # ── post_deploy: notify_managers — gói duyệt 10.x dựng ở app/report.py:manager_packet ──
    "ops.btn.approve_merge": {"vi": "✅ Cho merge", "en": "✅ Approve merge", "ko": "✅ 머지 승인"},
    "ops.btn.reject": {"vi": "❌ Từ chối", "en": "❌ Reject", "ko": "❌ 거절"},

    # ── post_deploy: enter_await_manager ──
    "ops.await_manager.default": {
        "vi": "✅ Đã merge vào `{base}`. Đang chờ manager duyệt.",
        "en": "✅ Merged into `{base}`. Waiting for manager approval.",
        "ko": "✅ `{base}`에 머지했습니다. 매니저 승인을 기다리는 중입니다.",
    },

    # ── post_deploy: _run_verify_loop ──
    "ops.deploy_ok": {
        "vi": "✅ Em đã deploy lên môi trường dev và test thấy hoạt động ổn rồi. "
              "Đang chờ manager duyệt.",
        "en": "✅ I deployed to the dev environment and tested it working fine. "
              "Waiting for manager approval.",
        "ko": "✅ dev 환경에 배포하고 테스트해 보니 정상 작동했습니다. "
              "매니저 승인을 기다리는 중입니다.",
    },
    "ops.deploy_ok_link": {
        "vi": "✅ Em đã deploy lên môi trường dev và test thấy hoạt động ổn rồi.\n"
              "Anh/chị xem thử tại: {url}\nNếu đúng ý rồi, em đang chờ manager duyệt để triển khai chính thức.",
        "en": "✅ I deployed to the dev environment and tested it working fine.\n"
              "You can check it here: {url}\nIf it looks right, I'm now waiting for manager approval to go live.",
        "ko": "✅ dev 환경에 배포하고 테스트해 보니 정상 작동했습니다.\n"
              "여기에서 확인해 보세요: {url}\n괜찮으시면 정식 배포를 위해 매니저 승인을 기다리는 중입니다.",
    },
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
