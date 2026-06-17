# Dùng luna trong Group Chat

luna hỗ trợ chạy trong **group/space nhiều người**: câu trả lời + nút bấm (duyệt kế hoạch,
duyệt merge của manager) đăng **công khai trong group** để cả team nắm tiến trình. Mỗi user vẫn
có request riêng (bind theo người gửi). **Liên kết tài khoản (`/start`) và lệnh quản trị
(`/users`, `/invite`, …) chỉ làm khi nhắn riêng (DM)** để tránh lộ token.

## Telegram

1. **Liên kết tài khoản trước (DM):** mỗi thành viên nhắn riêng bot `/start <token>` (admin cấp
   qua `/invite`). User đã liên kết ở DM được nhận diện trong mọi group (Telegram user id ổn định).
2. **Add bot vào group.**
3. **Cho bot thấy tin nhắn** — chọn 1:
   - Tắt *Group Privacy* trong BotFather (`/setprivacy` → Disable) → bot nhận mọi tin, nhưng luna
     **chỉ xử lý** tin có @mention/command/reply tới bot; HOẶC
   - Giữ Privacy bật → **luôn @mention bot** (vd `@LunaMaiBot thêm cache cho API`).
4. **Mode webhook:** đặt `TELEGRAM_BOT_USERNAME=<username_không_@>` để bot nhận diện @mention.
   Mode polling tự lấy qua `getMe`, không cần.

Trong group: gửi yêu cầu bằng cách @mention bot. Duyệt kế hoạch / verify / huỷ: bấm nút trong
group hoặc trả lời từ khoá (`ok`/`sửa`/`huỷ`). **Phải có ≥1 manager trong group** để duyệt merge
`main` (yêu cầu duyệt chỉ đăng trong group, không DM manager). Request tạo từ DM thì vẫn DM manager.

## Google Chat

1. **Liên kết tài khoản trước (DM):** nhắn riêng app `/start <token>`.
2. **Add app vào space (ROOM).** Chat app chỉ nhận tin khi được **@mention** trong space — không
   cần cấu hình gì thêm cho việc "addressed".
3. Câu trả lời + cardsV2 (nút) đăng thẳng vào space. Manager duyệt merge ngay trong space.

## Giới hạn đã biết

- Một user có request đang mở ở group A, nhắn tiếp ở group B → bot vẫn trả lời về **group A**
  (một luồng/một request, theo `origin_chat_id`).
- Group **không có manager** → request kẹt ở `AWAIT_MANAGER` (không ai duyệt được). Thêm manager
  vào group hoặc nhờ admin can thiệp.
