"""Catalog dịch chatbot — branch_sync (phân kỳ prod↔base + gỡ xung đột merge release).

Xem app/web/i18n/__init__.py. Giọng NGHIỆP VỤ: với requester không nói "merge/conflict",
nói "thay đổi đưa lên trực tiếp / gộp / chồng chéo"; message cho manager được nêu tên file.
"""
from __future__ import annotations

TEXTS: dict[str, dict[str, str]] = {
    # ── Feature 1: phát hiện phân kỳ lúc nhận request (branch_sync.check_divergence_at_intake) ──
    "sync.diverged_ask": {
        "vi": "⚠️ Em thấy bản chạy thật (`{prod}`) có {n} thay đổi được đưa lên trực tiếp "
              "(không qua em), chưa có trong bản làm việc (`{base}`).\n"
              "Anh/chị có muốn em gộp các thay đổi đó vào trước khi làm yêu cầu này không? "
              "Nếu không, em vẫn làm bình thường trên bản hiện tại.",
        "en": "⚠️ I noticed the live version (`{prod}`) has {n} change(s) that were pushed "
              "directly (not through me) and aren't in the working copy (`{base}`) yet.\n"
              "Would you like me to bring those changes in before working on this request? "
              "If not, I'll proceed on the current copy as usual.",
        "ko": "⚠️ 운영 버전(`{prod}`)에 저를 거치지 않고 직접 반영된 변경 사항이 {n}건 있는데, "
              "아직 작업 버전(`{base}`)에는 없습니다.\n"
              "이 요청을 진행하기 전에 그 변경 사항을 먼저 합칠까요? "
              "아니라면 현재 버전에서 그대로 진행하겠습니다.",
    },
    "sync.btn.yes": {"vi": "✅ Gộp vào", "en": "✅ Bring them in", "ko": "✅ 합치기"},
    "sync.btn.no": {"vi": "⏭️ Cứ làm tiếp", "en": "⏭️ Just proceed", "ko": "⏭️ 그대로 진행"},
    "sync.done": {
        "vi": "✅ Đã cập nhật các thay đổi từ `{prod}` vào bản làm việc. Em tiếp tục xử lý yêu cầu.",
        "en": "✅ Brought the changes from `{prod}` into the working copy. Continuing with your request.",
        "ko": "✅ `{prod}`의 변경 사항을 작업 버전에 반영했습니다. 요청을 계속 진행합니다.",
    },
    "sync.declined": {
        "vi": "👌 Em tiếp tục trên bản hiện tại. Lưu ý: lúc đưa lên `{prod}` có thể cần xử lý chồng chéo.",
        "en": "👌 Continuing on the current copy. Note: overlapping changes may need sorting out when going live on `{prod}`.",
        "ko": "👌 현재 버전에서 계속 진행합니다. 참고: `{prod}`에 반영할 때 겹치는 부분을 정리해야 할 수 있습니다.",
    },
    "sync.failed": {
        "vi": "⚠️ Em chưa gộp tự động được các thay đổi từ `{prod}` — em vẫn tiếp tục yêu cầu trên bản hiện tại.",
        "en": "⚠️ I couldn't bring in the changes from `{prod}` automatically — continuing your request on the current copy.",
        "ko": "⚠️ `{prod}`의 변경 사항을 자동으로 합치지 못했습니다 — 현재 버전에서 요청을 계속 진행합니다.",
    },

    # ── Feature 2: xung đột khi merge release lên prod (branch_sync.ask_conflict_fix) ──
    "sync.conflict_ask": {
        "vi": "⚠️ Chưa đưa yêu cầu #{id} lên `{prod}` được: có người đã sửa trực tiếp trên "
              "`{prod}`, đụng đúng phần em vừa thay đổi.\n"
              "Anh/chị muốn em tự gộp hai thay đổi lại (giữ cả hai) rồi triển khai tiếp không?",
        "en": "⚠️ Couldn't deploy request #{id} to `{prod}`: someone changed `{prod}` directly, "
              "touching the same parts I just modified.\n"
              "Want me to combine both changes (keeping both) and then finish the deployment?",
        "ko": "⚠️ 요청 #{id}을(를) `{prod}`에 배포하지 못했습니다: 누군가 `{prod}`을(를) 직접 수정했는데, "
              "제가 방금 변경한 부분과 겹칩니다.\n"
              "두 변경 사항을 모두 유지하도록 합친 뒤 배포를 마무리할까요?",
    },
    "sync.btn.fix_conflict": {
        "vi": "🔧 Gộp & triển khai", "en": "🔧 Combine & deploy", "ko": "🔧 합치고 배포",
    },
    "sync.fixing": {
        "vi": "🔧 Em đang gộp hai thay đổi lại, xin chờ chút…",
        "en": "🔧 Combining the two changes now, one moment…",
        "ko": "🔧 두 변경 사항을 합치는 중입니다. 잠시만 기다려 주세요…",
    },
    "sync.fix_failed": {
        "vi": "⚠️ Em chưa tự gộp được — phần chồng chéo cần người xem. Anh/chị có thể thử lại, hoặc Từ chối để hoàn tác.",
        "en": "⚠️ I couldn't combine them automatically — the overlap needs a human look. You can retry, or Reject to roll back.",
        "ko": "⚠️ 자동으로 합치지 못했습니다 — 겹치는 부분은 사람이 확인해야 합니다. 다시 시도하거나, 거절하여 되돌릴 수 있습니다.",
    },
    "sync.fix_in_progress": {
        "vi": "⏳ Em đang xử lý phần chồng chéo cho #{id} rồi, xin chờ.",
        "en": "⏳ Already working on the overlap for #{id}, please wait.",
        "ko": "⏳ #{id}의 겹치는 부분을 이미 처리 중입니다. 잠시만 기다려 주세요.",
    },

    # ── dispatcher: label hành động cho disambiguation/echo ──
    "disp.verb_conflict_fix": {"vi": "gộp & triển khai", "en": "combine & deploy", "ko": "합치고 배포"},
}
