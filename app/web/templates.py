"""HTML server-rendered tối giản cho web wizard (không Jinja2 — giữ dep tối thiểu).

Mỗi hàm trả 1 chuỗi HTML hoàn chỉnh. `esc()` chống XSS cho mọi giá trị động.
"""
from __future__ import annotations

from html import escape as esc

_CSS = """
*{box-sizing:border-box} body{font-family:system-ui,Segoe UI,Roboto,sans-serif;max-width:640px;
margin:40px auto;padding:0 20px;color:#1b1b1f;line-height:1.5}
h1{font-size:1.6rem} .card{border:1px solid #e3e3e8;border-radius:12px;padding:20px;margin:16px 0}
a.btn,button{display:inline-block;background:#5b54e8;color:#fff;border:0;border-radius:8px;
padding:10px 18px;font-size:1rem;cursor:pointer;text-decoration:none}
a.btn.ghost{background:#fff;color:#5b54e8;border:1px solid #5b54e8}
label{display:block;margin:12px 0 4px;font-weight:600} input,select{width:100%;padding:9px;
border:1px solid #c8c8d0;border-radius:8px;font-size:1rem} .muted{color:#6b6b76;font-size:.9rem}
.code{background:#f4f4f7;border-radius:6px;padding:2px 6px;font-family:ui-monospace,monospace}
.ok{color:#0a7d33} .err{color:#c0392b} .radio{display:flex;gap:8px;align-items:flex-start;margin:8px 0}
.radio input{width:auto;margin-top:5px} fieldset{border:1px solid #e3e3e8;border-radius:8px;margin:14px 0}
"""


def _page(title: str, body: str) -> str:
    return (f"<!doctype html><html><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{esc(title)}</title><style>{_CSS}</style></head><body>{body}</body></html>")


def landing(login_url: str, enabled: bool) -> str:
    if not enabled:
        return _page("luna", "<h1>luna 🌙</h1><div class='card err'>Web wizard chưa được cấu hình "
                     "(thiếu GitHub OAuth / PUBLIC_BASE_URL). Xem deploy/self-service.md.</div>")
    return _page("luna — tạo bot bảo trì", f"""
      <h1>luna 🌙 — bot bảo trì repo của bạn</h1>
      <div class='card'>
        <p>Tạo một bot tự bảo trì code cho repo của bạn trong vài bước: đăng nhập GitHub,
        cấp quyền repo, chọn bot — xong là dùng được ngay qua Telegram.</p>
        <a class='btn' href='{esc(login_url)}'>Đăng nhập bằng GitHub</a>
      </div>""")


def _repo_options(repos: list[dict]) -> str:
    if not repos:
        return "<option value=''>(chưa có repo nào — bấm \"Cấp quyền repo\")</option>"
    return "".join(
        f"<option value='{esc(r['full_name'])}|{r['installation_id']}'>{esc(r['full_name'])}</option>"
        for r in repos
    )


def wizard(user_name: str, repos: list[dict], install_url: str, csrf: str,
           dedicated_enabled: bool, error: str | None = None) -> str:
    err = f"<div class='card err'>{esc(error)}</div>" if error else ""
    host_field = ""
    if dedicated_enabled:
        host_field = """
        <label>Hạ tầng</label>
        <div class='radio'><input type='radio' name='hosting' value='shared_instance' checked id='h1'>
          <label for='h1' style='font-weight:400'>Chạy chung (khuyến nghị)</label></div>
        <div class='radio'><input type='radio' name='hosting' value='dedicated_container' id='h2'>
          <label for='h2' style='font-weight:400'>Container riêng (cô lập thật)</label></div>"""
    return _page("luna — cấu hình bot", f"""
      <h1>Chào {esc(user_name)} 👋</h1>{err}
      <div class='card'>
        <a class='btn ghost' href='{esc(install_url)}'>＋ Cấp quyền repo (cài GitHub App)</a>
        <p class='muted'>Cài/đổi repo trên GitHub rồi quay lại đây — danh sách sẽ cập nhật.</p>
      </div>
      <form class='card' method='post' action='/wizard/create'>
        <input type='hidden' name='csrf' value='{esc(csrf)}'>
        <label>Repo</label>
        <select name='repo' required>{_repo_options(repos)}</select>

        <label>Tên bot (hiển thị)</label>
        <input name='display_name' placeholder='vd: Bot bảo trì shop'>

        <fieldset><legend>Loại bot</legend>
          <div class='radio'><input type='radio' name='bot_choice' value='shared' checked id='b1'>
            <label for='b1' style='font-weight:400'>Dùng bot Luna chung — không cần cài gì</label></div>
          <div class='radio'><input type='radio' name='bot_choice' value='own' id='b2'>
            <label for='b2' style='font-weight:400'>Bot riêng (tên/avatar của bạn)</label></div>
          <p class='muted'>Bot riêng: mở Telegram → <span class='code'>@BotFather</span> → <span class='code'>/newbot</span>
            → đặt tên → dán token vào ô dưới.</p>
          <label>Token bot riêng (BotFather)</label>
          <input name='bot_token' placeholder='123456:ABC-DEF... (để trống nếu dùng bot chung)'>
        </fieldset>

        <label>Nhánh làm việc / nhánh production</label>
        <input name='base_branch' value='dev' style='width:48%;display:inline-block'>
        <input name='prod_branch' value='main' style='width:48%;display:inline-block;float:right'>
        {host_field}
        <p style='margin-top:18px'><button type='submit'>Tạo bot</button></p>
        <p class='muted'>Bạn sẽ là <b>manager</b> của bot này (tự duyệt merge vào production).</p>
      </form>
      <p class='muted'><a href='/dashboard'>Xem bot đã tạo</a> · <a href='/logout'>Đăng xuất</a></p>""")


def done(result, repo_full_name: str) -> str:
    deeplink = result.deeplink
    link_html = (f"<a class='btn' href='{esc(deeplink)}'>Mở bot trong Telegram</a>"
                 if deeplink.startswith("http")
                 else f"<p>Nhắn bot Luna chung: <span class='code'>{esc(deeplink)}</span></p>")
    return _page("luna — đã tạo bot", f"""
      <h1 class='ok'>✅ Bot đã sẵn sàng!</h1>
      <div class='card'>
        <p><b>Repo:</b> {esc(repo_full_name)}</p>
        <p><b>Bot:</b> {('@' + esc(result.bot_username)) if result.bot_username else 'Luna chung'}
           &nbsp;<span class='muted'>(loại: {esc(result.mode)})</span></p>
        <p>Bấm nút dưới (hoặc gửi lệnh) để liên kết tài khoản chat của bạn rồi bắt đầu gửi yêu cầu bảo trì:</p>
        {link_html}
        <p class='muted'>Lệnh liên kết thủ công: <span class='code'>/start {esc(result.link_token)}</span></p>
      </div>
      <p class='muted'><a href='/dashboard'>Về dashboard</a></p>""")


def dashboard(user_name: str, rows: list[dict]) -> str:
    if rows:
        items = "".join(
            f"<div class='card'><b>{esc(r['name'])}</b> — {esc(r['repo'])}<br>"
            f"<span class='muted'>bot: {('@'+esc(r['username'])) if r['username'] else 'Luna chung'} · "
            f"{esc(r['mode'])}/{esc(r['deployment'])} · {esc(r['status'])}</span></div>"
            for r in rows
        )
    else:
        items = "<div class='card muted'>Chưa có bot nào.</div>"
    return _page("luna — dashboard", f"""
      <h1>Bot của {esc(user_name)}</h1>{items}
      <p><a class='btn' href='/wizard'>＋ Tạo bot mới</a> &nbsp;
         <a href='/logout'>Đăng xuất</a></p>""")
