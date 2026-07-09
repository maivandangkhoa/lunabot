# Kế hoạch: Dev-Mode — "Claude Code extension qua chat" (per-tenant)

> Mở rộng Luna cho **developer**: khi tenant bật `dev_mode`, mọi tin nhắn đi **thẳng**
> vào Claude Code headless như một trợ lý coding agentic (giống VS Code extension, **trừ
> streaming**), toàn quyền — kể cả push `main`, nhưng **push main phải confirm**.
>
> **Chế độ thường (FSM) KHÔNG đổi.** Dev-mode nằm sau cờ, mặc định tắt, nhánh code tách biệt.

## Mục tiêu trải nghiệm
- Hội thoại **đa lượt, nhớ ngữ cảnh** (`--resume` per user+repo).
- Vòng lặp **agentic tự chạy** (đọc→sửa→chạy test→lặp) rồi trả lời — bản chất `claude -p`.
- **Toàn quyền** (`bypassPermissions`): Bash/Edit/Write tự do.
- **Recap hành động**: cuối lượt liệt kê "đã đọc/sửa file gì, chạy lệnh gì" (parse `stream-json`).
- **Cổng duy nhất**: trước khi push `main` → hỏi confirm; user "ok" thì Luna tự merge/push.
- Bỏ qua: streaming từng token, interrupt giữa chừng, xem diff trực quan (dùng recap text).

## Quyết định thiết kế (chốt)
- **Cờ bật**: `Tenant.settings_json["dev_mode"] = true` → **KHÔNG cần migration** (JSONB đã có).
  Admin bật/tắt qua `/admin` (giống chỗ ghim model per-tenant).
- **Phiên dev**: cần lưu `claude_session_id` per (user, repo) + trạng thái chờ-confirm-main.
  `User` không có cột JSONB → **bảng mới `dev_sessions`** (migration 0011).
- **Không sửa `orchestrator.py`**. Tái dùng `Orchestrator._merge_to_main` cho bước push main.
- **Không đi qua tầng từ khoá FSM** (`ok/sửa/huỷ`). Dev-mode là pipe thô; chỉ chặn 2 thứ:
  `/clear` (reset phiên) và cổng confirm-main.
- Vẫn qua **lock per-repo** (dùng lock user hiện có ở `handle_channel_update`) + đo **usage**.

## Các bước

### B1. Cờ dev_mode + admin toggle
- [ ] Helper `tenant_dev_mode(tenant) -> bool` đọc `settings_json.get("dev_mode")`.
- [ ] `/admin` (app/web): thêm toggle bật/tắt dev_mode cho từng tenant. Tái dùng pattern
      ghim model. Cập nhật `settings_json` (giữ nguyên các key khác).
- [ ] (tuỳ chọn) Lệnh chat `/devmode on|off` cho owner — hoãn nếu web đủ.

### B2. Bảng dev_sessions (migration 0011)
- [ ] Model `DevSession`: `id, user_id(FK), repo_id(FK), claude_session_id: str|None,
      pending_json: JSONB (state chờ confirm-main), updated_at`. UNIQUE(user_id, repo_id).
- [ ] Migration `alembic/…_0011_dev_sessions.py`.
- [ ] Helper get-or-create theo (user, active_repo).

### B3. Runner stream-json + recap  (app/dev_runner.py — file mới, ≤200 LOC)
- [ ] Thêm chế độ `stream-json` vào `claude_runner` HOẶC hàm riêng trong dev_runner:
      chạy `claude -p --output-format stream-json --verbose --permission-mode bypassPermissions
      --resume <sid>`, đọc stdout **theo dòng**, gom event `tool_use` (name + input tóm tắt)
      và block `result` cuối + `session_id`.
- [ ] Ghép **recap**: "🔧 Đã thực hiện: • Đọc X • Sửa Y • Chạy: Z" + "💬 <result>".
- [ ] Format qua `app/channels/formatting.py`, gửi `adapter.send()`.
- [ ] Lưu `session_id` mới vào `dev_sessions`. Đo `usage.record(...)`.
- [ ] Giữ pre-push hook chặn main khi `ensure_clone` (đã có `install_pre_push_hook`).

### B4. Nhánh rẽ dev-mode trong dispatcher
- [ ] Trong `_dispatch_inbound` (sau khi có `user`, trước đường FSM/Orchestrator):
      `if tenant_dev_mode(user.tenant): return await dev_chat(...)`.
- [ ] `/clear` trong dev-mode → xoá `claude_session_id` (mở phiên mới), không đụng FSM.
- [ ] `dev_chat`: chọn repo (`user.active_repo_id` hoặc tenant có đúng 1 repo), ensure clone,
      gọi runner B3.

### B5. Cổng confirm push-main
- [ ] Prompt system dev-mode: yêu cầu Claude **KHÔNG tự push main**; muốn deploy main thì
      dừng và nêu rõ ("sẵn sàng deploy lên main"). (Fallback: pre-push hook vẫn chặn.)
- [ ] Khi runner phát hiện tín hiệu cần-main (Claude nêu, hoặc `classify_push_error` bắt được
      hook chặn main) → set `dev_sessions.pending_json = {"await_main": true, "branch": …}`
      và hỏi user: "Đã xong trên dev. Deploy lên main? [ok / huỷ]".
- [ ] Tin kế tiếp: nếu `pending_json.await_main` và text ∈ `_W_CONFIRM` → gọi
      `Orchestrator._merge_to_main(...)` (idempotent); `_W_CANCEL` → xoá pending, báo huỷ.
- [ ] Sau merge: xoá pending, trả kết quả (tái dùng post_deploy nếu muốn chờ CI — tuỳ chọn).

### B6. Tests
- [ ] `tenant_dev_mode` đọc đúng cờ; tenant không bật → đi đường FSM (chế độ thường bất biến).
- [ ] dev_chat: một lượt gọi runner (mock), lưu session_id, gửi recap.
- [ ] parse stream-json → recap đúng (fixture nhiều event tool_use + result).
- [ ] confirm-main: pending set → "ok" gọi `_merge_to_main`; "huỷ" xoá pending; text khác
      không kích hoạt merge.
- [ ] Guard: dev-mode KHÔNG chạm Orchestrator FSM (không tạo Request).

## Rủi ro / lưu ý
- **Toàn quyền = chạy code khách tự do** → giữ non-root + timeout (nâng `dev_timeout_s` riêng
  vì task agentic dài hơn one-shot). Chỉ bật cho tenant tin cậy.
- **Subprocess không treo chờ người**: confirm-main xảy ra **giữa 2 lượt** (Claude dừng, hỏi,
  lượt sau mới merge) — KHÔNG block subprocess như `--permission-prompt-tool`.
- **stream-json**: cần `--verbose`; xử lý dòng lỗi/không-JSON an toàn (fallback về text).
- **Không migration cho cờ** (dùng settings_json); chỉ 1 migration cho `dev_sessions`.

## Định nghĩa "done"
- Tenant bật dev_mode: chat "sửa bug X, chạy test" → Claude tự làm, trả recap + trả lời;
  "deploy lên main" → bot hỏi confirm → "ok" → merge main. Tenant KHÔNG bật: y hệt hôm nay.
