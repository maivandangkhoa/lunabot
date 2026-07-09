# Kế hoạch: Dev-Mode — "Claude Code extension qua chat" (per-tenant)

> Mở rộng Luna cho **developer**: khi tenant bật `dev_mode`, mọi tin nhắn đi **thẳng**
> vào Claude Code headless như một trợ lý coding agentic (giống Claude Code client, **trừ
> streaming**), **toàn quyền như trên repo của chính mình**: làm thẳng trên nhánh chính,
> tự commit & push nhánh chính; tự tạo/push nhánh riêng khi user yêu cầu.
>
> **Cập nhật 2026-07-09:** bỏ mô hình `dev`→confirm→`main`. Nay bot **tự do** (không cổng
> confirm-deploy, không pre-push hook chặn) — xem mục "Thay đổi 2026-07-09" cuối file.
>
> **Chế độ thường (FSM) KHÔNG đổi.** Dev-mode nằm sau cờ, mặc định tắt.

## Mục tiêu trải nghiệm
- Hội thoại **đa lượt, nhớ ngữ cảnh** (`--resume` per user+repo).
- Vòng lặp **agentic tự chạy** (đọc→sửa→chạy test→lặp) rồi trả lời — bản chất `claude -p`.
- **Toàn quyền** (`bypassPermissions`): Bash/Edit/Write + git push tự do.
- **Recap hành động**: cuối lượt liệt kê "đã đọc/sửa file gì, chạy lệnh gì" (parse `stream-json`).
- **Không cổng chặn**: làm thẳng trên nhánh chính, tự commit & push (giống Claude Code client
  trên repo của chính mình). ~~Cổng confirm push-main~~ đã bỏ (xem cuối file).
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
- [x] ~~Giữ pre-push hook chặn main~~ → **bỏ** (2026-07-09): clone `prod_branch` với
      `protected=[]`, bot tự do push nhánh chính.

### B4. Nhánh rẽ dev-mode trong dispatcher
- [ ] Trong `_dispatch_inbound` (sau khi có `user`, trước đường FSM/Orchestrator):
      `if tenant_dev_mode(user.tenant): return await dev_chat(...)`.
- [ ] `/clear` trong dev-mode → xoá `claude_session_id` (mở phiên mới), không đụng FSM.
- [ ] `dev_chat`: chọn repo (`user.active_repo_id` hoặc tenant có đúng 1 repo), ensure clone,
      gọi runner B3.

### ~~B5. Cổng confirm push-main~~ — ĐÃ GỠ (2026-07-09)
> Ban đầu dev-mode làm trên `dev`, deploy = PR `dev`→`main` có confirm. Đã **bỏ hẳn** theo
> yêu cầu "tự do như Claude Code client". Chi tiết ở mục "Thay đổi 2026-07-09" cuối file.
> Đã xoá: `_DEPLOY_SENTINEL`, `_deploy_main`, `_handle_deploy`, khối `await_main` trong
> `dev_chat`, i18n `dev.deploy_*`.

### B6. Tests
- [ ] `tenant_dev_mode` đọc đúng cờ; tenant không bật → đi đường FSM (chế độ thường bất biến).
- [ ] dev_chat: một lượt gọi runner (mock), lưu session_id, gửi recap.
- [ ] parse stream-json → recap đúng (fixture nhiều event tool_use + result).
- [x] ~~confirm-main~~ → thay bằng: clone `prod_branch` với `protected=[]`, không tự merge/PR.
- [ ] Guard: dev-mode KHÔNG chạm Orchestrator FSM (không tạo Request).

## Rủi ro / lưu ý
- **Toàn quyền = chạy code khách tự do** → giữ non-root + timeout (nâng `dev_timeout_s` riêng
  vì task agentic dài hơn one-shot). Chỉ bật cho tenant tin cậy.
- **Bot tự do push production** → chỉ bật cho tenant/developer tin cậy trên repo của họ.
- **stream-json**: cần `--verbose`; xử lý dòng lỗi/không-JSON an toàn (fallback về text).
- **Không migration cho cờ** (dùng settings_json); chỉ 1 migration cho `dev_sessions`.

## Định nghĩa "done"
- Tenant bật dev_mode: chat "sửa bug X, chạy test" → Claude tự làm, tự commit & push nhánh
  chính, trả recap + trả lời. "Tạo nhánh feature/x" → Claude tự tạo & push nhánh đó. Tenant
  KHÔNG bật: y hệt hôm nay (đi đường FSM).

## Thay đổi 2026-07-09 — "Claude Code client" hoá dev-mode
> **Trigger:** repo mới không có nhánh `dev` → `git clone --branch dev` fail
> ("Remote branch dev not found in upstream origin"). User muốn bot tự do như Claude Code client.
- **Nhánh làm việc:** `_ensure_repo` clone **`prod_branch`** (không phải `base_branch`).
- **Bỏ chặn:** truyền `protected=[]` → `_pre_push_hook([])` trả `exit 0` (không cài hook chặn).
  Claude tự commit & push nhánh chính; tự `git checkout -b` nhánh riêng khi user yêu cầu.
- **Gỡ cổng confirm-deploy:** xoá `_DEPLOY_SENTINEL`, `_deploy_main`, `_handle_deploy`, khối
  `await_main` trong `dev_chat`, i18n `dev.deploy_*`. `pending_json` giữ lại (chỉ reset /clear).
- **Prompt:** `_dev_system_prompt(main)` — làm trên `{main}`, tự commit & push, rẽ nhánh khi cần.
- **Tests:** thay 4 test deploy bằng 2 test (clone `prod_branch` + `protected=[]`; không tự merge).
  407/407 pass. **Chưa e2e trên VM.**
