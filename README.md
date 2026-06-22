# luna

SaaS **Software Maintenance Bot** (multi-tenant). Nhận yêu cầu bảo trì phần mềm qua chat
(Telegram MVP), chạy **Claude Code CLI headless** sửa code trên repo của khách (GitHub App),
theo **quy trình có cổng người duyệt** (FSM): yêu cầu → phân tích → hỏi lại → trình kế
hoạch → thực thi trên `dev` → nhân viên verify → manager duyệt merge `main`.

> Kế hoạch & mốc M0→M7: [tasks/todo.md](tasks/todo.md). Quy ước & gotchas: [CLAUDE.md](CLAUDE.md).

## Trạng thái — M0→M7 ✅ (MVP, chat-only)
- **M0** Scaffold: FastAPI + Postgres + SQLAlchemy + Alembic + models + Docker.
- **M1** `claude_runner.py` — subprocess `claude -p`, permission-mode theo phase, timeout.
- **M2** `github_app.py` (JWT→installation token→PR) + `git_ops.py` (clone/push + pre-push hook chặn `main`).
- **M3** `channels/telegram.py` — webhook, inline buttons, `/start <token>`.
- **M4** `orchestrator.py` — FSM đầy đủ (NEW→…→CLOSED), lưu requests/events/approvals.
- **M5** `prompts.py` + `parsing.py` — prompt từng phase + parser JSON fallback an toàn.
- **M6** `onboarding.py` + `dispatcher.py` — multi-tenant, roles, isolation/lock per repo.
- **M7** Docker compose + `.github/workflows/deploy.yml` + `scripts/seed.py`.

## Cấu trúc
```
app/        # claude_runner, github_app, git_ops, orchestrator, dispatcher,
            # prompts, parsing, onboarding, models, config, db, main, channels/
alembic/    # migrations (0001_initial)
deploy/     # Dockerfile, docker-compose.yml, entrypoint.sh, backup.sh, env.example
scripts/    # seed.py (onboard tenant/repo/users)
tests/      # 40 tests (parsing, runner, github, git, telegram, orchestrator, dispatcher)
```

## Onboard 1 tenant (seed)
```bash
python -m scripts.seed --tenant "Acme" --repo acme/widgets --installation 12345 \
    --manager "Alice" --employee "Bob"
# In ra "/start <token>" cho từng người → họ gửi cho bot Telegram để liên kết.
```

## Luồng e2e (Telegram, chat-only)
1. Nhân viên gửi yêu cầu (text) → bot phân tích → **hỏi lại** (nếu mơ hồ) → trình **kế hoạch** + nút **✅ Confirm**.
2. Confirm → bot tạo nhánh `bot/req-<id>`, để Claude sửa code, push + mở **PR vào `dev`** → nút **✅ Đạt / 🔧 Cần sửa / ❌ Huỷ**.
3. ✅ Đạt → merge PR vào `dev` → thông báo **manager** với nút **✅ Cho merge / ❌ Từ chối**.
4. Manager ✅ → merge `dev → main` → đóng request. (Chỉ `manager`/`admin` được duyệt.)

## Chạy local (dev)
```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env            # điền DATABASE_URL (Postgres)

alembic upgrade head            # tạo schema
uvicorn app.main:app --reload   # http://localhost:8000/healthz

pytest -q                       # smoke tests (không cần DB)
```

## Chạy bằng Docker
```bash
cp deploy/env.example /etc/luna/luna.env   # điền secrets
docker compose -f deploy/docker-compose.yml up -d --build
```
Container chạy **non-root** (gosu user `node`) vì Claude từ chối `bypassPermissions` khi
là root. `entrypoint.sh` tự `alembic upgrade head` trước khi serve.

## Data model
`tenants → repositories / users → requests → request_events / approvals`.
`requests.status` chạy qua FSM `RequestStatus` (xem [app/models.py](app/models.py)).
