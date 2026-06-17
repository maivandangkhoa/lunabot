# Kế hoạch G — Google Chat channel cho luna

> ✅ **ĐÃ LIVE + E2E (2026-06-17)**. Chi tiết vận hành: memory `luna-deployment.md`.

## 🔧 TODO vận hành (deploy-only, KHÔNG đụng source code) — làm sau
- [ ] **Auto-renew cert Let's Encrypt cho `luna.example.com`.** Hiện cert pin file tại
  `/etc/caddy/certs/luna.crt|key` trên VM (edge-caddy), **không tự gia hạn** → ~90 ngày
  (hạn ~2026-09) hết → Google không tin cert → đứt webhook. Thuần hạ tầng, không sửa luna.
  Phương án (chọn 1):
  1. **Cron re-obtain bằng Caddy**: script bật tạm `auto_https ignore_loaded_certs` → reload
     → copy cert mới ra file → gỡ flag → reload. Chạy cron hàng tháng. (Khớp cách đã làm tay.)
  2. **certbot/acme.sh + DNS-01** (cần Cloudflare API token cho zone internal) → gia hạn cert
     vào `/etc/caddy/certs/`, cron `caddy reload`. Không cần mở port.
  3. Để Caddy tự quản `luna` (managed cert) — nhưng vướng wildcard origin che (đã thử, phải
     dùng global flag ảnh hưởng domain khác) → cân nhắc tách Caddyfile riêng cho luna.
  - Khuyến nghị: phương án 1 (đơn giản, đã có quy trình) hoặc 2 (sạch nhất nếu có CF token).

---

> Cho phép người dùng **không có Telegram** vẫn dùng luna qua **Google Chat** (Google
> Workspace). Tận dụng kiến trúc `ChannelAdapter` sẵn có: thêm 1 adapter, **FSM không đổi**.
>
> Quyết định đã chốt: có **Google Workspace + GCP** (service account, async outbound) ·
> phơi webhook qua **subdomain edge-caddy** · viết plan trước rồi mới code.

## Vì sao "thêm adapter" là đủ
- Orchestrator/FSM chỉ nói qua `ChannelAdapter` ([app/channels/base.py](../app/channels/base.py)).
- Dispatcher ([app/dispatcher.py](../app/dispatcher.py)) đã nhận `adapter` chung — gần như không sửa.
- Identity sẵn sàng: `User.platform` + unique `(platform, platform_user_id)`
  ([app/models.py:141](../app/models.py#L141)); `link_user`/`get_user_by_platform` tái dùng nguyên.

## Khác biệt Telegram ↔ Google Chat (cốt lõi của adapter)
| Khái niệm | Telegram | Google Chat |
|---|---|---|
| Inbound | `message` / `callback_query` | event `MESSAGE` / `CARD_CLICKED` (POST JSON) |
| User ID | `from.id` | `user.name` = `users/123…` |
| Nơi gửi (chat_id) | `chat.id` | `space.name` = `spaces/AAA…` |
| Nút bấm | `inline_keyboard` + `callback_data` | `cardsV2` → button `onClick.action.function` + `parameters` |
| Click nút → | `callback_query.data` | event `CARD_CLICKED`, đọc `common.parameters` (giữ y format `action:rid`) |
| answer_callback | `answerCallbackQuery` (tắt spinner) | **không có** → no-op |
| Outbound async | bot token | **service account JSON** (OAuth2, scope `chat.bot`) gọi Chat REST |
| Giới hạn tin | 4096 ký tự | ~4096/text widget — vẫn chunk |

**Điểm khác lớn nhất:** FSM gửi tin **sau vài phút** (Claude chạy xong) ⇒ KHÔNG thể trả
trong HTTP response webhook (đã đóng) ⇒ **bắt buộc dùng Chat REST API + service account**
để gọi `spaces.messages.create`. Cần map `platform_user_id` → `space.name` (lưu space khi
user nhắn lần đầu; xem G2).

## Thiết kế adapter `app/channels/google_chat.py`
Hiện thực protocol `ChannelAdapter`, dùng `httpx` (đồng bộ phong cách `telegram.py`,
test bằng `httpx.MockTransport`). Auth: service account → access token (cache theo TTL).

```
@dataclass
class GoogleChatAdapter:
    sa_credentials: dict          # service account JSON (từ env/secret, KHÔNG log)
    client: httpx.AsyncClient | None = None
    name: str = "google_chat"

    def parse_inbound(raw) -> InboundMessage   # MESSAGE & CARD_CLICKED → chuẩn hoá
    async def send(platform_user_id, text, buttons)   # gọi spaces.messages.create
    async def answer_callback(callback_id, text=None)  # no-op (return {})
```
- `parse_inbound`: `platform_user_id = raw["user"]["name"]`; `chat_id = raw["space"]["name"]`;
  với `CARD_CLICKED` lấy `callback_data` từ `common.parameters`.
- `send`: dựng `text` + (tuỳ chọn) `cardsV2` buttons; cần `space.name` → tra từ DB (G2).
- Token: JWT service account → OAuth2 token endpoint; cache tới hết TTL (~1h), refresh trước hạn.
  (Có thể dùng `google-auth` lib thay vì tự ký — cân nhắc thêm 1 dependency vs tự viết PyJWT.)

## Endpoint `/webhook/google_chat` ([app/main.py](../app/main.py))
- Verify **Bearer JWT của Google** trong header `Authorization` (issuer
  `chat@system.gserviceaccount.com`, audience = project number/URL bot). Reject nếu sai.
- Parse body → `handle_google_chat_update(db, adapter, github, raw)` (đổi tên/generalize
  `handle_telegram_update`, xem G1).
- Trả `200` (body rỗng hoặc message ngắn) — FSM trả lời thật qua REST async.

## Sửa nhỏ ở dispatcher
- `handle_telegram_update` → đổi tên **`handle_channel_update`** (đã generic, chỉ là tên).
- `callback_id`: Google Chat không có → `getattr(adapter, "callback_id", …)` trả `None`,
  `answer_callback` no-op. Không cần đổi logic.
- Linking: Google Chat **không có deep-link** như Telegram. User gõ `/start <token>` (slash
  command GChat hoặc text thường) → `_handle_start` tái dùng nguyên. Cần đăng ký slash
  command `/start` ở cấu hình bot (hoặc chấp nhận text `/start <token>`).

## Onboarding / DB
- `create_user(..., platform="google_chat")` — đã hỗ trợ ([onboarding.py:38](../app/onboarding.py#L38)).
- **Cần lưu `space.name`** để gửi async: thêm cột `chat_space_id` vào `users` (nullable) qua
  Alembic migration mới `0003_user_chat_space`; set khi nhận inbound đầu tiên. (FSM gửi theo
  `platform_user_id`, adapter map → space; nếu chưa có space ⇒ chưa nhắn bot lần nào.)

## Config mới ([app/config.py](../app/config.py))
- `GOOGLE_CHAT_ENABLED=true|false`
- `GOOGLE_CHAT_SA_JSON` (đường dẫn file hoặc JSON inline; secret, không log)
- `GOOGLE_CHAT_PROJECT_NUMBER` (verify audience JWT)
- Giữ Telegram chạy song song — chọn kênh theo `User.platform`, hai webhook độc lập.

## Hạ tầng (Google Cloud — checklist, ngoài code)
1. Tạo/dùng GCP project; **bật Google Chat API**.
2. **Configuration** trong Chat API: tên bot, avatar, **Connection = HTTP endpoint** →
   URL = `https://luna.example.com/webhook/google_chat`.
3. Tạo **service account** + key JSON → nạp vào luna qua secret (`/etc/luna`).
4. Cấp quyền bot trong Workspace (visibility: domain hoặc nhóm cụ thể).
5. (Tuỳ) đăng ký slash command `/start`.

## Phơi ra ngoài — subdomain edge-caddy
- Thêm DNS `luna.example.com` → VM.
- 1 block Caddy reverse-proxy `luna.example.com → 127.0.0.1:<port luna>` (TLS tự động).
- Chỉ cần expose `/webhook/google_chat` (và `/webhook/telegram` nếu muốn chuyển Telegram
  sang webhook). `/admin` vẫn giữ riêng tư (SSH tunnel) theo plan web-admin.

## Mốc xây dựng (mỗi mốc chạy/test được, dừng review)
- **G0 — Adapter + unit test (offline):** `google_chat.py` (`parse_inbound`/`send`/`answer_callback`)
  + token service account; test bằng `httpx.MockTransport`, fixture event MESSAGE/CARD_CLICKED.
  Chưa cần GCP.
- **G1 — Endpoint + dispatcher generalize:** `/webhook/google_chat` + verify JWT;
  `handle_telegram_update → handle_channel_update`; TestClient test (verify, link, callback).
- **G2 — Persist space + async outbound:** migration `chat_space_id`, map khi inbound,
  adapter `send` dùng space; test FSM gửi tin sau khi resume.
- **G3 — Config + wiring 2 kênh:** settings, bật/tắt qua env, Telegram + GChat song song.
- **G4 — Deploy:** GCP bot config + service account secret + Caddy subdomain; e2e thật
  (link user GChat → tạo request → duyệt nút Card → merge dev).

## Test
- Unit: `parse_inbound` cho MESSAGE & CARD_CLICKED; `send` dựng payload `cardsV2` đúng;
  chunk tin dài; token cache/refresh.
- Integration (TestClient): reject JWT sai; `/start <token>` link; callback `action:rid`
  route đúng `handle_callback`; RBAC cross-tenant chặn (tái dùng fixture SQLite + fakes).

## Câu hỏi mở (chốt khi vào code)
1. Tự ký JWT service account (PyJWT, đã có) **hay** thêm dependency `google-auth`?
2. `/start` qua **slash command GChat** hay chấp nhận text `/start <token>`?
3. Có chuyển luôn Telegram sang webhook (vì đã có subdomain) hay giữ polling?
