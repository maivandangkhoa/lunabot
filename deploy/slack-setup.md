# Slack — hướng dẫn bật channel cho luna

Cho phép người dùng **không có Telegram** dùng luna qua Slack. Channel cài qua adapter,
**FSM không đổi**. Webhook (dùng chung 1 URL cho cả tin nhắn lẫn nút bấm):
`POST /webhook/slack`.

Chạy ở **webhook mode** (Events API + Interactivity), **không** dùng Socket Mode.

## 1. Tạo Slack App
1. Vào <https://api.slack.com/apps> → **Create New App** → *From scratch* → chọn workspace.
2. **Basic Information → App Credentials**: copy **Signing Secret** → `SLACK_SIGNING_SECRET`.

### OAuth & Permissions (scopes)
Trong **OAuth & Permissions → Scopes → Bot Token Scopes**, thêm:
- `chat:write` — gửi tin & Block Kit (bắt buộc).
- `im:history` — đọc tin nhắn DM 1:1 (bắt buộc cho luồng DM).
- `im:write` — mở/gửi DM.
- `app_mentions:read` — nhận `@luna` trong channel (nếu dùng trong channel).
- `channels:history` / `groups:history` — đọc tin trong channel/nhóm (chỉ khi dùng ngoài DM).
- `files:read` — tải ảnh người dùng gửi (chỉ khi cần nhận screenshot).

Sau đó **Install to Workspace** → copy **Bot User OAuth Token** (`xoxb-...`) →
`SLACK_BOT_TOKEN`.

### Event Subscriptions
1. Bật **Enable Events**.
2. **Request URL**: `https://luna.example.com/webhook/slack`.
   - luna tự trả `url_verification` challenge → Slack hiện *Verified* ngay
     (cần đã set `SLACK_ENABLED=true` + `SLACK_SIGNING_SECRET` và app đang chạy).
3. **Subscribe to bot events**: thêm
   - `message.im` — tin nhắn DM 1:1 (luồng chính).
   - `app_mention` — khi được `@luna` trong channel (tuỳ chọn).

### Interactivity & Shortcuts (nút bấm)
1. Bật **Interactivity**.
2. **Request URL**: `https://luna.example.com/webhook/slack` (cùng URL trên).
   - Bắt buộc để các nút *Xác nhận / Verify / Duyệt* (Block Kit) hoạt động.

### App Home → Messages Tab (BẮT BUỘC — nếu không sẽ không gõ được tin cho bot)
**Features → App Home → Show Tabs**:
1. Bật **Messages Tab**.
2. Tick **"Allow users to send Slash commands and messages from the messages tab"**.

> ⚠️ Thiếu bước này thì DM với bot hiện *"Sending messages to this app has been turned off"*
> và user không gõ được gì. Sau khi bật, đóng/mở lại DM để Slack cập nhật.

## 2. Phơi webhook qua edge-caddy (subdomain)
Giống các channel khác — chỉ `/webhook/slack` cần công khai:

```caddy
luna.example.com {
    reverse_proxy 127.0.0.1:8000   # đổi theo port luna expose ra host
}
```

Reload Caddy (TLS Let's Encrypt tự động).

## 3. Bật trong luna
Trong `/etc/luna/luna.env` trên VM (KHÔNG phải `.env` local):
```
SLACK_ENABLED=true
SLACK_BOT_TOKEN=xoxb-...
SLACK_SIGNING_SECRET=...
SLACK_VERIFY_ENFORCE=true
```
Rồi **recreate container** để nạp env mới (compose ở `~/luna/deploy`, cần `sudo`):
```
cd ~/luna/deploy && sudo docker compose up -d --force-recreate luna
```
> ⚠️ Gotcha (đã gặp với Zalo/Messenger): nếu chỉ sửa `.env` local mà không set trên VM
> `/etc/luna/luna.env` + recreate, endpoint sẽ **404** và Slack verify URL thất bại.

## 4. Kiểm tra nhanh trên VM (không cần Slack)
Xác nhận endpoint sống + chữ ký khớp trước khi bấm *Verify* bên Slack. Chạy trên VM:
```bash
SECRET=$(sudo docker exec luna printenv SLACK_SIGNING_SECRET)
TS=$(date +%s); BODY='{"type":"url_verification","challenge":"ok"}'
SIG="v0=$(printf 'v0:%s:%s' "$TS" "$BODY" | openssl dgst -sha256 -hmac "$SECRET" | sed 's/^.* //')"
curl -s -w ' | HTTP %{http_code}\n' -X POST http://127.0.0.1:8000/webhook/slack \
  -H 'Content-Type: application/json' -H "X-Slack-Signature: $SIG" \
  -H "X-Slack-Request-Timestamp: $TS" --data-binary "$BODY"
# Mong đợi: {"challenge":"ok"} | HTTP 200
```
- HTTP **404** = `SLACK_ENABLED` chưa true / chưa recreate.
- HTTP **403** = chữ ký sai (secret trong container khác secret bạn tính) — kiểm tra lại
  `SLACK_SIGNING_SECRET`.
- Container **không có** `python` trên PATH → dùng `python3` nếu cần.

## 5. Kiểm thử thực tế qua Slack
1. Trong Slack, mở DM với app luna → gửi `start <token>` (KHÔNG dấu `/`: Slack nuốt mọi tin
   bắt đầu bằng `/` thành slash-command của nó nên lệnh bot không tới. Adapter tự thêm lại `/`).
   Tương tự các lệnh khác gõ không dấu: `help`, `lang en`, `whoami`…
2. Gửi 1 yêu cầu → bot phải trả lời trong DM, kèm nút *Xác nhận*.
3. Bấm nút → không kẹt spinner, bot xử lý tiếp (ack qua HTTP 200 ở webhook).

## Ghi chú kỹ thuật
- **DM vs channel**: channel ID bắt đầu `D` = DM (luôn addressed); `C`/`G` = channel/nhóm
  (chỉ xử lý khi `@mention` hoặc bấm nút).
- **Chữ ký**: HMAC-SHA256 `v0:{ts}:{body}` với replay window 5 phút. Sai/thiếu → 403 khi
  `SLACK_VERIFY_ENFORCE=true`.
- **Ảnh đính kèm**: parse từ `event.files[]` (cần scope `files:read`); tải qua `url_private`
  với Bearer token.
- **Định dạng**: markdown bot → *mrkdwn* của Slack (`**` → `*`) trong `app/channels/formatting.py`.
- **Loop bot tự trả lời (đã xử lý trong code)**: `message.im` khiến Slack **echo lại chính
  tin bot vừa gửi** (event có `bot_id`). Code bỏ qua qua `InboundMessage.ignore` (xem
  `app/channels/slack.py`, `app/dispatcher.py`) — không cần cấu hình. Nếu tương lai bot vẫn
  tự trả lời mình → kiểm tra logic ignore này trước.
