"""Catalog dịch chatbot — dispatcher (routing), recovery, reconcile. Xem app/web/i18n/__init__.py.

Mỗi key: {"vi": ..., "en": ..., "ko": ...}. Giá trị "vi" GIỮ NGUYÊN văn bản gốc (test khớp
substring tiếng Việt). Brand/tech-term (luna, repo, PR, dev/main, /start, /repo…) giữ nguyên.
"""
from __future__ import annotations

TEXTS: dict[str, dict[str, str]] = {
    # ── Dispatcher: trạng thái/khoá ──
    "disp.busy": {
        "vi": "⏳ Em đang xử lý việc trước, xong em báo ngay. Gửi lại nội dung này sau khi em xong nhé.",
        "en": "⏳ I'm still handling your previous request — I'll report back as soon as it's done. Please resend this once I've finished.",
        "ko": "⏳ 이전 요청을 아직 처리 중입니다 — 끝나는 대로 알려드릴게요. 완료된 후 이 내용을 다시 보내주세요.",
    },
    "disp.thread_busy": {
        "vi": "🧵 Thread này đang xử lý yêu cầu #{id}. Mở thread mới (hoặc DM bot) để gửi yêu cầu khác nhé.",
        "en": "🧵 This thread is handling request #{id}. Open a new thread (or DM the bot) to send another request.",
        "ko": "🧵 이 스레드는 요청 #{id}을(를) 처리 중입니다. 다른 요청은 새 스레드를 열거나 봇에게 DM으로 보내주세요.",
    },
    "disp.plan_pending": {
        "vi": "📋 Yêu cầu #{id} đang chờ duyệt kế hoạch. Trả lời: ok · sửa · huỷ.",
        "en": "📋 Request #{id} is awaiting plan approval. Reply: ok · edit · cancel.",
        "ko": "📋 요청 #{id}은(는) 계획 승인을 기다리고 있습니다. 답장: ok · 수정 · 취소.",
    },
    "disp.req_processing": {
        "vi": "⏳ Em đang xử lý yêu cầu #{id} ({status}). Chờ em xong rồi gửi yêu cầu mới (thread mới) nhé.",
        "en": "⏳ I'm working on request #{id} ({status}). Please wait until I'm done before sending a new request (in a new thread).",
        "ko": "⏳ 요청 #{id}({status})을(를) 처리 중입니다. 끝날 때까지 기다렸다가 새 요청은 새 스레드로 보내주세요.",
    },
    # ── Dispatcher: liên kết / khởi đầu ──
    "disp.start_dm_only": {
        "vi": "🔒 Hãy nhắn riêng (DM) cho bot để liên kết: /start <token>.",
        "en": "🔒 Please DM the bot to link your account: /start <token>.",
        "ko": "🔒 계정을 연결하려면 봇에게 DM으로 보내주세요: /start <token>.",
    },
    "disp.not_linked": {
        "vi": "Anh/chị chưa liên kết tài khoản. Nhắn riêng bot: /start <token> (admin cấp).",
        "en": "Your account isn't linked yet. DM the bot: /start <token> (provided by your admin).",
        "ko": "계정이 아직 연결되지 않았습니다. 봇에게 DM으로 보내세요: /start <token> (관리자 제공).",
    },
    "disp.callback_not_yours": {
        "vi": "Nút này thuộc yêu cầu của một nhóm/không gian làm việc khác nên anh/chị "
              "không thao tác được. Người thuộc đúng workspace của yêu cầu mới bấm được.",
        "en": "This button belongs to a request in a different workspace, so you can't act "
              "on it. Only a member of that request's workspace can use it.",
        "ko": "이 버튼은 다른 워크스페이스의 요청에 속하므로 사용할 수 없습니다. "
              "해당 요청의 워크스페이스 구성원만 사용할 수 있습니다.",
    },
    "disp.admin_dm_only": {
        "vi": "🔒 Lệnh quản trị chỉ dùng khi nhắn riêng (DM) cho bot.",
        "en": "🔒 Admin commands only work in a direct message (DM) to the bot.",
        "ko": "🔒 관리자 명령은 봇에게 보내는 DM에서만 작동합니다.",
    },
    "disp.start_welcome": {
        "vi": "Chào mừng đến luna 🌙\nĐể liên kết: /start <token> (admin cấp cho anh/chị).",
        "en": "Welcome to luna 🌙\nTo link your account: /start <token> (provided by your admin).",
        "ko": "luna에 오신 것을 환영합니다 🌙\n계정 연결: /start <token> (관리자가 제공).",
    },
    "disp.start_bad_token": {
        "vi": "❌ Token không hợp lệ hoặc đã dùng.",
        "en": "❌ Token is invalid or already used.",
        "ko": "❌ 토큰이 유효하지 않거나 이미 사용되었습니다.",
    },
    "disp.start_already_linked": {
        "vi": "Tài khoản này đã được liên kết rồi. Bạn có thể gửi yêu cầu luôn.",
        "en": "This account is already linked. You can send a request right away.",
        "ko": "이 계정은 이미 연결되어 있습니다. 바로 요청을 보낼 수 있습니다.",
    },
    "disp.start_linked": {
        "vi": "✅ Đã liên kết! Vai trò: {role}. Gửi yêu cầu bảo trì để bắt đầu.\n\n{help}",
        "en": "✅ Linked! Role: {role}. Send a maintenance request to get started.\n\n{help}",
        "ko": "✅ 연결되었습니다! 역할: {role}. 유지보수 요청을 보내 시작하세요.\n\n{help}",
    },
    # ── Dispatcher: chọn dự án / tạo yêu cầu ──
    "disp.no_repo": {
        "vi": "Tenant chưa có dự án nào. Admin thêm bằng /addrepo.",
        "en": "This tenant has no projects yet. An admin can add one with /addrepo.",
        "ko": "이 테넌트에는 아직 프로젝트가 없는 상태입니다. 관리자가 /addrepo로 추가할 수 있습니다.",
    },
    "disp.pick_repo": {
        "vi": "Tenant có nhiều dự án. Chọn trước bằng /repo <số|tên>:\n{lines}",
        "en": "This tenant has multiple projects. Pick one first with /repo <number|name>:\n{lines}",
        "ko": "이 테넌트에는 여러 프로젝트가 있습니다. 먼저 /repo <번호|이름>으로 선택하세요:\n{lines}",
    },
    "disp.title_image_only": {
        "vi": "(ảnh đính kèm)",
        "en": "(attached image)",
        "ko": "(첨부 이미지)",
    },
    # ── Dispatcher: hành động bằng text ──
    "disp.req_not_awaiting": {
        "vi": "⚠️ Yêu cầu #{id} không đang chờ '{word}' của anh/chị.",
        "en": "⚠️ Request #{id} is not awaiting '{word}' from you.",
        "ko": "⚠️ 요청 #{id}은(는) 당신의 '{word}'을(를) 기다리고 있지 않습니다.",
    },
    "disp.ambiguous": {
        "vi": "🤔 Anh/chị có nhiều việc đang chờ — chọn việc cần áp dụng:",
        "en": "🤔 You have several pending items — choose which one to apply:",
        "ko": "🤔 대기 중인 항목이 여러 개입니다 — 적용할 항목을 선택하세요:",
    },
    "disp.confirm_intent": {
        "vi": "🤔 Mình hiểu ý anh/chị về yêu cầu #{id}. Bấm nút bên dưới, hoặc trả lời '{word}' để xác nhận nhé.",
        "en": "🤔 I think I understand what you mean for request #{id}. Tap the button below, or reply '{word}' to confirm.",
        "ko": "🤔 요청 #{id}에 대한 의도를 이해한 것 같아요. 아래 버튼을 누르거나 '{word}'로 답하여 확인해 주세요.",
    },
    "disp.verb_confirm": {"vi": "✅ Duyệt KH #{id}", "en": "✅ Approve plan #{id}", "ko": "✅ 계획 승인 #{id}"},
    "disp.verb_reject": {"vi": "✏️ Sửa KH #{id}", "en": "✏️ Edit plan #{id}", "ko": "✏️ 계획 수정 #{id}"},
    "disp.verb_cancel": {"vi": "❌ Huỷ #{id}", "en": "❌ Cancel #{id}", "ko": "❌ 취소 #{id}"},
    "disp.verb_verify_ok": {"vi": "✅ Xác nhận đạt #{id}", "en": "✅ Confirm pass #{id}", "ko": "✅ 통과 확인 #{id}"},
    "disp.verb_mgr_approve": {"vi": "✅ Cho merge #{id}", "en": "✅ Allow merge #{id}", "ko": "✅ 병합 허용 #{id}"},
    "disp.verb_mgr_reject": {"vi": "❌ Từ chối merge #{id}", "en": "❌ Reject merge #{id}", "ko": "❌ 병합 거부 #{id}"},
    # ── Dispatcher: /ask ──
    "disp.ask_usage": {
        "vi": "Hướng dẫn sử dụng: /ask <câu hỏi về dự án>.\nVd: /ask dự án này dùng DB gì?",
        "en": "How to use: /ask <question about the project>.\nE.g.: /ask what database does this project use?",
        "ko": "이용 방법: /ask <프로젝트에 대한 질문>.\n예: /ask 이 프로젝트는 어떤 DB를 사용하나요?",
    },
    "disp.ask_pick_repo": {
        "vi": "Có nhiều dự án — chọn trước bằng /repo <số|tên> rồi /ask lại:\n{lines}",
        "en": "Multiple projects — pick one with /repo <number|name>, then /ask again:\n{lines}",
        "ko": "프로젝트가 여러 개입니다 — /repo <번호|이름>으로 선택한 뒤 다시 /ask 하세요:\n{lines}",
    },
    "disp.ask_thinking": {
        "vi": "🔎 Em xem rồi trả lời ngay…",
        "en": "🔎 Let me take a look and answer right away…",
        "ko": "🔎 살펴보고 바로 답변드리겠습니다…",
    },
    # ── Recovery (khởi động lại) ──
    "recovery.interrupted": {
        "vi": "⚠️ Hệ thống vừa khởi động lại nên yêu cầu #{rid} đang xử lý dở bị gián đoạn. "
              "Em đã đóng nó — anh/chị gửi lại yêu cầu để em làm lại nhé.",
        "en": "⚠️ The system just restarted, so request #{rid} that was in progress got interrupted. "
              "I've closed it — please resend the request and I'll redo it.",
        "ko": "⚠️ 시스템이 방금 재시작되어 진행 중이던 요청 #{rid}이(가) 중단되었습니다. "
              "해당 요청을 닫았습니다 — 다시 보내주시면 처음부터 다시 처리하겠습니다.",
    },
    # ── Reconcile (request mồ côi) ──
    "reconcile.released": {
        "vi": "🎉 Yêu cầu #{rid} '{title}' đã có trên `{prod}` (được release cùng đợt duyệt trước). "
              "Em đã đóng yêu cầu này để khỏi treo nhé.",
        "en": "🎉 Request #{rid} '{title}' is already on `{prod}` (released together with an earlier approval). "
              "I've closed this request so it doesn't hang.",
        "ko": "🎉 요청 #{rid} '{title}'은(는) 이미 `{prod}`에 있습니다 (이전 승인과 함께 릴리스됨). "
              "걸려 있지 않도록 이 요청을 닫았습니다.",
    },
    # ── Cancel stuck (request kẹt do định tuyến thread cũ) ──
    "cancel_stuck.cancelled": {
        "vi": "🧹 Yêu cầu #{rid} '{title}' đã bị huỷ do dọn dẹp hệ thống. "
              "Bạn mở thread mới (hoặc DM bot) để gửi lại yêu cầu nhé.",
        "en": "🧹 Request #{rid} '{title}' was cancelled during system cleanup. "
              "Please open a new thread (or DM the bot) to resend your request.",
        "ko": "🧹 요청 #{rid} '{title}'이(가) 시스템 정리 중 취소되었습니다. "
              "새 스레드를 열거나 봇에게 DM으로 요청을 다시 보내주세요.",
    },
    # ── Dev-mode (app/dev_runner.py) ──
    "dev.acted": {"vi": "Đã thực hiện", "en": "Did", "ko": "수행함"},
    "dev.empty": {
        "vi": "✅ Xong (không có gì để hiển thị).",
        "en": "✅ Done (nothing to show).",
        "ko": "✅ 완료 (표시할 내용 없음).",
    },
    "dev.no_repo": {
        "vi": "⚠️ Chưa xác định được repo. Dùng /repo để chọn repo trước nhé.",
        "en": "⚠️ No repo selected. Use /repo to pick a repo first.",
        "ko": "⚠️ 선택된 저장소가 없습니다. 먼저 /repo로 저장소를 선택하세요.",
    },
    "dev.cleared": {
        "vi": "🧹 Đã mở phiên mới (xoá ngữ cảnh trước).",
        "en": "🧹 Started a fresh session (previous context cleared).",
        "ko": "🧹 새 세션을 시작했습니다 (이전 컨텍스트 삭제됨).",
    },
    "dev.error": {
        "vi": "❌ Lỗi chuẩn bị repo: {err}",
        "en": "❌ Repo prep error: {err}",
        "ko": "❌ 저장소 준비 오류: {err}",
    },
}
