"""Catalog dịch chatbot — orchestrator (FSM lifecycle). Xem app/web/i18n/__init__.py."""
from __future__ import annotations

TEXTS: dict[str, dict[str, str]] = {
    # ── friendly_repo_error ──
    "orch.repo_err.no_base_branch": {
        "vi": (
            "🌿 Repo {repo} chưa có nhánh `{base}` để em làm việc.\n\n"
            "Quy trình của em: em commit lên nhánh `{base}` cho anh/chị duyệt thử, "
            "rồi mới merge vào `{prod}`. Vì vậy repo cần sẵn 2 nhánh này.\n\n"
            "Cách tạo nhanh: mở repo trên GitHub → bấm ô chọn nhánh → gõ `{base}` → "
            'chọn "Create branch {base} from {prod}".\n\n'
            "{retry_hint}"
        ),
        "en": (
            "🌿 Repo {repo} does not have a `{base}` branch for me to work on.\n\n"
            "My flow: I commit to the `{base}` branch for you to review, "
            "then merge into `{prod}`. So the repo needs both of these branches.\n\n"
            "Quick way to create it: open the repo on GitHub → click the branch selector → type `{base}` → "
            'pick "Create branch {base} from {prod}".\n\n'
            "{retry_hint}"
        ),
        "ko": (
            "🌿 {repo} 저장소에 제가 작업할 `{base}` 브랜치가 없는 상태입니다.\n\n"
            "제 절차: 먼저 `{base}` 브랜치에 커밋하여 검토받은 뒤 `{prod}`에 병합합니다. "
            "그래서 저장소에 이 두 브랜치가 모두 있어야 합니다.\n\n"
            "빠른 생성 방법: GitHub에서 저장소 열기 → 브랜치 선택 상자 클릭 → `{base}` 입력 → "
            '"Create branch {base} from {prod}" 선택.\n\n'
            "{retry_hint}"
        ),
    },
    "orch.repo_err.no_access": {
        "vi": (
            "🔒 Em chưa truy cập được repo {repo} — có thể GitHub App "
            "chưa được cài (hoặc thiếu quyền) cho repo này.\n\n"
            "Anh/chị kiểm tra lại phần cài đặt GitHub App rồi {retry_hint_lower}"
        ),
        "en": (
            "🔒 I cannot access repo {repo} yet — the GitHub App "
            "may not be installed (or lacks permission) for this repo.\n\n"
            "Please check the GitHub App settings, then {retry_hint_lower}"
        ),
        "ko": (
            "🔒 아직 {repo} 저장소에 접근할 수 없습니다 — 이 저장소에 GitHub App이 "
            "설치되지 않았거나 권한이 없을 수 있습니다.\n\n"
            "GitHub App 설정을 확인한 뒤 {retry_hint_lower}"
        ),
    },
    "orch.repo_err.not_found": {
        "vi": (
            "❓ Em không tìm thấy repo {repo}. Anh/chị kiểm tra lại tên repo "
            "và quyền cài đặt GitHub App rồi {retry_hint_lower}"
        ),
        "en": (
            "❓ I could not find repo {repo}. Please double-check the repo name "
            "and the GitHub App install permission, then {retry_hint_lower}"
        ),
        "ko": (
            "❓ {repo} 저장소를 찾을 수 없는 상태입니다. 저장소 이름과 "
            "GitHub App 설치 권한을 확인한 뒤 {retry_hint_lower}"
        ),
    },
    "orch.repo_err.generic": {
        "vi": (
            "⚠️ Em chưa chuẩn bị được repo {repo} để phân tích.\n"
            "Chi tiết: {detail}\n\n{retry_hint}"
        ),
        "en": (
            "⚠️ I could not prepare repo {repo} for analysis.\n"
            "Details: {detail}\n\n{retry_hint}"
        ),
        "ko": (
            "⚠️ 분석을 위해 {repo} 저장소를 준비하지 못했습니다.\n"
            "세부 정보: {detail}\n\n{retry_hint}"
        ),
    },

    # ── retry hints (passed into friendly_repo_error) ──
    "orch.retry_hint.ask": {
        "vi": "Sửa xong rồi gọi /ask lại nhé.",
        "en": "Once fixed, call /ask again.",
        "ko": "수정 후 /ask를 다시 호출하세요.",
    },
    "orch.retry_hint.analyze": {
        "vi": 'Sửa xong rồi nhắn em "chạy lại" để em tiếp tục nhé.',
        "en": 'Once fixed, message me "chạy lại" and I will continue.',
        "ko": '수정 후 "chạy lại"라고 메시지를 보내시면 계속 진행하겠습니다.',
    },

    # ── handle_callback ──
    "orch.not_owner": {
        "vi": "⚠️ Yêu cầu #{id} không phải của anh/chị.",
        "en": "⚠️ Request #{id} is not yours.",
        "ko": "⚠️ #{id} 요청은 당신의 것이 아닙니다.",
    },
    "orch.already_handled": {
        "vi": "ℹ️ Yêu cầu #{id} đã được xử lý.",
        "en": "ℹ️ Request #{id} has already been handled.",
        "ko": "ℹ️ #{id} 요청은 이미 처리되었습니다.",
    },
    "orch.plan_rejected": {
        "vi": "Kế hoạch bị từ chối. Anh/chị muốn điều chỉnh gì? (trả lời tin này)",
        "en": "The plan was rejected. What would you like to adjust? (reply to this message)",
        "ko": "계획이 거부되었습니다. 무엇을 조정하시겠습니까? (이 메시지에 답장하세요)",
    },
    "orch.verify_fix_prompt": {
        "vi": "🔧 Cần sửa gì? Trả lời tin này để bot sửa tiếp.",
        "en": "🔧 What needs fixing? Reply to this message and the bot will keep working.",
        "ko": "🔧 무엇을 수정해야 하나요? 이 메시지에 답장하시면 봇이 계속 작업합니다.",
    },
    "orch.cancelled": {
        "vi": "❌ Đã huỷ yêu cầu.",
        "en": "❌ Request cancelled.",
        "ko": "❌ 요청이 취소되었습니다.",
    },
    "orch.cleanup_warn": {
        "vi": "\n⚠️ Dọn dẹp: {warns}",
        "en": "\n⚠️ Cleanup: {warns}",
        "ko": "\n⚠️ 정리: {warns}",
    },

    # ── clear_open_request ──
    "orch.no_open_request": {
        "vi": "✨ Không có yêu cầu đang mở. Gửi yêu cầu mới để bắt đầu.",
        "en": "✨ No open request. Send a new request to get started.",
        "ko": "✨ 열려 있는 요청이 없는 상태입니다. 새 요청을 보내 시작하세요.",
    },
    "orch.cleared": {
        "vi": "🧹 Đã đóng yêu cầu #{id}. Gửi yêu cầu mới để bắt đầu session mới.",
        "en": "🧹 Closed request #{id}. Send a new request to start a new session.",
        "ko": "🧹 #{id} 요청을 닫았습니다. 새 요청을 보내 새 세션을 시작하세요.",
    },

    # ── ask ──
    "orch.ask_failed": {
        "vi": "⚠️ Chưa trả lời được, thử lại sau nhé:\n{detail}",
        "en": "⚠️ Could not answer, please try again later:\n{detail}",
        "ko": "⚠️ 답변할 수 없는 상태입니다. 나중에 다시 시도하세요:\n{detail}",
    },
    "orch.ask_empty": {
        "vi": "(không có nội dung)",
        "en": "(no content)",
        "ko": "(내용 없음)",
    },

    # ── _analyze ──
    "orch.received": {
        "vi": "📥 Em đã nhận yêu cầu, chờ em kiểm tra rồi báo lại nhé…",
        "en": "📥 I've received your request, let me check and get back to you…",
        "ko": "📥 요청을 받았습니다. 확인 후 다시 알려드리겠습니다…",
    },
    "orch.analyze_failed": {
        "vi": (
            "⚠️ Em gặp trục trặc khi phân tích, chưa xong được. "
            'Anh/chị nhắn em "chạy lại" để em thử lại nhé.'
        ),
        "en": (
            "⚠️ I hit a problem during analysis and couldn't finish. "
            'Please message me "chạy lại" so I can try again.'
        ),
        "ko": (
            "⚠️ 분석 중 문제가 발생하여 완료하지 못했습니다. "
            '"chạy lại"라고 메시지를 보내시면 다시 시도하겠습니다.'
        ),
    },
    "orch.relay_then_clarify": {
        "vi": (
            "{result}\n\n———\nAnh/chị muốn em *thực hiện thay đổi gì*? "
            "Trả lời cụ thể để em lập kế hoạch."
        ),
        "en": (
            "{result}\n\n———\nWhat *change* would you like me to make? "
            "Reply with specifics so I can draft a plan."
        ),
        "ko": (
            "{result}\n\n———\n어떤 *변경*을 원하십니까? "
            "구체적으로 답해 주시면 계획을 세우겠습니다."
        ),
    },
    "orch.no_signal": {
        "vi": "⚠️ Em chưa xử lý xong yêu cầu này. Anh/chị thử mô tả lại rõ hơn giúp em nhé.",
        "en": "⚠️ I couldn't complete this request. Please try describing it again more clearly.",
        "ko": "⚠️ 이 요청을 완료하지 못했습니다. 좀 더 명확하게 다시 설명해 주세요.",
    },
    "orch.clarify_body": {
        "vi": "{body}\n\n(trả lời tin này)",
        "en": "{body}\n\n(reply to this message)",
        "ko": "{body}\n\n(이 메시지에 답장하세요)",
    },
    "orch.clarify_question": {
        "vi": "❓ {q}",
        "en": "❓ {q}",
        "ko": "❓ {q}",
    },
    "orch.clarify_with_answer": {
        "vi": "{answer}\n\n———\n{qs}",
        "en": "{answer}\n\n———\n{qs}",
        "ko": "{answer}\n\n———\n{qs}",
    },
    "orch.plan_text": {
        "vi": (
            "📋 Kế hoạch (risk: {risk}):\n{summary}\n\n{steps}"
            "\n\n(Bấm nút, hoặc trả lời: ok để duyệt · sửa · huỷ)"
        ),
        "en": (
            "📋 Plan (risk: {risk}):\n{summary}\n\n{steps}"
            "\n\n(Tap a button, or reply: ok to approve · sửa · huỷ)"
        ),
        "ko": (
            "📋 계획 (risk: {risk}):\n{summary}\n\n{steps}"
            "\n\n(버튼을 누르거나, 답장하세요: 승인하려면 ok · sửa · huỷ)"
        ),
    },
    "orch.btn.confirm": {"vi": "✅ Confirm", "en": "✅ Confirm", "ko": "✅ Confirm"},
    "orch.btn.edit": {"vi": "✏️ Sửa", "en": "✏️ Edit", "ko": "✏️ 수정"},
    "orch.btn.cancel": {"vi": "❌ Huỷ", "en": "❌ Cancel", "ko": "❌ 취소"},

    # ── _execute ──
    "orch.executing": {
        "vi": "🛠 Em bắt đầu thực hiện thay đổi + tạo PR, xong em báo lại nhé…",
        "en": "🛠 I'm starting the changes + creating the PR, I'll report back when done…",
        "ko": "🛠 변경 작업과 PR 생성을 시작합니다. 완료되면 알려드리겠습니다…",
    },
    "orch.prepare_repo_error": {
        "vi": "⚠️ Em chưa chuẩn bị được nơi làm việc cho yêu cầu này. "
              "Anh/chị bấm Confirm để em thử lại nhé.",
        "en": "⚠️ I couldn't set up the workspace for this request. "
              "Tap Confirm so I can try again.",
        "ko": "⚠️ 이 요청의 작업 공간을 준비하지 못했습니다. "
              "Confirm을 눌러 주시면 다시 시도하겠습니다.",
    },
    "orch.execute_failed": {
        "vi": "⚠️ Em gặp trục trặc khi thực hiện thay đổi, chưa hoàn tất được. "
              "Anh/chị bấm Confirm để em thử lại nhé.",
        "en": "⚠️ I ran into a problem making the changes and couldn't finish. "
              "Tap Confirm so I can try again.",
        "ko": "⚠️ 변경 작업 중 문제가 발생하여 완료하지 못했습니다. "
              "Confirm을 눌러 주시면 다시 시도하겠습니다.",
    },
    "orch.push_pr_error": {
        "vi": "⚠️ Em gặp trục trặc khi lưu lại thay đổi. "
              "Anh/chị bấm Confirm để em thử lại nhé.",
        "en": "⚠️ I hit a problem saving the changes. "
              "Tap Confirm so I can try again.",
        "ko": "⚠️ 변경 사항을 저장하는 중 문제가 발생했습니다. "
              "Confirm을 눌러 주시면 다시 시도하겠습니다.",
    },
    # ── _verify_buttons ──
    "orch.btn.verify_ok": {"vi": "✅ Đạt", "en": "✅ Good", "ko": "✅ 통과"},
    "orch.btn.verify_fix": {"vi": "🔧 Cần sửa", "en": "🔧 Needs fix", "ko": "🔧 수정 필요"},

    # ── _merge_to_dev ──
    "orch.dev_holder_wait": {
        "vi": (
            "⏳ Yêu cầu #{holder_id} đang chờ manager duyệt merge `main`. Em xử lý "
            "#{id} sau khi #{holder_id} xong — anh/chị bấm **✅ Đạt** lại lúc đó nhé."
        ),
        "en": (
            "⏳ Request #{holder_id} is waiting for a manager to approve the `main` merge. I'll handle "
            "#{id} after #{holder_id} is done — please tap **✅ Đạt** again at that point."
        ),
        "ko": (
            "⏳ #{holder_id} 요청이 `main` 병합에 대한 관리자 승인을 기다리고 있습니다. #{holder_id}가 "
            "끝난 뒤 #{id}를 처리하겠습니다 — 그때 **✅ Đạt**를 다시 눌러 주세요."
        ),
    },
    "orch.merge_dev_error": {
        "vi": "⚠️ Em chưa đưa được thay đổi lên môi trường thử nghiệm. Anh/chị thử lại sau giúp em nhé.",
        "en": "⚠️ I couldn't move the change to the test environment. Please try again shortly.",
        "ko": "⚠️ 변경 사항을 테스트 환경에 반영하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    },
    "orch.merged_dev_waiting_deploy": {
        "vi": (
            "✅ Đã merge vào `{base}`. Em đang chờ build & deploy lên "
            "môi trường dev rồi kiểm thử lại, xong em báo nhé…"
        ),
        "en": (
            "✅ Merged into `{base}`. I'm waiting for the build & deploy to the "
            "dev environment, then I'll re-test and report back…"
        ),
        "ko": (
            "✅ `{base}`에 병합했습니다. dev 환경으로 빌드 및 배포를 기다린 뒤 "
            "다시 테스트하고 알려드리겠습니다…"
        ),
    },

    # ── _merge_to_main / _manager_reject ──
    "orch.only_manager": {
        "vi": "⛔ Chỉ manager được duyệt merge.",
        "en": "⛔ Only a manager can approve the merge.",
        "ko": "⛔ 관리자만 병합을 승인할 수 있습니다.",
    },
    "orch.merge_main_error": {
        "vi": "⚠️ Em chưa triển khai được lên `{prod}`. Vui lòng kiểm tra lại và thử duyệt lại sau.",
        "en": "⚠️ I couldn't deploy to `{prod}`. Please check and try approving again shortly.",
        "ko": "⚠️ `{prod}`에 배포하지 못했습니다. 확인 후 잠시 뒤 다시 승인해 주세요.",
    },
    "orch.merged_main_closed": {
        "vi": "🎉 Yêu cầu #{id} đã merge `{prod}` và đóng.",
        "en": "🎉 Request #{id} has been merged into `{prod}` and closed.",
        "ko": "🎉 #{id} 요청이 `{prod}`에 병합되고 닫혔습니다.",
    },
    "orch.manager_rejected": {
        "vi": (
            "❌ Manager từ chối merge yêu cầu #{id}. "
            "Đã hoàn tác `{base}`, đóng PR và xoá nhánh."
        ),
        "en": (
            "❌ The manager rejected the merge for request #{id}. "
            "Reverted `{base}`, closed the PR and deleted the branch."
        ),
        "ko": (
            "❌ 관리자가 #{id} 요청의 병합을 거부했습니다. "
            "`{base}`를 되돌리고 PR을 닫고 브랜치를 삭제했습니다."
        ),
    },
    "orch.cleanup_partial_warn": {
        "vi": "\n⚠️ Dọn dẹp chưa trọn: {warns}",
        "en": "\n⚠️ Cleanup incomplete: {warns}",
        "ko": "\n⚠️ 정리가 완료되지 않음: {warns}",
    },
}
