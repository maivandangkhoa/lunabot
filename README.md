# luna

SaaS **Software Maintenance Bot** (multi-tenant). Nhận yêu cầu bảo trì phần mềm qua chat
(Telegram, Google Chat), chạy **Claude Code CLI headless** sửa code trên repo của khách
(GitHub App), theo **quy trình có cổng người duyệt** (FSM): yêu cầu → phân tích → hỏi lại
→ trình kế hoạch → thực thi trên `dev` → kiểm thử deploy → nhân viên verify → manager
duyệt merge `main`.

> Kế hoạch & mốc M0→M7: [tasks/todo.md](tasks/todo.md). Quy ước & gotchas: [CLAUDE.md](CLAUDE.md).

## Trạng thái — M0→M7 ✅ + tính năng bổ sung

- **M0** Scaffold: FastAPI + Postgres + SQLAlchemy + Alembic + models + Docker.
- **M1** `claude_runner.py` — subprocess `claude -p`, permission-mode theo phase, timeout.
- **M2** `github_app.py` (JWT→installation token→PR) + `git_ops.py` (clone/push + pre-push hook chặn `main`).
- **M3** `channels/telegram.py` — webhook + polling mode, inline buttons, `/start <token>`, group chat.
- **M4** `orchestrator.py` — FSM đầy đủ (NEW→…→CLOSED), lưu requests/events/approvals.
- **M5** `prompts.py` + `parsing.py` — prompt từng phase + parser JSON fallback an toàn.
- **M6** `onboarding.py` + `dispatcher.py` — multi-tenant, roles, isolation/lock per repo.
- **M7** Docker compose + `.github/workflows/deploy.yml` + `scripts/seed.py`.
- **Google Chat** `channels/google_chat.py` — kênh thay thế Telegram; outbound async qua service account; JWT inbound verify.
- **Web wizard** `web/` + `github_oauth.py` + `provisioning.py` — self-service onboarding: GitHub OAuth → chọn repo → tạo bot → nhận deeplink (không cần chạy `seed.py`).
- **Multi-bot** `bot_registry.py` — mỗi tenant dùng bot chung (shared) hoặc BYO bot riêng (token BotFather mã hoá Fernet); route webhook `/webhook/telegram/{bot_id}`.
- **Deploy gate** `post_deploy.py` — sau merge vào `dev`, tự dò CI/deploy (GitHub Actions + curl trang dev); auto-fix tối đa N vòng; mời manager chỉ khi deploy xanh.
- **Reconcile** `reconcile.py` — dọn request "mồ côi" (code đã lên main nhưng FSM kẹt).
- **Recovery** `recovery.py` — khởi động lại: đóng request bị interrupt + rekick deploy đang chờ.

## Cấu trúc

```
app/
  main.py               # FastAPI: /webhook/telegram, /webhook/telegram/{id}, /webhook/google_chat,
                        #          /webhook/github, /healthz + lifespan (recovery + poller)
  config.py             # settings (pydantic-settings, đọc env)
  db.py                 # SQLAlchemy engine/session
  models.py             # tenants/repositories/bots/users/requests/request_events/approvals
  orchestrator.py       # FSM lifecycle — lõi nghiệp vụ
  dispatcher.py         # routing tin nhắn/nút bấm → orchestrator; multi-bot/tenant lookup
  claude_runner.py      # subprocess claude -p
  github_app.py         # JWT → installation token → clone/push/PR/merge
  git_ops.py            # clone/commit/push + pre-push hook chặn main
  github_oauth.py       # GitHub OAuth user-to-server (web wizard)
  onboarding.py         # create_tenant/create_user/add_repository
  provisioning.py       # web wizard → Tenant+Bot+User+setWebhook trong 1 transaction
  bot_registry.py       # lookup Bot row → build adapter; register_webhook
  token_crypto.py       # Fernet encrypt/decrypt token bot riêng
  container_provisioner.py  # (tier 2) spawn container riêng cho bot own+dedicated
  poller.py             # Telegram long-polling (TELEGRAM_MODE=polling)
  post_deploy.py        # deploy gate sau merge dev: poll Actions + curl + auto-fix
  reconcile.py          # dọn request mồ côi (dry-run / --apply)
  recovery.py           # khởi động: recover request bị interrupt + rekick pending deploy
  cleanup.py            # dọn workspace clone cũ
  admin_commands.py     # lệnh /admin (nội bộ)
  prompts.py            # system prompt từng phase
  parsing.py            # trích & validate khối json cuối từ output Claude
  channels/
    base.py             # ChannelAdapter protocol, InboundMessage, Button, Attachment
    telegram.py         # aiogram adapter (webhook + polling)
    google_chat.py      # Google Chat adapter (outbound async qua service account)
  web/
    routes.py           # web wizard: /, /login, /oauth/github/callback, /wizard, /dashboard, /logout
    session.py          # cookie phiên HMAC (không dùng itsdangerous)
    templates.py        # HTML render chuỗi (không dùng Jinja2)
alembic/                # migrations
deploy/
  Dockerfile            # image non-root (gosu node), Claude Code CLI + git + gh
  docker-compose.yml    # services: app + db (Postgres self-hosted)
  entrypoint.sh         # alembic upgrade head → uvicorn
  backup.sh             # pg_dump cron
  env.example           # template biến môi trường
  google-chat-setup.md  # hướng dẫn cấu hình Google Chat
  group-chat.md         # hướng dẫn dùng group Telegram
  self-service.md       # hướng dẫn bật web wizard
scripts/
  seed.py               # onboard tenant/repo/users thủ công (CLI)
  user.py               # thêm user vào tenant đã có
tests/                  # ~20 file, ~2700 LOC (parsing, runner, github, git, telegram, orchestrator,
                        #  dispatcher, provisioning, web, google_chat, post_deploy, reconcile, recovery…)
```

## Onboard — 2 cách

### A. Web wizard (khuyến nghị — không cần chạy lệnh)

Cấu hình `PUBLIC_BASE_URL`, `GITHUB_OAUTH_CLIENT_ID`, `GITHUB_OAUTH_CLIENT_SECRET`,
`GITHUB_APP_SLUG`, `WEB_SESSION_SECRET` (xem [deploy/self-service.md](deploy/self-service.md)).
Sau đó mở `https://<your-domain>/` → đăng nhập GitHub → chọn repo → chọn bot (shared hoặc
BYO) → nhận deeplink Telegram để gửi cho thành viên.

### B. Seed thủ công (CLI)

```bash
python -m scripts.seed --tenant "Acme" --repo acme/widgets --installation 12345 \
    --manager "Alice" --employee "Bob"
# In ra "/start <token>" hoặc deeplink t.me/... cho từng người → họ gửi cho bot Telegram để liên kết.

# Thêm user về sau:
python -m scripts.user --tenant-id 1 --name "Charlie" --role employee
```

## Luồng e2e

1. Nhân viên gửi yêu cầu (text, DM hoặc group @mention) → bot phân tích → **hỏi lại** (nếu mơ hồ) → trình **kế hoạch** + nút **✅ Confirm**.
2. Confirm → bot tạo nhánh `bot/req-<id>`, để Claude sửa code, push + mở **PR vào `dev`** → **deploy gate**: poll CI/GitHub Actions + curl trang dev; auto-fix nếu deploy lỗi.
3. Deploy xanh → nút **✅ Đạt / 🔧 Cần sửa / ❌ Huỷ** gửi nhân viên. ✅ Đạt → thông báo **manager** với nút **✅ Cho merge / ❌ Từ chối**.
4. Manager ✅ → merge `dev → main` → đóng request. (Chỉ `manager`/`admin` được duyệt.)

## Chạy local (dev)

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp deploy/env.example .env    # điền DATABASE_URL + CLAUDE_CODE_OAUTH_TOKEN + TELEGRAM_BOT_TOKEN

alembic upgrade head          # tạo schema
uvicorn app.main:app --reload # http://localhost:8000/healthz

pytest -q                     # ~20 test files (không cần DB thật)
```

Web wizard local (không cần GitHub OAuth thật):
```bash
WEB_DEV_LOGIN=true uvicorn app.main:app --reload
# Mở http://localhost:8000/dev/login → wizard với repo giả
```

## Chạy bằng Docker

```bash
cp deploy/env.example /etc/luna/luna.env   # điền secrets
docker compose -f deploy/docker-compose.yml up -d --build
```

Container chạy **non-root** (gosu user `node`) vì Claude từ chối `bypassPermissions` khi là root.
`entrypoint.sh` tự `alembic upgrade head` trước khi serve.

### Chế độ Telegram polling (VM khoá port inbound)

```bash
TELEGRAM_MODE=polling uvicorn app.main:app
# App tự getUpdates; không cần setWebhook và không cần port 443 mở.
```

## Biến môi trường chính

| Biến | Mô tả |
|------|-------|
| `DATABASE_URL` | Postgres connection string |
| `CLAUDE_CODE_OAUTH_TOKEN` | Token CLI Claude (subscription) |
| `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY_PATH` | GitHub App |
| `TELEGRAM_BOT_TOKEN` | Bot Telegram chung (shared) |
| `TELEGRAM_MODE` | `webhook` (mặc định) hoặc `polling` |
| `GOOGLE_CHAT_ENABLED` | `true` để bật kênh Google Chat |
| `GOOGLE_CHAT_SA_JSON` | Service account JSON (đường dẫn hoặc inline) |
| `PUBLIC_BASE_URL` | URL công khai — bật web wizard + webhook đa bot |
| `GITHUB_OAUTH_CLIENT_ID/SECRET` | GitHub App OAuth credentials |
| `GITHUB_APP_SLUG` | Slug GitHub App (bật nút "Cấp quyền repo" trong wizard) |
| `WEB_SESSION_SECRET` | Khoá ký cookie phiên web |
| `BOT_TOKEN_ENC_KEY` | Fernet key mã hoá token bot riêng (BYO) |
| `DEV_VERIFY_ENABLED` | `true` bật deploy gate sau merge dev (mặc định) |
| `DEV_VERIFY_MAX_ROUNDS` | Số vòng auto-fix tối đa khi deploy lỗi (mặc định 2) |

Xem đầy đủ: [deploy/env.example](deploy/env.example).

## Data model

```
tenants (owner_github_id, plan)
  ├── repositories (repo_full_name, base_branch, prod_branch, gh_installation_id, settings_json)
  ├── bots (platform, mode=shared|own, token_encrypted, deployment_mode, status)
  ├── users (role, platform_user_id, link_token, bot_id→bots, active_repo_id)
  └── requests (status→FSM, claude_session_id, branch_name, pr_number, dev_merge_sha)
        ├── request_events (kind, direction, payload_json)
        └── approvals (type=merge_to_main, decision)
```

`requests.status` chạy qua FSM `RequestStatus` (xem [app/models.py](app/models.py)):
`NEW → ANALYZING → (CLARIFYING ⇄ ANALYZING) → PLAN_REVIEW → EXECUTING → VERIFY →
MERGED_DEV → AWAIT_MANAGER → MERGED_MAIN → CLOSED`; bất kỳ đâu → `CANCELLED`.

## Tiện ích vận hành

```bash
# Dọn request "mồ côi" (code đã lên main nhưng FSM kẹt):
python -m app.reconcile           # dry-run — chỉ liệt kê
python -m app.reconcile --apply   # thực thi đóng + dọn nhánh
```
