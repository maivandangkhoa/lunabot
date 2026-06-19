"""HTML server-rendered cho web wizard (không Jinja2 — giữ dep tối thiểu).

Mỗi hàm trả 1 chuỗi HTML hoàn chỉnh; design system ở app/web/styles.py.
`esc()` chống XSS cho mọi giá trị động. Chữ ký hàm & các field POST GIỮ NGUYÊN
(landing/wizard/done/dashboard) để không đụng routes.py / backend.
"""
from __future__ import annotations

from html import escape as esc

from app.web.styles import brand, doc, icon, onboarding, shell

# ── Landing ───────────────────────────────────────────────────────────────────
_FLOW = ["Request", "Analyze", "Plan", "Approve", "Code", "Verify", "Merge"]


def landing(login_url: str, enabled: bool) -> str:
    if not enabled:
        body = (
            "<div class='ob-col'><div class='card'>"
            f"<div class='alert alert-danger'>{icon('alert', 18)}<div>"
            "<b>Web wizard chưa được cấu hình.</b><br>"
            "Thiếu GitHub OAuth / PUBLIC_BASE_URL — xem "
            "<span class='code'>deploy/self-service.md</span>.</div></div>"
            "</div></div>"
        )
        return onboarding("Luna", body)

    flow = ("<span class='flow'>" + f"{icon('arrow-right')}".join(
        f"<span class='fstep'>{esc(s)}</span>" for s in _FLOW) + "</span>")
    pills = "".join(
        f"<span class='pill'>{icon(ic)}{esc(t)}</span>" for ic, t in (
            ("shield", "Human-approved merges"),
            ("github", "Works on your repos"),
            ("zap", "Zero-setup shared bot"),
            ("users", "Team collaboration"),
        ))
    body = f"""
      <div class='ob-col ob-wide' style='text-align:center'>
        <span class='badge badge-info' style='margin-bottom:22px'>{icon('sparkles')}AI Engineering Platform</span>
        <h1 class='hero'>AI Maintenance Engineer<br>for your codebase</h1>
        <p class='muted' style='font-size:18px;max-width:560px;margin:18px auto 0'>
          Luna nhận yêu cầu bảo trì qua chat, tự phân tích, lập kế hoạch, viết code trên
          nhánh dev và chỉ merge production khi <b>người duyệt</b> đồng ý.</p>
        <div style='margin:30px 0 10px'>
          <a class='btn btn-github btn-lg' href='{esc(login_url)}'>{icon('github')}Tiếp tục với GitHub</a>
        </div>
        <p class='hint'>Miễn phí để bắt đầu · Không cần thẻ tín dụng</p>
        <div style='display:flex;justify-content:center'>{flow}</div>
        <div class='pills' style='justify-content:center'>{pills}</div>
      </div>"""
    return doc_landing(body)


def doc_landing(body: str) -> str:
    # Landing không có thanh đăng xuất; chỉ brand ở góc trái.
    bar = f"<div class='ob-bar'>{brand()}<a class='btn btn-ghost' href='/login'>Đăng nhập</a></div>"
    return doc("Luna — AI Maintenance Engineer", f"<div class='ob'>{bar}<div class='ob-wrap'>{body}</div></div>")


# ── Wizard (4 bước, 1 form — JS điều hướng, field POST không đổi) ──────────────
def _repo_options(repos: list[dict]) -> str:
    if not repos:
        return "<option value=''>— chưa có repo, hãy cài GitHub App —</option>"
    return "".join(
        f"<option value='{esc(r['full_name'])}|{r['installation_id']}'>{esc(r['full_name'])}</option>"
        for r in repos
    )


def _stepper(steps: list[str]) -> str:
    nodes = []
    for i, name in enumerate(steps):
        cls = "step-node current" if i == 0 else "step-node"
        if i:
            nodes.append("<span class='step-line'></span>")
        nodes.append(
            f"<div class='{cls}' data-node='{i}'>"
            f"<span class='step-num'>{i + 1}</span>"
            f"<span class='step-name'>{esc(name)}</span></div>")
    return f"<div class='stepper'>{''.join(nodes)}</div>"


def wizard(user_name: str, repos: list[dict], install_url: str, csrf: str,
           dedicated_enabled: bool, error: str | None = None) -> str:
    err = ""
    if error:
        err = (f"<div class='alert alert-danger' style='margin-bottom:18px'>"
               f"{icon('alert', 18)}<div>{esc(error)}</div></div>")

    connected = bool(repos)
    repo_status = (
        f"<span class='badge badge-success'>{icon('check')}Connected</span>" if connected
        else f"<span class='badge badge-warning'>Chưa kết nối</span>")
    install_label = "Quản lý repo trên GitHub" if connected else "Cài GitHub App"

    host_block = ""
    if dedicated_enabled:
        host_block = f"""
        <div class='field'><label>Hạ tầng chạy bot</label>
          <div class='choices'>
            <label class='choice'><input type='radio' name='hosting' value='shared_instance' checked>
              <span class='ch-tick'>{icon('check', 13)}</span>
              <span class='ch-title'>{icon('zap', 16)} Chạy chung</span>
              <span class='ch-desc'>Khuyến nghị — khởi động tức thì trên hạ tầng Luna.</span></label>
            <label class='choice'><input type='radio' name='hosting' value='dedicated_container'>
              <span class='ch-tick'>{icon('check', 13)}</span>
              <span class='ch-title'>{icon('shield', 16)} Container riêng</span>
              <span class='ch-desc'>Cô lập thật cho khối lượng công việc nhạy cảm.</span></label>
          </div></div>"""

    body = f"""
      <div class='ob-col ob-wide'>
        <h1 class='page-title'>Tạo bot bảo trì</h1>
        <p class='muted' style='margin:6px 0 22px'>Chào {esc(user_name)} 👋 — bốn bước là bot của bạn sẵn sàng.</p>
        {err}
        {_stepper(["Kết nối repo", "Loại bot", "Cấu hình", "Xác nhận"])}
        <form id='wf' class='card' method='post' action='/wizard/create' novalidate>
          <input type='hidden' name='csrf' value='{esc(csrf)}'>

          <section class='wstep show' data-step='0'>
            <h2 class='section-title'>{icon('github', 18)} Kết nối repository</h2>
            <p class='muted small' style='margin:6px 0 16px'>Cho phép Luna truy cập & bảo trì codebase của bạn một cách an toàn.</p>
            <div class='card card-tight card-row' style='justify-content:space-between'>
              <div class='card-row'><span class='ws-ico'>{icon('repo', 16)}</span>
                <div><div style='font-weight:600'>GitHub App</div>
                  <div class='hint' style='margin:0'>Cài/đổi quyền repo, rồi quay lại đây.</div></div></div>
              {repo_status}
            </div>
            <a class='btn btn-secondary' style='margin-top:14px' href='{esc(install_url)}'>{icon('plus', 16)}{install_label}</a>
            <div class='field'><label>Chọn repository</label>
              <select class='input' name='repo' id='f-repo' required>{_repo_options(repos)}</select></div>
          </section>

          <section class='wstep' data-step='1'>
            <h2 class='section-title'>Chọn loại bot</h2>
            <p class='muted small' style='margin:6px 0 16px'>Dùng bot Luna chung hoặc bot Telegram mang thương hiệu của bạn.</p>
            <div class='choices'>
              <label class='choice'><input type='radio' name='bot_choice' value='shared' id='bc-shared' checked>
                <span class='ch-tick'>{icon('check', 13)}</span>
                <span class='ch-title'>{icon('zap', 16)} Bot Luna chung
                  <span class='badge badge-info' style='margin-left:auto'>Khuyến nghị</span></span>
                <span class='ch-desc'>Không cần cài gì. Bắt đầu ngay trên hạ tầng Luna.</span></label>
              <label class='choice'><input type='radio' name='bot_choice' value='own' id='bc-own'>
                <span class='ch-tick'>{icon('check', 13)}</span>
                <span class='ch-title'>{icon('bot', 16)} Bot riêng</span>
                <span class='ch-desc'>Dùng tên & avatar Telegram của riêng bạn.</span></label>
            </div>
          </section>

          <section class='wstep' data-step='2'>
            <h2 class='section-title'>Cấu hình bot</h2>
            <div class='field'><label>Tên bot (hiển thị)</label>
              <input class='input' name='display_name' id='f-name' placeholder='vd: Bot bảo trì Shop'></div>
            <div class='field' id='token-field' style='display:none'>
              <label>Telegram token (BotFather)</label>
              <input class='input' name='bot_token' placeholder='123456:ABC-DEF…'>
              <div class='hint'>Telegram → <span class='code'>@BotFather</span> → <span class='code'>/newbot</span> → đặt tên → dán token.</div>
            </div>
            <div class='field-2'>
              <div class='field'><label>Nhánh làm việc (dev)</label>
                <input class='input' name='base_branch' id='f-base' value='dev'></div>
              <div class='field'><label>Nhánh production</label>
                <input class='input' name='prod_branch' id='f-prod' value='main'></div>
            </div>
            {host_block}
          </section>

          <section class='wstep' data-step='3'>
            <h2 class='section-title'>Xác nhận</h2>
            <p class='muted small' style='margin:6px 0 16px'>Kiểm tra lại trước khi tạo bot.</p>
            <div class='summary'>
              <div class='srow'><span>Repository</span><span id='r-repo'>—</span></div>
              <div class='srow'><span>Loại bot</span><span id='r-bot'>—</span></div>
              <div class='srow'><span>Nhánh dev → prod</span><span id='r-branch'>—</span></div>
              <div class='srow'><span>Quyền</span><span>Bảo trì code (GitHub App)</span></div>
              <div class='srow'><span>Quản lý</span><span>{esc(user_name)} (manager)</span></div>
              <div class='srow'><span>Quy trình duyệt</span><span>Bắt buộc duyệt merge production</span></div>
            </div>
          </section>

          <div class='wnav'>
            <button type='button' class='btn btn-ghost' id='w-back' style='display:none'>{icon('arrow-left', 16)}Quay lại</button>
            <span class='grow'></span>
            <button type='button' class='btn btn-primary' id='w-next'>Tiếp tục{icon('arrow-right', 16)}</button>
            <button type='submit' class='btn btn-primary btn-lg' id='w-submit' style='display:none'>{icon('sparkles', 16)}Tạo bot</button>
          </div>
        </form>
        <p class='hint' style='text-align:center;margin-top:16px'>
          <a href='/dashboard'>Xem bot đã tạo</a> · <a href='/logout'>Đăng xuất</a></p>
      </div>
      {_WIZARD_JS}"""
    return onboarding("Luna — cấu hình bot", body, user_name=user_name)


_WIZARD_JS = """
<script>
(function(){
  var steps=[].slice.call(document.querySelectorAll('.wstep'));
  var nodes=[].slice.call(document.querySelectorAll('.step-node'));
  var back=document.getElementById('w-back'),next=document.getElementById('w-next'),
      submit=document.getElementById('w-submit'),cur=0;
  var ownRadio=document.getElementById('bc-own'),tokenField=document.getElementById('token-field');
  function syncToken(){tokenField.style.display=ownRadio.checked?'block':'none';}
  [].forEach.call(document.querySelectorAll('input[name=bot_choice]'),function(r){r.addEventListener('change',syncToken);});
  syncToken();
  function valid(i){
    if(i===0){var s=document.getElementById('f-repo');if(!s.value){s.focus();return false;}}
    return true;
  }
  function review(){
    var sel=document.getElementById('f-repo');
    document.getElementById('r-repo').textContent=sel.value?sel.options[sel.selectedIndex].text:'—';
    document.getElementById('r-bot').textContent=ownRadio.checked?'Bot riêng (Telegram)':'Bot Luna chung';
    document.getElementById('r-branch').textContent=
      (document.getElementById('f-base').value||'dev')+' → '+(document.getElementById('f-prod').value||'main');
  }
  function show(i){
    cur=i;
    steps.forEach(function(s,k){s.classList.toggle('show',k===i);});
    nodes.forEach(function(n,k){n.className='step-node'+(k<i?' done':k===i?' current':'');});
    back.style.display=i===0?'none':'inline-flex';
    next.style.display=i===steps.length-1?'none':'inline-flex';
    submit.style.display=i===steps.length-1?'inline-flex':'none';
    if(i===steps.length-1)review();
    window.scrollTo({top:0,behavior:'smooth'});
  }
  next.addEventListener('click',function(){if(valid(cur))show(Math.min(cur+1,steps.length-1));});
  back.addEventListener('click',function(){show(Math.max(cur-1,0));});
  show(0);
})();
</script>"""


# ── Done ──────────────────────────────────────────────────────────────────────
def done(result, repo_full_name: str) -> str:
    deeplink = result.deeplink
    if deeplink.startswith("http"):
        cta = (f"<a class='btn btn-primary btn-lg btn-block' href='{esc(deeplink)}'>"
               f"{icon('send', 18)}Mở bot trong Telegram</a>")
    else:
        cta = (f"<div class='alert alert-success'>{icon('send', 18)}<div>Nhắn bot Luna chung: "
               f"<span class='code'>{esc(deeplink)}</span></div></div>")
    bot_label = ('@' + esc(result.bot_username)) if result.bot_username else 'Luna chung'
    body = f"""
      <div class='ob-col'>
        <div style='text-align:center;margin-bottom:8px'>
          <div class='dot dot-success' style='width:56px;height:56px;border-radius:18px;display:grid;
            place-items:center;margin:0 auto 18px;background:rgba(16,185,129,.14);box-shadow:none;color:#6EE7B7'>
            {icon('check-circle', 30)}</div>
          <h1 class='page-title'>Bot đã sẵn sàng 🎉</h1>
          <p class='muted' style='margin-top:6px'>Liên kết tài khoản chat rồi bắt đầu gửi yêu cầu bảo trì.</p>
        </div>
        <div class='card'>
          <div class='summary' style='margin-bottom:18px'>
            <div class='srow'><span>Repository</span><span>{esc(repo_full_name)}</span></div>
            <div class='srow'><span>Bot</span><span>{bot_label}</span></div>
            <div class='srow'><span>Loại</span><span>{esc(result.mode)}</span></div>
          </div>
          {cta}
          <p class='hint' style='text-align:center;margin-top:14px'>Lệnh liên kết thủ công:
            <span class='code'>/start {esc(result.link_token)}</span></p>
        </div>
        <p style='text-align:center;margin-top:18px'>
          <a class='btn btn-secondary' href='/dashboard'>{icon('dashboard', 16)}Về dashboard</a></p>
      </div>"""
    return onboarding("Luna — đã tạo bot", body)


# ── Dashboard (app shell có sidebar) ──────────────────────────────────────────
_STATUS_DOT = {
    "running": "dot-running", "executing": "dot-running", "analyzing": "dot-running",
    "active": "dot-success", "merged": "dot-success", "merged_main": "dot-success",
    "ready": "dot-success", "approved": "dot-success",
    "pending": "dot-warning", "await_manager": "dot-warning", "plan_review": "dot-warning",
    "failed": "dot-danger", "cancelled": "dot-danger",
}


def _bot_card(r: dict) -> str:
    username = ('@' + esc(r['username'])) if r['username'] else 'Luna chung'
    status = (r.get('status') or '').lower()
    dot = _STATUS_DOT.get(status, "")
    return f"""
      <div class='card card-tight card-row' style='justify-content:space-between'>
        <div class='card-row'>
          <span class='ws-ico' style='width:40px;height:40px'>{icon('bot', 20)}</span>
          <div>
            <div style='font-weight:600;font-size:15px'>{esc(r['name'])}</div>
            <div class='hint' style='margin:2px 0 0;display:flex;gap:8px;align-items:center'>
              {icon('repo', 13)}{esc(r['repo'])} · {username}</div>
          </div>
        </div>
        <div style='display:flex;align-items:center;gap:14px'>
          <span class='badge badge-muted'>{esc(r['mode'])} · {esc(r['deployment'])}</span>
          <span class='status'><span class='dot {dot}'></span>{esc(r['status'])}</span>
        </div>
      </div>"""


def dashboard(user_name: str, rows: list[dict]) -> str:
    head = f"""
      <div class='page-head'>
        <div><h1 class='page-title'>Bots</h1>
          <p class='muted' style='margin-top:4px'>Các bot bảo trì AI của bạn và trạng thái hiện tại.</p></div>
        <a class='btn btn-primary' href='/wizard'>{icon('plus', 16)}Tạo bot mới</a>
      </div>"""
    if rows:
        body = "<div class='stack-sm'>" + "".join(_bot_card(r) for r in rows) + "</div>"
    else:
        body = f"""
          <div class='card empty'>
            <div class='e-ico'>{icon('bot', 26)}</div>
            <h2 class='section-title'>Chưa có bot nào</h2>
            <p class='muted' style='max-width:380px;margin:8px auto 20px'>
              Tạo bot đầu tiên để Luna bắt đầu bảo trì codebase của bạn qua chat.</p>
            <a class='btn btn-primary' href='/wizard'>{icon('plus', 16)}Tạo bot đầu tiên</a>
          </div>"""
    return shell("Luna — Dashboard", active="bot", user_name=user_name, body=head + body)
