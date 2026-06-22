"""Catalog dịch chatbot — post_deploy + cleanup (deploy-gate, dọn nhánh). Xem app/web/i18n/__init__.py."""
from __future__ import annotations

TEXTS: dict[str, dict[str, str]] = {
    # ── post_deploy: notify_managers ──
    "ops.notify_managers": {
        "vi": "🔔 Yêu cầu #{id} '{title}' đã sẵn sàng merge `{prod}`.\nPR: {pr}"
              "\n\n(Bấm nút, hoặc trả lời: ok để duyệt · từ chối)",
        "en": "🔔 Request #{id} '{title}' is ready to merge into `{prod}`.\nPR: {pr}"
              "\n\n(Tap a button, or reply: ok to approve · reject)",
        "ko": "🔔 요청 #{id} '{title}'이(가) `{prod}` 머지 준비가 되었습니다.\nPR: {pr}"
              "\n\n(버튼을 누르거나 답장하세요: ok 승인 · reject 거절)",
    },
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
    "ops.deploy_retry": {
        "vi": "🔧 Deploy/kiểm thử dev chưa đạt ({reason}). Em tự sửa lại (lần {round})…",
        "en": "🔧 Dev deploy/test not passing yet ({reason}). I'll fix it myself (attempt {round})…",
        "ko": "🔧 dev 배포/테스트가 아직 통과하지 못했습니다 ({reason}). 제가 직접 수정합니다 ({round}번째)…",
    },

    # ── post_deploy: _give_up ──
    "ops.give_up": {
        "vi": "⚠️ Deploy lên dev chưa đạt: {reason}.{extra}{log_line}\n"
              "Em CHƯA báo manager. Anh/chị muốn em sửa tiếp (bấm 'Cần sửa' rồi mô tả) hay huỷ?",
        "en": "⚠️ Dev deploy not passing: {reason}.{extra}{log_line}\n"
              "I have NOT notified the manager. Do you want me to keep fixing (tap 'Needs fix' then describe) or cancel?",
        "ko": "⚠️ dev 배포가 통과하지 못했습니다: {reason}.{extra}{log_line}\n"
              "아직 매니저에게 알리지 않았습니다. 계속 수정할까요('수정 필요'를 누른 뒤 설명) 아니면 취소할까요?",
    },
    "ops.give_up.extra_fix_failed": {
        "vi": " Em đã thử tự sửa nhưng vẫn chưa được.",
        "en": " I tried to fix it myself but it still didn't work.",
        "ko": " 제가 직접 수정해 봤지만 여전히 해결되지 않았습니다.",
    },
    "ops.give_up.log_line": {
        "vi": "\nLog: {url}",
        "en": "\nLog: {url}",
        "ko": "\nLog: {url}",
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
