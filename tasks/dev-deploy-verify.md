# Kế hoạch: Chờ deploy dev + tự test web trước khi mời manager

> Khiếu nại gốc (repo khách `sotaman`): bot merge vào `dev` → GitHub Action build+deploy lên
> `sotaman-dev`. **Build lỗi nhưng bot vẫn báo user merge OK / mời manager duyệt.**
> Mong muốn: sau khi merge dev, **chờ CI build+deploy xong**, **tự test lại trang web đúng
> yêu cầu**, rồi mới báo user — câu báo: *"em đã deploy lên môi trường dev và test thấy
> hoạt động ổn rồi"*. Build/test lỗi thì KHÔNG báo OK.

## Quyết định đã chốt với user
1. Mức test cuối: **Claude tự test bằng browser** (Playwright MCP). **B1 làm trước bằng CI xanh + curl HTTP 200**; browser thật để B2.
2. Phát hiện deploy xong: **poll GitHub Actions API** theo `head_sha` của commit merge.
3. Khi CI/test LỖI: **tự đưa log lỗi cho Claude sửa** rồi lặp lại (fix-forward), có **giới hạn vòng lặp** (`dev_verify_max_rounds`).
4. Triển khai **B1 trước, dừng review**.

## Luồng mới (sau khi nhân viên bấm "✅ Đạt" ở VERIFY)
```
verify_ok → merge PR vào dev (như cũ)
          → trạng thái = MERGED_DEV (tái dùng, KHÔNG mời manager ngay)
          → spawn BACKGROUND TASK: post_deploy_verify(req)   ← không chặn bot
                │
                ├─ poll Actions runs theo merge_sha tới completed (timeout ~15ph)
                │     ├─ conclusion != success → lấy log lỗi job → auto-fix (xem dưới)
                │     └─ success ↓
                ├─ Claude browser-test: --resume, mở dev_url, thao tác theo yêu cầu
                │     → kết JSON {"action":"dev_test","pass":true/false,"detail":"..."}
                │     ├─ pass=false → auto-fix
                │     └─ pass=true ↓
                └─ → AWAIT_MANAGER + notify manager + báo user
                      "✅ Em đã deploy lên môi trường dev và test thấy hoạt động ổn rồi. Chờ manager duyệt."

auto-fix (round < MAX, mặc định 2):
   feed log/lỗi cho Claude (_execute fix) → push cùng nhánh → CI chạy lại
   → quay lại bước poll. Hết MAX vòng vẫn lỗi → báo user + về VERIFY (nút Cần sửa/Huỷ).
```

### Vì sao tái dùng `MERGED_DEV` thay vì thêm status mới
`request_status` là native PG enum → thêm value cần `ALTER TYPE` (không chạy trong transaction,
phiền). `MERGED_DEV` hiện chỉ là bước nhảy tức thời sang `AWAIT_MANAGER` → ta giữ request ở
`MERGED_DEV` suốt quá trình deploy+test, tiến độ ghi vào `request_events`. Không cần migration enum.

## Cấu hình
### Per-repo (`repositories.settings_json` — JSONB, KHÔNG migration)
- `dev_url`: URL site dev để test (vd `https://sotaman-dev.example.com`). Thiếu → bỏ qua browser-test, chỉ chờ CI xanh.
- `deploy_workflow` (optional): tên file workflow để lọc run; bỏ trống = xét mọi run của `head_sha`.
- Sẽ set cho repo `sotaman` sau khi có URL thật.

### Global (`app/config.py`)
- `deploy_poll_interval_s: int = 15`
- `deploy_timeout_s: int = 900` (15 phút chờ CI)
- `dev_verify_max_rounds: int = 2` (số vòng auto-fix tối đa)
- `dev_verify_enabled: bool = True` (kill-switch; tắt = giữ hành vi cũ merge→mời manager ngay)

## Thành phần code
1. **`app/github_app.py`** (+~30 LOC): `list_workflow_runs(installation_id, repo, head_sha, workflow=None)`
   → `GET /repos/{repo}/actions/runs?head_sha=`; `list_run_jobs(... run_id)` để lấy step lỗi làm
   tóm tắt feed Claude (tránh tải zip log nặng; dùng job name + failed step + run html_url).

2. **`app/post_deploy.py`** (MỚI, ~180 LOC) — giữ orchestrator.py dưới 500 LOC:
   - `poll_deploy(github, repo, sha) -> DeployResult(success|failed|timeout, summary, run_url)`.
   - `run_dev_browser_test(claude_run, repo_dir, req, dev_url)`: chạy Claude `--resume` với
     Playwright MCP, parse JSON `dev_test`.
   - `post_deploy_verify(orch, req_id)`: orchestrator của background task (DB session riêng,
     vòng auto-fix, gọi lại `orch._execute`/merge, chuyển AWAIT_MANAGER, notify).

3. **`app/orchestrator.py`** (sửa nhỏ):
   - `_merge_to_dev`: sau merge, **không** sang AWAIT_MANAGER ngay; nếu `dev_verify_enabled` →
     `asyncio.create_task(post_deploy_verify(self, req.id))` + báo user "đang deploy & kiểm thử…".
     (Tắt hoặc thiếu `dev_url`+CI → giữ luồng cũ.)
   - Tách phần "→ AWAIT_MANAGER + notify" thành helper `_enter_await_manager(req)` để post_deploy gọi.

4. **`app/claude_runner.py`** (+~10 LOC): thêm tham số `mcp_config: Path|None` và
   `allowed_tools: list[str]|None` → `--mcp-config`, `--allowedTools`. Cần cho browser-test phase.

5. **`app/prompts.py`** (+1 hàm): `dev_test_system_prompt(dev_url, ...)` — ràng buộc Claude
   mở `dev_url` bằng Playwright, kiểm chứng đúng yêu cầu, kết JSON `{"action":"dev_test","pass":bool,"detail":...}`.
   `app/parsing.py`: thêm Action.DEV_TEST.

6. **`app/recovery.py`**: thêm `MERGED_DEV` vào tập "interrupted" — background task chết khi
   restart. Xử lý: re-kick `post_deploy_verify` lúc startup (đã merge dev rồi, không hủy oan)
   thay vì cancel. (Hoặc đơn giản hơn cho MVP: báo user "đang tiếp tục kiểm thử lại".)

7. **`deploy/Dockerfile`**: cài `@playwright/mcp` + `npx playwright install --with-deps chromium`
   (~400MB). Thêm `deploy/mcp/playwright.json` mount/copy làm `--mcp-config`.
   ⚠️ Đây là phần NẶNG nhất & tăng attack surface (chạy chung container code khách). Cân nhắc
   phương án nhẹ hơn nếu muốn: chỉ CI-xanh + `curl` HTTP 200 (bỏ Playwright).

## Tests (tests/)
- `test_post_deploy.py`: poll_deploy (fake github: success/failed/timeout), vòng auto-fix tới MAX,
  pass→AWAIT_MANAGER + notify, fail→về VERIFY. Fake claude_run trả JSON dev_test.
- `test_github_actions.py`: list_workflow_runs/list_run_jobs (httpx mock).
- orchestrator: `_merge_to_dev` khi `dev_verify_enabled=False` giữ luồng cũ (regression).

## Mốc (dừng review giữa chừng)
- **B1 — Lõi orchestration (không Playwright) — ✅ XONG (122 tests pass):**
  - `config.py`: DEV_VERIFY_ENABLED / DEPLOY_POLL_INTERVAL_S / DEPLOY_TIMEOUT_S / DEV_VERIFY_MAX_ROUNDS.
  - `github_app.py`: `list_workflow_runs` + `run_failure_summary` (Actions API).
  - `app/post_deploy.py` (MỚI): poll deploy theo merge_sha → CI xanh + **curl dev_url 200** → AWAIT_MANAGER
    + báo "đã deploy lên dev và test ổn"; lỗi → auto-fix fix-forward (nhánh `bot/req-N-fixK` mới mỗi
    vòng → PR → merge dev), tối đa `DEV_VERIFY_MAX_ROUNDS`; hết vẫn lỗi → về VERIFY (reset pr_number)
    **không mời manager**. `notify_managers`/`enter_await_manager` chuyển từ orchestrator sang đây.
  - `orchestrator._merge_to_dev`: opt-in per repo (`settings_json.dev_url`) → spawn background task
    (không chặn poller); repo chưa bật → mời manager ngay (hành vi cũ, regression test phủ).
  - `recovery.rekick_pending_deploys` + wire main.lifespan: re-poll request kẹt `MERGED_DEV` sau restart.
  - `tests/test_post_deploy.py`: 6 case (CI xanh+curl ok, curl fail, auto-fix→ok, hết vòng, fix rỗng, repo chưa bật).
  → **Đã trị dứt khiếu nại "build lỗi vẫn báo OK".** Browser-test thật để B2. **DỪNG review.**
- **B2 — Browser-test thật:** Dockerfile Playwright MCP + claude_runner mcp flags + prompt
  dev_test + parsing. → Test web đúng yêu cầu. **DỪNG review.**
- **B3 — Cấu hình sotaman:** set `dev_url` cho repo sotaman, e2e thử 1 yêu cầu thật.

## Câu hỏi còn mở (cần khi tới B2/B3)
- URL site dev của sotaman? (cho `repo.settings_json.dev_url`)
- Site dev có cần đăng nhập không? (nếu có → cần cấp credential test cho Playwright)
- Workflow deploy tên gì / có nhiều workflow chạy cùng `head_sha` không?
