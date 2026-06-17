# Kế hoạch: luna — SaaS "Software Maintenance Bot" (multi-tenant)

> Dự án **ĐỘC LẬP**, tách khỏi internal. Đây là file khởi đầu của repo mới `~/projects/luna`.
> Tên dự án: **luna**. (Trong plan dưới đây "maint-bot" = luna; đổi tên trong code theo `luna`.)

## 🤖 ĐỌC TRƯỚC TIÊN (cho session khởi tạo luna)
Bạn đang ở repo trống `~/projects/luna`. Nhiệm vụ: hiện thực hoá plan này theo từng mốc M0→M7.
- **File mẫu tham chiếu đã được copy sẵn vào ``** (KHÔNG phải code production của luna,
  chỉ là pattern lấy từ internal để học/port — đọc rồi viết lại cho sạch theo cấu trúc luna):
  - `bot.py` — ⭐ subprocess `claude -p --output-format json --resume`,
    state per-chat, cài pre-push hook chặn `main`, xử lý lỗi/timeout, split message dài.
    → Là nguồn chính để port `app/claude_runner.py`.
  - `{Dockerfile,entrypoint.sh,docker-compose.yml}` — image non-root (gosu),
    cài `@anthropic-ai/claude-code` + git + gh, auth gh. → Nguồn cho `deploy/`.
  - `{ops-bot.env.example,projects.yaml,requirements.txt,README.md}` — env vars,
    config repo per-project, deps.
  - `{base,dispatcher,telegram}.py` — adapter + registry + dispatcher pattern
    (đa kênh). → Nguồn cho `app/channels/base.py` (interface ChannelAdapter).
  - `sample-bot` — webhook Telegram + verify secret header + link-account `/start <token>`.
    → Nguồn cho `app/channels/telegram.py` (webhook mode) và luồng liên kết user.
- **Bước đầu tiên nên làm:** tạo `CLAUDE.md` cho luna (tên dự án, stack, gotchas rút từ plan này),
  rồi mới bắt đầu M0. Sau mỗi mốc, dừng cho user review.
- `` chỉ để đọc; có thể xoá/đưa vào `.gitignore` khi không cần nữa.

## Context — vì sao làm cái này
internal đã có sẵn **ops-bot** (`deploy/ops-bot/`): một ops bot chạy Claude Code headless trên VM,
nhận tin Telegram → tự sửa code → commit → push/PR. Đây là pattern đã chạy production, single-tenant,
single-user, và Claude tự quyết mọi thứ trong 1 lượt.

Mục tiêu: **sản phẩm hoá** pattern đó thành SaaS cho nhiều công ty. Khác biệt cốt lõi so với ops-bot:
1. **Multi-tenant** (nhiều công ty, nhiều repo, nhiều user, có **vai trò** employee/manager).
2. **Quy trình có cổng người duyệt** (state machine), không phải "1 prompt làm hết":
   yêu cầu → bot phân tích → **hỏi lại nếu chưa rõ** → **trình kế hoạch xin confirm** → thực thi trên `dev`
   → **nhân viên kiểm tra** → **manager duyệt merge vào `main`**.
3. **Đa nền tảng chat** qua adapter (MVP: Telegram; sau: Slack, Google Chat).
4. **Kết nối repo qua GitHub App** (token scoped, ngắn hạn, an toàn multi-tenant).

Quyết định đã chốt với user:
- Engine: **Claude Code CLI headless** (`claude -p --output-format json --resume`) — tái dùng pattern `deploy/ops-bot/bot.py`.
- Platform MVP: **Telegram** (aiogram), kiến trúc adapter để mở rộng.
- Git provider: **GitHub App**.
- Hosting: **1 instance dùng chung**, mỗi tenant có **workspace clone + state cô lập**.

---

## Kiến trúc tổng thể

```
Nhân viên / Manager (Telegram)
        │  (inline buttons: Confirm / Verify / Approve)
        ▼
┌──────────────────────────────────────────────────────────┐
│  maint-bot service (1 container, Python)                   │
│                                                            │
│  ┌────────────┐   ┌─────────────────┐   ┌──────────────┐  │
│  │ Channel     │   │ Orchestrator     │   │ Claude       │  │
│  │ Adapter     │──▶│ (FSM lifecycle   │──▶│ Runner       │  │
│  │ (Telegram)  │   │  per request)    │   │ (subprocess) │  │
│  └────────────┘   └────────┬─────────┘   └──────┬───────┘  │
│         ▲                  │                     │          │
│         │                  ▼                     ▼          │
│         │           ┌────────────┐      claude -p --resume │
│         └───────────│ Postgres   │      cwd=workspace/      │
│   outbound replies  │ (tenants,  │       <tenant>/<repo>   │
│                     │ users,     │                         │
│                     │ requests,  │   ┌──────────────────┐  │
│                     │ events)    │   │ GitHub App        │  │
│                     └────────────┘   │ (clone/push/PR/   │  │
│                                       │  merge via token) │  │
│  FastAPI: /webhook/telegram, /webhook/github, /admin      │  │
└──────────────────────────────────────────────────────────┘  │
                                       ▼
                              GitHub repo của khách (dev → main)
```

**Nguyên tắc điều khiển:** App giữ quyền điều phối (FSM). Claude chỉ làm phần "suy nghĩ + viết code"
trong từng phase, và **trả về 1 khối JSON ở cuối** để app biết chuyển trạng thái. Dùng `--permission-mode plan`
cho các phase chỉ-đọc (phân tích/hỏi/lập kế hoạch) và `bypassPermissions` cho phase thực thi.

---

## Tech stack
| Layer | Choice | Ghi chú |
|---|---|---|
| Ngôn ngữ | Python 3.12 | khớp pattern ops-bot, dễ copy |
| Web/API | FastAPI | webhook Telegram + GitHub + admin |
| Chat | aiogram 3 (Telegram) | adapter; webhook mode (không long-poll cho SaaS) |
| Engine | Claude Code CLI headless | `@anthropic-ai/claude-code`, `--output-format json --resume` |
| DB | Postgres **self-hosted trong container** (MVP) | multi-tenant; **không** dùng chung DB internal. Đổi sang Supabase = sửa `DATABASE_URL`. Backup: `deploy/backup.sh` (cron pg_dump) |
| ORM | SQLAlchemy + Alembic | |
| Git | GitHub App (PyJWT + httpx, hoặc PyGithub) | installation token ngắn hạn |
| Auth Claude | `CLAUDE_CODE_OAUTH_TOKEN` (subscription) | hoặc `ANTHROPIC_API_KEY` nếu muốn tính tiền/usage |
| Deploy | Docker + docker-compose + GitHub Actions | VM (Cloud hiện có hoặc VPS mới) |

---

## Data model (Postgres)
- **tenants**: `id, name, plan, chat_platform, settings_json, created_at`
- **repositories**: `id, tenant_id, gh_installation_id, repo_full_name, base_branch (mặc định 'dev'), prod_branch (mặc định 'main'), settings_json`
- **users**: `id, tenant_id, platform ('telegram'), platform_user_id (chat_id), role ('employee'|'manager'|'admin'), display_name, link_token, linked_at`
- **requests** (ticket — thực thể trung tâm): `id, tenant_id, repo_id, requester_user_id, title, body, status (FSM enum), claude_session_id, branch_name, pr_number, pr_url, created_at, updated_at`
- **request_events** (audit + lịch sử hội thoại): `id, request_id, actor_user_id, kind ('msg'|'clarify'|'plan'|'confirm'|'verify'|'approve'|'system'), direction ('in'|'out'), payload_json, created_at`
- **approvals**: `id, request_id, approver_user_id, type ('merge_to_main'), decision ('approved'|'rejected'), note, created_at`

Mỗi `request` neo `claude_session_id` để `--resume` giữ ngữ cảnh xuyên suốt vòng đời.

---

## Vòng đời request (FSM) — trái tim hệ thống

```
NEW ──► ANALYZING ──┬─► CLARIFYING ──(nhân viên trả lời)──► ANALYZING
                    │        ▲                                  │
                    │        └──────────────────────────────────┘
                    └─► PLAN_REVIEW ──(confirm)──► EXECUTING ──► VERIFY
                              │ (reject/sửa plan)                  │
                              └──────────────◄───────────────┐    │
                                                             (🔧 cần sửa)
                                          ┌───────────────────────┤
                                          ▼                       ▼
                                   EXECUTING (fix)         (✅ đạt) MERGED_DEV
                                                                   │
                                                          ──► AWAIT_MANAGER
                                                                   │ (manager ✅)
                                                                   ▼
                                                               MERGED_MAIN ──► CLOSED
                                            (huỷ ở bất kỳ đâu) ──► CANCELLED
```

**Mapping phase → Claude invocation:**

1. **ANALYZING / CLARIFYING** — `claude -p <prompt> --permission-mode plan --output-format json [--resume]`
   - System prompt: *chỉ đọc, KHÔNG sửa file*. Phân tích yêu cầu theo codebase.
     Nếu mơ hồ → hỏi; nếu rõ → lập kế hoạch. **Bắt buộc kết thúc bằng 1 khối ```json**:
     - `{"action":"clarify","questions":["...","..."]}`  → FSM = CLARIFYING, bot gửi câu hỏi
     - `{"action":"plan","summary":"...","steps":["..."],"risk":"low|med|high"}` → FSM = PLAN_REVIEW
   - Nhân viên trả lời câu hỏi → `--resume` lại phase này.

2. **EXECUTING** (sau khi nhân viên bấm **Confirm**) — `claude -p <prompt> --permission-mode bypassPermissions --resume --output-format json`
   - System prompt (theo repo config): tạo nhánh `bot/req-<id>` từ `dev`, implement đúng plan đã chốt,
     `git pull --rebase origin dev`, commit, push, `gh pr create --base dev --fill`. **NEVER push `main`** (pre-push hook chặn).
   - Kết thúc bằng ```json: `{"action":"implemented","branch":"...","pr_url":"...","summary":"..."}` → FSM = VERIFY.

3. **VERIFY** — bot gửi nhân viên: tóm tắt + PR URL + 3 nút: **✅ Đạt** / **🔧 Cần sửa** / **❌ Huỷ**.
   - 🔧 + mô tả → EXECUTING (fix): `--resume` với feedback, push tiếp cùng nhánh.
   - ✅ → bot merge PR vào `dev` (cổng nhân viên) → FSM = MERGED_DEV → AWAIT_MANAGER.

4. **AWAIT_MANAGER** — bot thông báo (các) manager của tenant: tóm tắt + PR + 2 nút **✅ Cho merge** / **❌ Từ chối**.
   - ✅ → bot merge `dev → main` (PR `dev→main` hoặc fast-forward theo config) → MERGED_MAIN → CLOSED.
   - Ghi `approvals`.

**Parsing tín hiệu:** trích khối ```json cuối cùng trong `result` của Claude (regex fenced block). Nếu thiếu/parse fail → coi như cần người can thiệp, báo lỗi rõ ràng (giống xử lý lỗi `bot.py:151-171`).

---

## Git flow (GitHub App)
- Tạo **GitHub App**: permissions `Contents: R/W`, `Pull requests: R/W`, `Metadata: R`. Webhook events: `installation`, `pull_request`, `push` (tuỳ chọn `check_suite` để gắn CI sau).
- Khách **Install App** vào org/repo → ta lưu `gh_installation_id` vào `repositories`.
- Sinh **installation access token** (JWT ký bằng private key của App → `POST /app/installations/{id}/access_tokens`, TTL ~1h). Dùng làm remote `https://x-access-token:<token>@github.com/<repo>.git` cho clone/push, và header cho REST tạo/merge PR.
- Mỗi repo 1 clone tại `WORKSPACE/<tenant>/<repo>`. Mỗi request checkout nhánh `bot/req-<id>` (cân nhắc `git worktree` để chạy song song nhiều request/repo; MVP: **serialize per repo bằng lock**).
- Cài **pre-push hook** chặn `main` (copy từ logic ops-bot) như lớp phòng vệ; cộng thêm **GitHub branch protection** trên `main`.

---

## Messaging adapter (đa nền tảng)
Định nghĩa interface (tham khảo `api/notifications/base.py` + `dispatcher.py` của internal):
```python
class ChannelAdapter(Protocol):
    name: str
    def parse_inbound(self, raw) -> InboundMessage: ...      # update → normalized
    async def send(self, user, text, buttons=None): ...      # outbound + action buttons
    async def answer_callback(self, cb): ...                  # xử lý bấm nút
```
- MVP chỉ `TelegramAdapter` (aiogram, **webhook mode** + secret header verify như `bot/main.py`). Dùng **inline keyboard** cho Confirm/Verify/Approve thay vì gõ lệnh — UX tốt hơn cho không-kỹ-thuật.
- Slack / Google Chat thêm sau bằng adapter mới, FSM/Orchestrator **không đổi**.

---

## Roles & onboarding
- Liên kết tài khoản kiểu internal: nhân viên `/start <link_token>` → map `platform_user_id` ↔ `users` (xem `api/server/routers/users.py:94` `link-telegram`).
- `role` (employee/manager) do admin tenant gán (admin API hoặc seed thủ công cho MVP).
- Phân quyền: chỉ `manager` được duyệt merge vào `main`; chỉ requester (hoặc cùng tenant) thao tác request của mình.

---

## Cấu trúc repo mới (đề xuất)
```
maint-bot/
├── app/
│   ├── main.py              # FastAPI: webhooks + admin
│   ├── config.py            # settings (env)
│   ├── db.py                # SQLAlchemy engine/session
│   ├── models.py            # tenants/repos/users/requests/events/approvals
│   ├── orchestrator.py      # FSM lifecycle (lõi nghiệp vụ)
│   ├── claude_runner.py     # subprocess claude -p (copy từ deploy/ops-bot/bot.py)
│   ├── github_app.py        # JWT, installation token, clone/push/PR/merge
│   ├── prompts.py           # system prompt từng phase + định dạng JSON bắt buộc
│   ├── parsing.py           # trích & validate khối json cuối từ output Claude
│   └── channels/
│       ├── base.py          # ChannelAdapter protocol
│       └── telegram.py      # aiogram adapter (webhook + inline buttons)
├── alembic/                 # migrations
├── deploy/
│   ├── Dockerfile           # node(claude-cli)+python+git+gh, non-root (copy ops-bot)
│   ├── docker-compose.yml
│   └── env.example
├── .github/workflows/deploy.yml
├── tests/
└── README.md
```
> Giữ **mỗi file ≤ 500 LOC** (quy tắc repo). `orchestrator.py` là nơi dễ phình → tách theo phase nếu cần.

---

## Mốc xây dựng (cho session khởi tạo)
1. **M0 — Scaffold:** repo + FastAPI + Postgres + Alembic + models + Docker (copy Dockerfile/entrypoint non-root từ `deploy/ops-bot/`).
2. **M1 — Claude runner:** port `claude_runner.py` từ `bot.py:130-172` (subprocess, json, `--resume`, timeout, error-handling).
3. **M2 — GitHub App:** `github_app.py` (JWT → installation token → clone/push/PR/merge); test trên 1 repo sandbox.
4. **M3 — Telegram adapter:** webhook + inline buttons + link `/start <token>`.
5. **M4 — Orchestrator/FSM:** đủ vòng ANALYZE→CLARIFY→PLAN_REVIEW→EXECUTING→VERIFY→AWAIT_MANAGER→MERGED; lưu `requests`/`events`/`approvals`.
6. **M5 — Prompts + parsing:** prompt từng phase + ép định dạng json + parser chịu lỗi.
7. **M6 — Multi-tenant + roles:** tenant/repo/user seeding, phân quyền manager, isolation workspace.
8. **M7 — Deploy + e2e:** docker-compose lên VM, GitHub Actions deploy, chạy thử end-to-end 1 yêu cầu thật.

---

## Rủi ro & lưu ý
- **Chạy code khách = rủi ro bảo mật.** MVP shared-instance: bắt buộc **non-root + mem/cpu limit + timeout** (như ops-bot). Nếu phase verify cần build/test (chạy code khách) → lộ trình **container/sandbox riêng/tenant** ở phase sau.
- **Race condition nhánh:** serialize per-repo bằng lock; nâng cấp `git worktree` khi cần song song.
- **Token GitHub App** TTL ngắn → sinh lại trước mỗi thao tác git; không log token.
- **Chi phí Claude:** dùng OAuth subscription (không tính tiền/req) cho MVP; nếu cần usage-based billing → chuyển `ANTHROPIC_API_KEY` và parse `total_cost_usd` từ output.
- **JSON từ Claude không đảm bảo 100%** → parser phải fallback an toàn, không tự ý chuyển state khi mơ hồ.
- **KHÔNG dùng chung DB/secret với internal** — dự án tách biệt hoàn toàn.

## Tái dùng từ internal (đã copy vào `` — đọc & port, KHÔNG import trực tiếp)
- `bot.py` — subprocess Claude, state per-chat, `--resume`, pre-push hook, error-handling, split message dài → `app/claude_runner.py`.
- `{Dockerfile,entrypoint.sh,docker-compose.yml}` — image non-root + gosu, gh auth → `deploy/`.
- `{base,dispatcher,telegram}.py` — adapter + registry + dispatcher pattern → `app/channels/base.py`.
- `sample-bot` — webhook verify + link-account flow (`/start <token>`) → `app/channels/telegram.py`.

## Verification (định nghĩa "done" cho MVP)
1. **Unit:** `parsing.py` (trích json), `orchestrator` transitions (giả lập output Claude).
2. **Integration GitHub App:** clone → tạo nhánh → commit → PR → merge trên repo sandbox thật.
3. **E2E thủ công (Telegram):** gửi 1 yêu cầu mơ hồ → bot hỏi lại → trả lời → bot ra plan → Confirm → bot tạo PR vào `dev` → bấm ✅ Đạt → merge dev → manager bấm ✅ → merge `main`. Kiểm tra `requests.status` + `request_events` + `approvals` đúng từng bước.
4. **Negative:** bot KHÔNG được push thẳng `main` (pre-push hook chặn); user không phải manager KHÔNG duyệt được merge.
