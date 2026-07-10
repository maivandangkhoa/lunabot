# Plan: Deploy-preview-first UAT (hướng B)

## Vấn đề
Cổng UAT của requester nằm **trước** khi có bản chạy thật. Requester bấm "Đạt/Cần sửa"
dựa trên self-test (git diff) của bot, tới lúc thấy URL `.../dev/` thì đã lỡ qua cửa,
chỉ còn chờ manager. → Họ "duyệt mù".

## Mục tiêu
Đảo cổng: **deploy bản xem thử lên `dev` TRƯỚC, requester UAT trên URL thật, rồi mới mời manager.**

```
Cũ:  EXECUTING → VERIFY(duyệt mù) → MERGED_DEV(deploy) → AWAIT_MANAGER
Mới: EXECUTING → MERGED_DEV(deploy preview) → VERIFY(UAT trên URL) → AWAIT_MANAGER
```

Không migration: tái dùng state `VERIFY`, phân biệt bằng `dev_merge_sha`
(null = chưa merge/đang chờ slot; not-null = đã deploy, đang UAT trên live).

## Nguyên tắc "đè" (đã chốt)
- URL live `.../dev/`: bản mới nhất luôn thắng → rework redeploy đè site. ✔
- Nhánh `dev`: **KHÔNG force-push**; rework = commit mới chồng lên (pre-push hook chặn force).
- Nhánh feature `req-N`: bot toàn quyền commit thêm.

---

## Thay đổi code

### 1. `orchestrator._execute` (cuối, ~L500)
- BỎ: `_set_status(VERIFY)` + `self_test_message` + `_verify_buttons`.
- THAY: sau push/PR thành công → gọi thẳng `_merge_to_dev(req)` (tự động dựng preview).
- Vẫn báo requester ngắn gọn "Em sửa xong, đang dựng bản xem thử…" (dùng luôn message
  `merged_dev_waiting_deploy` sẵn có trong `_merge_to_dev`).

### 2. `orchestrator._merge_to_dev`
- Sau `merge_pull_request` thành công: **reset `req.pr_number = None`, `req.pr_url = None`**
  (PR đã đóng) để vòng rework kế tiếp mở PR mới sạch — giống `_give_up` đang làm.
- Nhánh holder-busy (slot dev đang bị request khác giữ): thay vì re-show verify buttons,
  **park**: giữ `VERIFY` với `dev_merge_sha = NULL` + cờ `report_json["_await_slot"]=True`,
  báo requester "đang chờ request #X xong". (xem mục 5)

### 3. `post_deploy._run_verify_loop` — nhánh `passed` (~L343-347)
- BỎ: `enter_await_manager(...)`.
- THAY: quay lại **requester UAT**:
  - `_set_status(VERIFY)` (dev_merge_sha vẫn not-null ⇒ nhận diện "post-deploy UAT").
  - Gửi requester: self-test summary + **link dev thật** + nút `verify_ok`/`verify_fix`/`cancel`.
  - i18n key mới, vd `ops.uat_ready_link` (gộp nội dung self_test_message + URL).
- Nhánh `no_ci` (repo không có CI deploy → không có URL live): fallback về cổng cũ —
  `VERIFY` + self_test_message (không URL) + nút UAT. Requester vẫn duyệt, chỉ là không có link.
- `_give_up` (deploy fail hết vòng): giữ nguyên (đã về VERIFY + needs_fix/cancel).

### 4. `orchestrator` dispatch action (~L267-269)
- `verify_ok` khi VERIFY: đổi từ `_merge_to_dev(req)` → `enter_await_manager(orch, req)`
  (đã merge dev rồi, giờ chỉ mời manager). Guard: chỉ khi `dev_merge_sha` not-null;
  nếu null (no_ci fallback) → vẫn cần merge dev trước → `_merge_to_dev`.
- `verify_fix` khi VERIFY: giữ nguyên (prompt xin mô tả) → text feedback →
  `_execute(fix_feedback)` → tạo PR mới (pr_number đã reset) → `_merge_to_dev` → deploy → UAT lại.

### 5. Hàng đợi slot dev (contention)
Trước đây requester tự re-click để retry khi slot bận. Giờ auto-merge nên cần "kick" khi slot nhả.
- Thêm `orchestrator._advance_dev_queue(repo)`: tìm request cùng repo đang park
  (`VERIFY` + `dev_merge_sha IS NULL` + `report_json._await_slot`), cũ nhất → gọi `_merge_to_dev`.
- Gọi `_advance_dev_queue` tại các điểm **nhả slot**:
  - `_merge_to_main` thành công (MERGED_MAIN, ~L584)
  - cancel (~L283, ~L309) + `_manager_reject`
  - `branch_sync.resolve_conflict_and_merge` (sau khi release)
- Guard dispatcher: request đang park (`_await_slot`) → text feedback KHÔNG chạy `_execute`
  (bỏ qua/nhắc đang chờ), tránh chạy lại nhầm.

### 6. i18n
- Key mới: `ops.uat_ready_link` (bàn giao UAT có link), có thể tái dùng `ops.deploy_ok_link`.
- Bổ sung vi/en/ko; **vi phải giống hệt bản gốc** nếu tách từ chuỗi cũ (test substring — xem
  [[luna-chatbot-i18n]]).

---

## Test (pytest)
1. `_execute` xong → auto `_merge_to_dev`, KHÔNG hỏi requester trước deploy.
2. Deploy pass → requester nhận link + nút UAT (state VERIFY, dev_merge_sha not-null).
3. `verify_ok` post-deploy → `enter_await_manager` (KHÔNG merge lại dev).
4. `verify_fix` post-deploy → reset PR → EXECUTING → PR mới → merge dev → deploy → UAT lại (không force-push).
5. no_ci → fallback UAT không link → verify_ok → merge dev → await_manager.
6. Contention: request B park khi A giữ slot; A merge_main/cancel → B tự tiến (`_advance_dev_queue`).
7. Guard: text feedback lúc B đang park → không chạy _execute.

## Rủi ro / cần soi
- Recovery/restart: `verify_after_dev_merge` rekick khi MERGED_DEV — vẫn đúng vì UAT nằm sau
  deploy-gate ([[luna-resilience]]).
- `reconcile.py`/`_dev_pipeline_holder`: đảm bảo định nghĩa "đang giữ slot" vẫn khớp
  (MERGED_DEV/AWAIT_MANAGER) — request park ở VERIFY-null KHÔNG tính là holder.
- Ước lượng: ~2 file lõi (orchestrator, post_deploy) + i18n + tests. Không migration. Không đụng backend web.
