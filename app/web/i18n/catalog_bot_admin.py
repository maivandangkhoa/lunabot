"""Catalog dịch chatbot — admin_commands (lệnh quản trị). Xem app/web/i18n/__init__.py."""
from __future__ import annotations

TEXTS: dict[str, dict[str, str]] = {
    "admin.help": {
        "vi": (
            "🛠 Lệnh:\n"
            "/whoami — thông tin của anh/chị\n"
            "/ask <câu hỏi> — hỏi-đáp về dự án (chỉ đọc, không tạo yêu cầu)\n"
            "/clear — đóng yêu cầu đang mở, bắt đầu session mới\n"
            "/repos — liệt kê dự án (repo) của tenant\n"
            "/repo <tên|số> — chọn dự án để gửi yêu cầu\n"
            "/users — liệt kê user (admin)\n"
            "/invite <role> <tên> — tạo user + link (admin)\n"
            "/addrepo <owner/repo> <installation_id> [base] [prod] — thêm dự án (admin)\n"
            "/role <user_id> <role> — đổi vai trò (admin)\n"
            "/unlink <user_id> — gỡ liên kết, cấp token mới (admin)\n"
            "role ∈ employee|manager|admin"
        ),
        "en": (
            "🛠 Commands:\n"
            "/whoami — your info\n"
            "/ask <question> — Q&A about the project (read-only, no request created)\n"
            "/clear — close the open request, start a new session\n"
            "/repos — list the tenant's projects (repos)\n"
            "/repo <name|number> — pick a project to send requests to\n"
            "/users — list users (admin)\n"
            "/invite <role> <name> — create user + link (admin)\n"
            "/addrepo <owner/repo> <installation_id> [base] [prod] — add a project (admin)\n"
            "/role <user_id> <role> — change role (admin)\n"
            "/unlink <user_id> — unlink, issue a new token (admin)\n"
            "role ∈ employee|manager|admin"
        ),
        "ko": (
            "🛠 명령어:\n"
            "/whoami — 내 정보\n"
            "/ask <질문> — 프로젝트 질의응답 (읽기 전용, 요청 생성 안 함)\n"
            "/clear — 열린 요청을 닫고 새 세션 시작\n"
            "/repos — 테넌트의 프로젝트(repo) 목록\n"
            "/repo <이름|번호> — 요청을 보낼 프로젝트 선택\n"
            "/users — 사용자 목록 (admin)\n"
            "/invite <role> <이름> — 사용자 생성 + 링크 (admin)\n"
            "/addrepo <owner/repo> <installation_id> [base] [prod] — 프로젝트 추가 (admin)\n"
            "/role <user_id> <role> — 역할 변경 (admin)\n"
            "/unlink <user_id> — 링크 해제, 새 토큰 발급 (admin)\n"
            "role ∈ employee|manager|admin"
        ),
    },
    "admin.whoami": {
        "vi": "id={id} · vai trò={role} · tenant={tenant} · {name}",
        "en": "id={id} · role={role} · tenant={tenant} · {name}",
        "ko": "id={id} · 역할={role} · tenant={tenant} · {name}",
    },
    "admin.unknown_command": {
        "vi": "Lệnh không rõ.\n\n{help}",
        "en": "Unknown command.\n\n{help}",
        "ko": "알 수 없는 명령어입니다.\n\n{help}",
    },
    "admin.only_admin": {
        "vi": "⛔ Chỉ admin dùng được lệnh này. (Xem /whoami)",
        "en": "⛔ Only admins can use this command. (See /whoami)",
        "ko": "⛔ 이 명령어는 admin만 사용할 수 있습니다. (/whoami 참고)",
    },
    "admin.repos_empty": {
        "vi": "Tenant chưa có dự án nào. Admin thêm bằng /addrepo.",
        "en": "This tenant has no projects yet. An admin can add one with /addrepo.",
        "ko": "이 테넌트에는 아직 프로젝트가 없는 상태입니다. admin이 /addrepo로 추가할 수 있습니다.",
    },
    "admin.repos_list": {
        "vi": "📦 Dự án:\n{body}\n\nChọn: /repo <số hoặc tên>",
        "en": "📦 Projects:\n{body}\n\nPick: /repo <number or name>",
        "ko": "📦 프로젝트:\n{body}\n\n선택: /repo <번호 또는 이름>",
    },
    "admin.repo_usage": {
        "vi": "Hướng dẫn sử dụng: /repo <số hoặc tên>. Xem danh sách: /repos",
        "en": "How to use: /repo <number or name>. See the list: /repos",
        "ko": "이용 방법: /repo <번호 또는 이름>. 목록 보기: /repos",
    },
    "admin.repo_not_found": {
        "vi": "Hiện chưa tìm thấy dự án '{key}'. Xem /repos.",
        "en": "Project '{key}' not found. See /repos.",
        "ko": "프로젝트 '{key}'를 찾을 수 없는 상태입니다. /repos를 확인하세요.",
    },
    "admin.repo_chosen": {
        "vi": "✅ Đã chọn dự án: {name}. Gửi yêu cầu bảo trì để bắt đầu.",
        "en": "✅ Project selected: {name}. Send a maintenance request to get started.",
        "ko": "✅ 프로젝트 선택됨: {name}. 유지보수 요청을 보내 시작하세요.",
    },
    "admin.addrepo_usage": {
        "vi": "Hướng dẫn sử dụng: /addrepo <owner/repo> <installation_id> [base_branch] [prod_branch]",
        "en": "How to use: /addrepo <owner/repo> <installation_id> [base_branch] [prod_branch]",
        "ko": "이용 방법: /addrepo <owner/repo> <installation_id> [base_branch] [prod_branch]",
    },
    "admin.repo_exists": {
        "vi": "Dự án {name} đã tồn tại trong tenant.",
        "en": "Project {name} already exists in this tenant.",
        "ko": "프로젝트 {name}는 이 테넌트에 이미 존재합니다.",
    },
    "admin.repo_added": {
        "vi": (
            "✅ Đã thêm dự án #{id} {name} ({base}→{prod}).\n"
            "Nhắc cài GitHub App lên repo + repo có 2 nhánh đó. User chọn bằng /repo."
        ),
        "en": (
            "✅ Added project #{id} {name} ({base}→{prod}).\n"
            "Remember to install the GitHub App on the repo + make sure the repo has those 2 branches. Users pick it with /repo."
        ),
        "ko": (
            "✅ 프로젝트 #{id} {name} ({base}→{prod}) 추가됨.\n"
            "repo에 GitHub App을 설치하고 해당 2개 브랜치가 있는지 확인하세요. 사용자는 /repo로 선택합니다."
        ),
    },
    "admin.users_header": {
        "vi": "👥 Users:\n{body}",
        "en": "👥 Users:\n{body}",
        "ko": "👥 사용자:\n{body}",
    },
    "admin.users_empty": {
        "vi": "Hiện chưa có user.",
        "en": "There are no users yet.",
        "ko": "아직 사용자가 없는 상태입니다.",
    },
    "admin.user_linked": {
        "vi": "đã link",
        "en": "linked",
        "ko": "연결됨",
    },
    "admin.user_token": {
        "vi": "token: {token}",
        "en": "token: {token}",
        "ko": "token: {token}",
    },
    "admin.invite_usage": {
        "vi": "Hướng dẫn sử dụng: /invite <employee|manager|admin> <tên>",
        "en": "How to use: /invite <employee|manager|admin> <name>",
        "ko": "이용 방법: /invite <employee|manager|admin> <이름>",
    },
    "admin.invite_created": {
        "vi": "✅ Tạo {role} '{name}' (#{id}).\nGửi họ: /start {token}",
        "en": "✅ Created {role} '{name}' (#{id}).\nSend them: /start {token}",
        "ko": "✅ {role} '{name}' (#{id}) 생성됨.\n다음을 전달하세요: /start {token}",
    },
    "admin.role_usage": {
        "vi": "Hướng dẫn sử dụng: /role <user_id> <employee|manager|admin>",
        "en": "How to use: /role <user_id> <employee|manager|admin>",
        "ko": "이용 방법: /role <user_id> <employee|manager|admin>",
    },
    "admin.user_not_in_tenant": {
        "vi": "Hiện chưa tìm thấy user trong tenant của anh/chị.",
        "en": "There are no such user in your tenant.",
        "ko": "당신의 테넌트에 해당 사용자가 없는 상태입니다.",
    },
    "admin.role_changed": {
        "vi": "✅ #{id} '{name}' → {role}",
        "en": "✅ #{id} '{name}' → {role}",
        "ko": "✅ #{id} '{name}' → {role}",
    },
    "admin.unlink_usage": {
        "vi": "Hướng dẫn sử dụng: /unlink <user_id>",
        "en": "How to use: /unlink <user_id>",
        "ko": "이용 방법: /unlink <user_id>",
    },
    "admin.unlinked": {
        "vi": "✅ Đã gỡ liên kết #{id}. Token mới: /start {token}",
        "en": "✅ Unlinked #{id}. New token: /start {token}",
        "ko": "✅ #{id} 링크 해제됨. 새 토큰: /start {token}",
    },
}
