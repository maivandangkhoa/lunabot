# Google Chat — hướng dẫn bật channel cho luna

Cho phép người dùng **không có Telegram** dùng luna qua Google Chat (Google Workspace).
Channel cài qua adapter, **FSM không đổi**. Webhook: `POST /webhook/google_chat`.

## 1. Google Cloud / Workspace
1. Mở (hoặc tạo) **Google Cloud project** trong cùng Workspace của khách → ghi lại
   **Project number** (Console → trang chủ project). Đây là `GOOGLE_CHAT_PROJECT_NUMBER`
   (audience verify JWT inbound).
2. **APIs & Services → Library → Google Chat API → Enable.**
3. **Service account**: IAM & Admin → Service Accounts → Create → tạo **key JSON** (tải về).
   - Lưu lên VM: `/etc/luna/google-chat-sa.json` (chmod 600, **không commit**).
   - luna tự ký JWT (scope `chat.bot`) từ key này để gọi Chat REST async — không cần
     google-auth, không cần OAuth consent.
4. **Chat API → Configuration** (trang cấu hình bot):
   - App name / Avatar / Description.
   - **Functionality**: bật *Receive 1:1 messages* (DM) (+ *Join spaces* nếu cần).
   - **Connection settings = HTTP endpoint URL** →
     `https://luna.example.com/webhook/google_chat`.
   - **Visibility**: domain hoặc nhóm cụ thể được phép dùng bot.
   - **KHÔNG cần** đăng ký slash command: người dùng gõ thẳng `/start <token>` dạng text.

## 2. Phơi webhook qua edge-caddy (subdomain)
- DNS: thêm `luna.example.com` → IP VM.
- Thêm 1 block vào Caddyfile của edge-caddy (reverse-proxy tới container luna, vd cổng 8000):

```caddy
luna.example.com {
    reverse_proxy 127.0.0.1:8000   # đổi theo port luna expose ra host
}
```
- Reload Caddy. TLS Let's Encrypt tự động. Chỉ `/webhook/google_chat` cần công khai;
  `/admin` vẫn để riêng tư (SSH tunnel) theo tasks/web-admin.md.

## 3. Bật trong luna
Trong `/etc/luna/luna.env`:
```
GOOGLE_CHAT_ENABLED=true
GOOGLE_CHAT_SA_JSON=/etc/luna/google-chat-sa.json
GOOGLE_CHAT_PROJECT_NUMBER=<project number bước 1>
```
Mount file SA vào container (compose `volumes`: `/etc/luna:/etc/luna:ro`). Restart luna.
> Để trống `GOOGLE_CHAT_PROJECT_NUMBER` ⇒ **bỏ verify JWT inbound** (chỉ dùng khi test nội bộ).

## 4. Onboarding user Google Chat
- Admin tạo user với `platform="google_chat"` (CLI `app/admin_commands` / web-admin) → lấy
  `link_token`.
- Người dùng **DM bot** (tìm app trong Google Chat) rồi gõ: `/start <token>`.
- Sau khi liên kết, gửi yêu cầu bảo trì như Telegram; nút Confirm/Verify/Approve hiện dưới
  dạng **card buttons**.

## 5. Kiểm thử nhanh
- `curl https://luna.example.com/healthz` → `{"status":"ok"}`.
- DM bot `/start <token>` → nhận "✅ Đã liên kết".
- Gửi 1 yêu cầu → bot phân tích → hiện card kế hoạch → bấm **Confirm** → tạo PR.

## Ghi chú kỹ thuật
- **Outbound async**: FSM trả lời sau vài phút ⇒ luna **ack 200 ngay** rồi xử lý nền, gửi
  lại qua Chat REST (`spaces/*/messages`). Map user→space bằng `spaces:findDirectMessage`.
- **Telegram & Google Chat chạy song song**: chọn theo `User.platform`. Tắt GChat =
  `GOOGLE_CHAT_ENABLED=false` (endpoint trả 404).
- **Bảo mật**: SA key & JWT **không bao giờ log**; verify JWT inbound khi có project number.
