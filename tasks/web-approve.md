# Web approval — Admin duyệt request trên giao diện web

## Mục tiêu
Trên trang `/requests`, cho **chủ workspace (đăng nhập GitHub OAuth)** duyệt/từ chối các
request đang ở `AWAIT_MANAGER` ngay trên web — tương đương manager bấm nút trong chat.

## Quyết định thiết kế (tối giản, không đụng FSM)
- **Uỷ quyền**: chủ tenant (`owner_github_id == session uid`). Không dùng platform_admins.
- **Tái dùng nguyên `orchestrator.handle_callback(req, approver, cb("mgr_approve"/"mgr_reject"))`** —
  KHÔNG sửa orchestrator/models/migration. Mọi side-effect (PR base→prod, merge, revert dev,
  đóng PR, xoá nhánh, ghi Approval, báo requester) đã nằm trong đường chat sẵn có.
- **Approver attribution**: tenant tạo qua wizard luôn có 1 User role=ADMIN (chủ tenant,
  `provisioning.py:127`). Web approve gán Approval cho user ADMIN/MANAGER đó (prefer ADMIN, nhỏ id
  nhất = chủ). Bỏ guard role vì `_merge_to_main` đã tự kiểm (ADMIN/MANAGER pass).
- **Adapter báo requester**: dựng best-effort theo kênh requester (telegram/zalo own qua
  bot_registry; shared/gchat/messenger từ settings). Bọc `_SafeAdapter` để send lỗi KHÔNG làm
  hỏng merge (DB đã commit) — chỉ log.
- **Đồng bộ trong POST**: merge nhanh; reject revert dev (clone+revert) vài giây — chấp nhận để
  redirect thấy status mới ngay.

## Files
1. `app/web/routes.py` — chuyển `_csrf` (HMAC theo uid) vào đây (team.py import lại); `requests()`
   truyền `csrf`; `_request_rows` thêm `id`.
2. `app/web/approvals.py` (MỚI, APIRouter) — `POST /requests/{rid}/approve|reject`. Auth owner +
   CSRF; tìm request thuộc tenant owner + status AWAIT_MANAGER; tìm approver ADMIN/MANAGER; dựng
   orchestrator (github thật + git_ops + safe adapter) → `handle_callback`. Hook `_github/_git/
   _reply_adapter` để test monkeypatch.
3. `app/main.py` — include router.
4. `app/web/pages.py` — `_req_row(r, csrf=None)`: nếu csrf + status await_manager → 2 form
   Approve/Reject (confirm dialog). `requests(user_name, rows, csrf)`.
5. `app/web/i18n/catalog_app.py` — `reqs.approve/reqs.reject/reqs.approve_confirm/reqs.reject_confirm/
   reqs.awaiting`.
6. `tests/test_web_approvals.py` — approve→MERGED_MAIN/CLOSED + Approval; reject→CANCELLED; auth/CSRF/
   ownership/ wrong-status no-op.

## Done khi
- pytest xanh toàn bộ (cũ + mới). Render /requests có nút cho row await_manager, không có cho row khác.
</content>
