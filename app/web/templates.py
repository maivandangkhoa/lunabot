"""HTML server-rendered cho web wizard (không Jinja2 — giữ dep tối thiểu).

Mỗi hàm trả 1 chuỗi HTML hoàn chỉnh; design system ở app/web/styles.py.
`esc()` chống XSS cho mọi giá trị động. Chữ ký hàm & các field POST GIỮ NGUYÊN
(landing/wizard/done/dashboard) để không đụng routes.py / backend.
"""
from __future__ import annotations

import json
from html import escape as esc

from app.web import landing_sections as lp
from app.web.i18n import t
from app.web.styles import brand, doc, icon, lang_switcher, onboarding, shell, status_dot

# ── Landing ───────────────────────────────────────────────────────────────────
_FLOW = ["flow.request", "flow.analyze", "flow.plan", "flow.approve", "flow.code",
         "flow.verify", "flow.merge"]


def landing(login_url: str, enabled: bool) -> str:
    if not enabled:
        body = (
            "<div class='ob-col'><div class='card'>"
            f"<div class='alert alert-danger'>{icon('alert', 18)}<div>"
            f"<b>{t('landing.disabled.title')}</b><br>"
            f"{t('landing.disabled.body')}"
            "<span class='code'>deploy/self-service.md</span>.</div></div>"
            "</div></div>"
        )
        return onboarding("Luna", body)

    flow = ("<span class='flow'>" + f"{icon('arrow-right')}".join(
        f"<span class='fstep'>{esc(t(k))}</span>" for k in _FLOW) + "</span>")
    pills = "".join(
        f"<span class='pill'>{icon(ic)}{esc(t(k))}</span>" for ic, k in (
            ("shield", "pill.approved"),
            ("github", "pill.repos"),
            ("zap", "pill.zerosetup"),
            ("users", "pill.team"),
        ))
    hero = f"""
      <div class='ob-wrap' style='padding-bottom:40px'>
        <div class='ob-col ob-wide' style='text-align:center'>
          <span class='badge badge-info' style='margin-bottom:22px'>{icon('sparkles')}{t('landing.badge')}</span>
          <h1 class='hero'>{t('landing.hero')}</h1>
          <p class='muted' style='font-size:18px;max-width:560px;margin:18px auto 0'>
            {t('landing.subtitle')}</p>
          <div style='margin:30px 0 10px'>
            <a class='btn btn-github btn-lg' href='{esc(login_url)}'>{icon('github')}{t('landing.cta_github')}</a>
          </div>
          <p class='hint'>{t('landing.hint_free')}</p>
          <div style='display:flex;justify-content:center'>{flow}</div>
          <div class='pills' style='justify-content:center'>{pills}</div>
        </div>
      </div>"""
    return doc_landing(hero + lp.sections(login_url))


def doc_landing(body: str) -> str:
    # Landing không có thanh đăng xuất; chỉ brand ở góc trái. Trang cuộn full-width.
    bar = (f"<div class='ob-bar'>{brand()}"
           f"<div style='display:flex;align-items:center;gap:12px'>{lang_switcher()}"
           f"<a class='btn btn-ghost' href='/login'>{t('common.login')}</a></div></div>")
    return doc(t("title.landing"),
               f"<div class='ob'>{bar}<main class='lp'>{body}</main></div>",
               extra_head=lp.LANDING_CSS)


# ── Wizard (4 bước, 1 form — JS điều hướng, field POST không đổi) ──────────────
def _repo_options(repos: list[dict]) -> str:
    if not repos:
        return f"<option value=''>{t('wizard.repo_empty')}</option>"
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


def _pf_choice(value: str, rid: str, ic: str, key: str, checked: bool = False) -> str:
    """1 radio chọn kênh chat trong wizard."""
    return (f"<label class='choice'><input type='radio' name='platform' value='{value}' "
            f"id='{rid}'{' checked' if checked else ''}>"
            f"<span class='ch-tick'>{icon('check', 13)}</span>"
            f"<span class='ch-title'>{icon(ic, 16)} {t('wizard.s1.platform.' + key)}</span>"
            f"<span class='ch-desc'>{t('wizard.s1.platform.' + key + '_desc')}</span></label>")


def wizard(user_name: str, repos: list[dict], install_url: str, csrf: str,
           dedicated_enabled: bool, gchat_enabled: bool = False,
           error: str | None = None, has_workspace: bool = False,
           zalo_enabled: bool = False, messenger_enabled: bool = False,
           slack_enabled: bool = False) -> str:
    err = ""
    if error:
        err = (f"<div class='alert alert-danger' style='margin-bottom:18px'>"
               f"{icon('alert', 18)}<div>{esc(error)}</div></div>")
    if has_workspace:
        err += (f"<div class='alert alert-info' style='margin-bottom:18px'>"
                f"{icon('info', 18)}<div>{t('wizard.have_ws')} "
                f"<a href='/repo/add'>{t('repos.add')}</a></div></div>")

    # Chọn kênh chat. Telegram luôn có; các kênh "bot chung" (GC/Zalo/Messenger) chỉ hiện khi bật.
    extra = []
    if gchat_enabled:
        extra.append(_pf_choice("google_chat", "pf-gchat", "chat", "gchat"))
    if zalo_enabled:
        extra.append(_pf_choice("zalo", "pf-zalo", "chat", "zalo"))
    if messenger_enabled:
        extra.append(_pf_choice("messenger", "pf-messenger", "chat", "messenger"))
    if slack_enabled:
        extra.append(_pf_choice("slack", "pf-slack", "chat", "slack"))
    if extra:
        platform_block = (
            f"<div class='field'><label>{t('wizard.s1.platform')}</label><div class='choices'>"
            + _pf_choice("telegram", "pf-telegram", "send", "telegram", checked=True)
            + "".join(extra) + "</div></div>")
    else:
        platform_block = "<input type='hidden' name='platform' value='telegram'>"

    connected = bool(repos)
    repo_status = (
        f"<span class='badge badge-success'>{icon('check')}{t('wizard.connected')}</span>" if connected
        else f"<span class='badge badge-warning'>{t('wizard.not_connected')}</span>")
    install_label = t("wizard.manage_repo") if connected else t("wizard.install_app")

    host_block = ""
    if dedicated_enabled:
        host_block = f"""
        <div class='field'><label>{t('wizard.hosting.label')}</label>
          <div class='choices'>
            <label class='choice'><input type='radio' name='hosting' value='shared_instance' checked>
              <span class='ch-tick'>{icon('check', 13)}</span>
              <span class='ch-title'>{icon('zap', 16)} {t('wizard.hosting.shared.title')}</span>
              <span class='ch-desc'>{t('wizard.hosting.shared.desc')}</span></label>
            <label class='choice'><input type='radio' name='hosting' value='dedicated_container'>
              <span class='ch-tick'>{icon('check', 13)}</span>
              <span class='ch-title'>{icon('shield', 16)} {t('wizard.hosting.dedicated.title')}</span>
              <span class='ch-desc'>{t('wizard.hosting.dedicated.desc')}</span></label>
          </div></div>"""

    body = f"""
      <div class='ob-col ob-wide'>
        <h1 class='page-title'>{t('wizard.title')}</h1>
        <p class='muted' style='margin:6px 0 22px'>{t('wizard.greeting', name=esc(user_name))}</p>
        {err}
        {_stepper([t('wizard.step.connect'), t('wizard.step.bottype'), t('wizard.step.config'), t('wizard.step.confirm')])}
        <form id='wf' class='card' method='post' action='/wizard/create' novalidate>
          <input type='hidden' name='csrf' value='{esc(csrf)}'>

          <section class='wstep show' data-step='0'>
            <h2 class='section-title'>{icon('github', 18)} {t('wizard.s0.title')}</h2>
            <p class='muted small' style='margin:6px 0 16px'>{t('wizard.s0.desc')}</p>
            <div class='card card-tight card-row' style='justify-content:space-between'>
              <div class='card-row'><span class='ws-ico'>{icon('repo', 16)}</span>
                <div><div style='font-weight:600'>GitHub App</div>
                  <div class='hint' style='margin:0'>{t('wizard.s0.ghapp_desc')}</div></div></div>
              {repo_status}
            </div>
            <a class='btn btn-secondary' style='margin-top:14px' href='{esc(install_url)}'>{icon('plus', 16)}{install_label}</a>
            <div class='field'><label>{t('wizard.s0.select')}</label>
              <select class='input' name='repo' id='f-repo' required>{_repo_options(repos)}</select></div>
          </section>

          <section class='wstep' data-step='1'>
            <h2 class='section-title'>{t('wizard.s1.title')}</h2>
            <p class='muted small' style='margin:6px 0 16px'>{t('wizard.s1.desc')}</p>
            {platform_block}
            <div class='choices'>
              <label class='choice'><input type='radio' name='bot_choice' value='shared' id='bc-shared' checked>
                <span class='ch-tick'>{icon('check', 13)}</span>
                <span class='ch-title'>{icon('zap', 16)} {t('wizard.s1.shared.title')}
                  <span class='badge badge-info' style='margin-left:auto'>{t('common.recommended')}</span></span>
                <span class='ch-desc'>{t('wizard.s1.shared.desc')}</span></label>
              <label class='choice' id='bc-own-label'><input type='radio' name='bot_choice' value='own' id='bc-own'>
                <span class='ch-tick'>{icon('check', 13)}</span>
                <span class='ch-title'>{icon('bot', 16)} {t('wizard.s1.own.title')}</span>
                <span class='ch-desc'>{t('wizard.s1.own.desc')}</span></label>
            </div>
            <div class='hint' id='shared-note' style='display:none;margin-top:12px'>
              {icon('info', 14)} {t('wizard.s1.sharedonly_note')}</div>
          </section>

          <section class='wstep' data-step='2'>
            <h2 class='section-title'>{t('wizard.s2.title')}</h2>
            <div class='field'><label>{t('wizard.s2.name')}</label>
              <input class='input' name='display_name' id='f-name' placeholder='{esc(t("wizard.s2.name_ph"))}'></div>
            <div class='field' id='token-field' style='display:none'>
              <label>{t('wizard.s2.token')}</label>
              <input class='input' name='bot_token' placeholder='123456:ABC-DEF…'>
              <div class='hint'>{t('wizard.s2.token_hint')}</div>
            </div>
            <div class='field-2'>
              <div class='field'><label>{t('wizard.s2.dev_branch')}</label>
                <input class='input' name='base_branch' id='f-base' value='dev'></div>
              <div class='field'><label>{t('wizard.s2.prod_branch')}</label>
                <input class='input' name='prod_branch' id='f-prod' value='main'></div>
            </div>
            <div class='field'>
              <label class='choice'><input type='checkbox' name='dev_mode' value='1'>
                <span class='ch-title'>{icon('zap', 16)} {t('wizard.s2.devmode')}</span>
                <span class='ch-desc'>{t('wizard.s2.devmode_desc')}</span></label>
              <div class='hint' style='margin-top:8px'>⚠️ {t('wizard.s2.devmode_warn')}</div>
            </div>
            {host_block}
          </section>

          <section class='wstep' data-step='3'>
            <h2 class='section-title'>{t('wizard.s3.title')}</h2>
            <p class='muted small' style='margin:6px 0 16px'>{t('wizard.s3.desc')}</p>
            <div class='summary'>
              <div class='srow'><span>{t('wizard.s3.repo')}</span><span id='r-repo'>—</span></div>
              <div class='srow'><span>{t('wizard.s3.bottype')}</span><span id='r-bot'>—</span></div>
              <div class='srow'><span>{t('wizard.s3.branch')}</span><span id='r-branch'>—</span></div>
              <div class='srow'><span>{t('wizard.s3.perm')}</span><span>{t('wizard.s3.perm_val')}</span></div>
              <div class='srow'><span>{t('wizard.s3.manager')}</span><span>{t('wizard.s3.manager_val', name=esc(user_name))}</span></div>
              <div class='srow'><span>{t('wizard.s3.flow')}</span><span>{t('wizard.s3.flow_val')}</span></div>
            </div>
          </section>

          <div class='wnav'>
            <button type='button' class='btn btn-ghost' id='w-back' style='display:none'>{icon('arrow-left', 16)}{t('common.back')}</button>
            <span class='grow'></span>
            <button type='button' class='btn btn-primary' id='w-next'>{t('common.next')}{icon('arrow-right', 16)}</button>
            <button type='submit' class='btn btn-primary btn-lg' id='w-submit' style='display:none'>{icon('sparkles', 16)}{t('wizard.create_btn')}</button>
          </div>
        </form>
        <p class='hint' style='text-align:center;margin-top:16px'>
          <a href='/dashboard'>{t('wizard.foot_view')}</a> · <a href='/logout'>{t('common.logout')}</a></p>
      </div>
      {_wizard_js()}"""
    return onboarding(t("title.wizard"), body, user_name=user_name)


def _wizard_js() -> str:
    # Nhãn review (cột phải step Xác nhận) dịch phía server rồi nhúng vào JS dạng chuỗi JSON.
    own = json.dumps(t("wizard.js.own"))
    shared = json.dumps(t("wizard.js.shared"))
    pf_tg = json.dumps(t("wizard.s1.platform.telegram"))
    return """
<script>
(function(){
  var steps=[].slice.call(document.querySelectorAll('.wstep'));
  var nodes=[].slice.call(document.querySelectorAll('.step-node'));
  var back=document.getElementById('w-back'),next=document.getElementById('w-next'),
      submit=document.getElementById('w-submit'),cur=0;
  var ownRadio=document.getElementById('bc-own'),sharedRadio=document.getElementById('bc-shared'),
      tokenField=document.getElementById('token-field');
  var ownLabel=document.getElementById('bc-own-label'),
      sharedNote=document.getElementById('shared-note');
  function curPlatform(){var r=document.querySelector('input[name=platform]:checked');return r?r.value:'telegram';}
  // GC/Zalo/Messenger = bot chung toàn cục → chỉ shared, không có bot riêng. Chỉ Telegram mới own.
  function sharedOnly(){return curPlatform()!=='telegram';}
  function platformLabel(){var r=document.querySelector('input[name=platform]:checked');
    if(!r)return __PF_TG__;var l=r.closest('.choice');var ti=l&&l.querySelector('.ch-title');
    return ti?ti.textContent.trim():r.value;}
  function syncPlatform(){
    if(sharedOnly()){if(ownLabel)ownLabel.style.display='none';if(sharedNote)sharedNote.style.display='flex';
      sharedRadio.checked=true;}
    else{if(ownLabel)ownLabel.style.display='';if(sharedNote)sharedNote.style.display='none';}
    syncToken();
  }
  function syncToken(){tokenField.style.display=(!sharedOnly()&&ownRadio.checked)?'block':'none';}
  [].forEach.call(document.querySelectorAll('input[name=bot_choice]'),function(r){r.addEventListener('change',syncToken);});
  [].forEach.call(document.querySelectorAll('input[name=platform]'),function(r){r.addEventListener('change',syncPlatform);});
  syncPlatform();
  function valid(i){
    if(i===0){var s=document.getElementById('f-repo');if(!s.value){s.focus();return false;}}
    return true;
  }
  function review(){
    var sel=document.getElementById('f-repo');
    document.getElementById('r-repo').textContent=sel.value?sel.options[sel.selectedIndex].text:'—';
    document.getElementById('r-bot').textContent=platformLabel()+' · '+(ownRadio.checked&&!sharedOnly()?__OWN__:__SHARED__);
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
</script>""".replace("__OWN__", own).replace("__SHARED__", shared) \
    .replace("__PF_TG__", pf_tg)


# ── Add repository (vào tenant đã có — KHÔNG provision bot/link mới) ───────────
def add_repo(user_name: str, tenants: list[dict], repos: list[dict], install_url: str,
             csrf: str, *, selected_tenant: str = "", error: str | None = None) -> str:
    err = ""
    if error:
        err = (f"<div class='alert alert-danger' style='margin-bottom:18px'>"
               f"{icon('alert', 18)}<div>{esc(error)}</div></div>")
    tenant_opts = "".join(
        f"<option value='{tn['id']}'{' selected' if str(tn['id']) == str(selected_tenant) else ''}>"
        f"{esc(tn['name'])}</option>" for tn in tenants)
    connected = bool(repos)
    repo_status = (
        f"<span class='badge badge-success'>{icon('check')}{t('wizard.connected')}</span>" if connected
        else f"<span class='badge badge-warning'>{t('wizard.not_connected')}</span>")
    install_label = t("wizard.manage_repo") if connected else t("wizard.install_app")
    head = (f"<div class='page-head'><div>"
            f"<h1 class='page-title'>{t('repoadd.title')}</h1>"
            f"<p class='muted' style='margin-top:4px'>{t('repoadd.subtitle')}</p></div></div>")
    body = f"""
      {head}
      {err}
      <form class='card' method='post' action='/repo/add' novalidate>
        <input type='hidden' name='csrf' value='{esc(csrf)}'>
        <div class='field'><label>{t('repoadd.tenant')}</label>
          <select class='input' name='tenant_id' required>{tenant_opts}</select></div>
        <div class='card card-tight card-row' style='justify-content:space-between'>
          <div class='card-row'><span class='ws-ico'>{icon('repo', 16)}</span>
            <div><div style='font-weight:600'>GitHub App</div>
              <div class='hint' style='margin:0'>{t('wizard.s0.ghapp_desc')}</div></div></div>
          {repo_status}
        </div>
        <a class='btn btn-secondary' style='margin-top:14px' href='{esc(install_url)}'>{icon('plus', 16)}{install_label}</a>
        <div class='field'><label>{t('repoadd.select')}</label>
          <select class='input' name='repo' required>{_repo_options(repos)}</select></div>
        <div class='field-2'>
          <div class='field'><label>{t('wizard.s2.dev_branch')}</label>
            <input class='input' name='base_branch' value='dev'></div>
          <div class='field'><label>{t('wizard.s2.prod_branch')}</label>
            <input class='input' name='prod_branch' value='main'></div>
        </div>
        <div class='wnav'>
          <a class='btn btn-ghost' href='/repositories'>{icon('arrow-left', 16)}{t('common.back')}</a>
          <span class='grow'></span>
          <button type='submit' class='btn btn-primary'>{icon('plus', 16)}{t('repoadd.btn')}</button>
        </div>
      </form>"""
    return shell(t("title.repo_add"), active="repo", user_name=user_name, body=body)


# ── Done ──────────────────────────────────────────────────────────────────────
def done(result, repo_full_name: str) -> str:
    deeplink = result.deeplink
    if deeplink.startswith("http"):
        cta = (f"<a class='btn btn-primary btn-lg btn-block' href='{esc(deeplink)}'>"
               f"{icon('send', 18)}{t('done.open_telegram')}</a>")
    else:
        # Bot chung không có deeplink riêng → hướng dẫn /start. Google Chat dùng thông điệp riêng.
        msg = t("done.gchat_msg") if result.platform == "google_chat" else t("done.shared_msg")
        cta = (f"<div class='alert alert-success'>{icon('send', 18)}<div>{msg}"
               f"<span class='code'>{esc(deeplink)}</span></div></div>")
    bot_label = ('@' + esc(result.bot_username)) if result.bot_username else t("common.luna_shared")
    body = f"""
      <div class='ob-col'>
        <div style='text-align:center;margin-bottom:8px'>
          <div class='dot dot-success' style='width:56px;height:56px;border-radius:18px;display:grid;
            place-items:center;margin:0 auto 18px;background:rgba(16,185,129,.14);box-shadow:none;color:#6EE7B7'>
            {icon('check-circle', 30)}</div>
          <h1 class='page-title'>{t('done.title')}</h1>
          <p class='muted' style='margin-top:6px'>{t('done.subtitle')}</p>
        </div>
        <div class='card'>
          <div class='summary' style='margin-bottom:18px'>
            <div class='srow'><span>{t('done.repo')}</span><span>{esc(repo_full_name)}</span></div>
            <div class='srow'><span>{t('done.bot')}</span><span>{bot_label}</span></div>
            <div class='srow'><span>{t('done.type')}</span><span>{esc(result.mode)}</span></div>
          </div>
          {cta}
          <p class='hint' style='text-align:center;margin-top:14px'>{t('done.manual')}
            <span class='code'>/start {esc(result.link_token)}</span></p>
        </div>
        <p style='text-align:center;margin-top:18px'>
          <a class='btn btn-secondary' href='/dashboard'>{icon('dashboard', 16)}{t('done.to_dashboard')}</a></p>
      </div>"""
    return onboarding(t("title.done"), body)


# ── Bots (app shell có sidebar) ───────────────────────────────────────────────
def _bot_card(r: dict) -> str:
    username = ('@' + esc(r['username'])) if r['username'] else t("common.luna_shared")
    dot = status_dot(r.get('status'))
    return f"""
      <div class='card card-tight card-row' style='justify-content:space-between;flex-wrap:wrap;gap:12px'>
        <div class='card-row' style='min-width:0'>
          <span class='ws-ico' style='width:40px;height:40px;flex:none'>{icon('bot', 20)}</span>
          <div style='min-width:0'>
            <div style='font-weight:600;font-size:15px'>{esc(r['name'])}</div>
            <div class='hint' style='margin:2px 0 0;display:flex;gap:8px;align-items:center;flex-wrap:wrap'>
              {icon('repo', 13)}<span style='word-break:break-all'>{esc(r['repo'])}</span> · {username}</div>
          </div>
        </div>
        <div style='display:flex;align-items:center;gap:14px;flex-wrap:wrap'>
          <span class='badge badge-muted'>{esc(r['mode'])} · {esc(r['deployment'])}</span>
          <span class='status'><span class='dot {dot}'></span>{esc(r['status'])}</span>
        </div>
      </div>"""


def bots(user_name: str, rows: list[dict]) -> str:
    head = f"""
      <div class='page-head'>
        <div><h1 class='page-title'>{t('dash.title')}</h1>
          <p class='muted' style='margin-top:4px'>{t('dash.subtitle')}</p></div>
        <a class='btn btn-primary' href='/wizard'>{icon('plus', 16)}{t('dash.new')}</a>
      </div>"""
    if rows:
        body = "<div class='stack-sm'>" + "".join(_bot_card(r) for r in rows) + "</div>"
    else:
        body = f"""
          <div class='card empty'>
            <div class='e-ico'>{icon('bot', 26)}</div>
            <h2 class='section-title'>{t('dash.empty.title')}</h2>
            <p class='muted' style='max-width:380px;margin:8px auto 20px'>
              {t('dash.empty.desc')}</p>
            <a class='btn btn-primary' href='/wizard'>{icon('plus', 16)}{t('dash.empty.cta')}</a>
          </div>"""
    return shell(t("title.bots"), active="bot", user_name=user_name, body=head + body)
