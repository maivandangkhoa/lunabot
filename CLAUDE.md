# CLAUDE.md — luna

> **luna** — SaaS "Software Maintenance Bot" (multi-tenant). Nhận yêu cầu bảo trì phần
> mềm qua chat (Telegram MVP), chạy **Claude Code CLI headless** để sửa code trên repo
> của khách (GitHub App), với **quy trình có cổng người duyệt** (FSM): yêu cầu → phân
> tích → hỏi lại → trình kế hoạch → thực thi trên `dev` → nhân viên verify → manager
> duyệt merge `main`.
>
> Kế hoạch chi tiết & mốc M0→M7: [tasks/todo.md](tasks/todo.md). **Đọc trước khi làm.**

## Stack
- **Python 3.12**
- **FastAPI** + uvicorn — webhook Telegram/GitHub + admin
- **SQLAlchemy 2.0 + Alembic** — Postgres **self-hosted trong container** (service `db` ở
  compose) cho MVP; **KHÔNG** dùng chung DB internal. Đổi sang Supabase chỉ cần sửa
  `DATABASE_URL` (code không đụng). Self-hosted ⇒ phải tự backup: `deploy/backup.sh` (cron `pg_dump`).
- **aiogram 3** (Telegram, webhook mode) — qua adapter `app/channels/`
- **Claude Code CLI headless** — `claude -p --output-format json --resume` (subprocess)
- **GitHub App** — PyJWT + httpx, installation token ngắn hạn
- **Docker** — image non-root (node CLI + python + git + gh), compose, GitHub Actions deploy

## Cấu trúc
```
app/
  main.py          # FastAPI: /webhook/telegram, /webhook/github, /admin, /healthz
  config.py        # settings (pydantic-settings, đọc env)
  db.py            # SQLAlchemy engine/session
  models.py        # tenants/repositories/users/requests/request_events/approvals
  orchestrator.py  # FSM lifecycle (M4) — lõi nghiệp vụ
  claude_runner.py # subprocess claude -p (M1)
  github_app.py    # JWT → installation token → clone/push/PR/merge (M2)
  prompts.py       # system prompt từng phase (M5)
  parsing.py       # trích & validate khối json cuối từ output Claude (M5)
  channels/
    base.py        # ChannelAdapter protocol
    telegram.py    # aiogram adapter (M3)
alembic/           # migrations
deploy/            # Dockerfile, docker-compose.yml, entrypoint.sh, env.example
tests/
```

## Quy tắc code (BẮT BUỘC)
- **≤ 500 LOC/file.** `orchestrator.py` dễ phình → tách theo phase nếu cần.
- **Root cause, không workaround.** Fix tận gốc.
- **Đọc trước khi sửa.** Luôn Read file trước Edit.
- **App giữ quyền điều phối (FSM).** Claude chỉ "suy nghĩ + viết code" trong từng phase và
  **trả về 1 khối ```json ở cuối** để app chuyển state. Không để Claude tự quyết toàn bộ.

## Gotchas (rút từ plan + )
- **Claude từ chối `bypassPermissions` khi chạy root** → container drop xuống user `node`
  bằng `gosu` (xem `entrypoint.sh`). Đây là lý do image non-root.
- **Permission mode theo phase:** `--permission-mode plan` cho phase chỉ-đọc
  (ANALYZING/CLARIFYING/PLAN_REVIEW); `bypassPermissions` cho EXECUTING.
- **NEVER push `main`:** cài pre-push hook chặn (port từ `bot.py`) + GitHub branch protection.
- **GitHub App token TTL ~1h** → sinh lại trước mỗi thao tác git; **không bao giờ log token**.
- **JSON từ Claude không đảm bảo 100%** → `parsing.py` phải fallback an toàn, KHÔNG tự ý
  chuyển state khi parse fail; báo lỗi rõ để người can thiệp.
- **Mỗi `request` neo `claude_session_id`** để `--resume` giữ ngữ cảnh xuyên vòng đời.
- **Isolation:** mỗi repo clone tại `WORKSPACE/<tenant>/<repo>`; MVP **serialize per-repo
  bằng lock** (nâng cấp `git worktree` khi cần song song).
- **Auth Claude:** `CLAUDE_CODE_OAUTH_TOKEN` (subscription) cho MVP.
- **`` chỉ để đọc & port** — KHÔNG import trực tiếp, KHÔNG phải code production.

## FSM (status của `requests`)
`NEW → ANALYZING → (CLARIFYING ⇄ ANALYZING) → PLAN_REVIEW → EXECUTING → VERIFY →
MERGED_DEV → AWAIT_MANAGER → MERGED_MAIN → CLOSED`; bất kỳ đâu → `CANCELLED`.
EXECUTING ⇄ VERIFY khi "cần sửa". Chi tiết mapping phase→Claude: [tasks/todo.md](tasks/todo.md).

## Workflow
- Làm theo mốc **M0→M7**; **dừng sau mỗi mốc cho user review**.
- Roles: chỉ `manager` được duyệt merge `main`; chỉ requester (hoặc cùng tenant) thao tác request.
