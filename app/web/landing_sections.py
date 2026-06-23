"""Các section marketing cho landing page (kiến trúc, isolation, đa kênh, mobile flow).

Tách khỏi templates.py để giữ mỗi file ≤500 LOC. `LANDING_CSS` được inject qua
`doc(..., extra_head=...)`. HTML tĩnh (không nhận giá trị động ngoài login_url ở CTA).
Các "screenshot" là mockup CSS/SVG thuần — không cần asset ngoài.
"""
from __future__ import annotations

from html import escape as esc

from app.web.i18n import t
from app.web.styles import icon

LANDING_CSS = """<style>
.lp{position:relative;z-index:1}
.lp-section{padding:76px 0;border-top:1px solid var(--border)}
.lp-inner{max-width:1080px;margin:0 auto;padding:0 24px}
.lp-head{text-align:center;max-width:680px;margin:0 auto 48px}
.lp-eyebrow{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:600;
  letter-spacing:.06em;text-transform:uppercase;color:var(--primary-hover);margin-bottom:14px}
.lp-eyebrow svg{width:15px;height:15px}
.lp-title{font-size:34px;font-weight:700;letter-spacing:-.02em;line-height:1.15}
.lp-sub{color:var(--text-2);font-size:17px;line-height:1.6;margin-top:14px}

/* Architecture pipeline */
.arch{display:grid;grid-template-columns:1fr auto 1fr auto 1fr;align-items:center;gap:0}
.arch-node{background:var(--surface);border:1px solid var(--border);border-radius:16px;
  padding:22px 20px;text-align:center;box-shadow:var(--shadow);height:100%}
.arch-node.hl{border-color:rgba(99,102,241,.5);background:linear-gradient(180deg,var(--primary-soft),var(--surface));
  box-shadow:0 0 0 1px rgba(99,102,241,.25),0 20px 50px -24px var(--primary)}
.arch-ico{width:46px;height:46px;border-radius:13px;margin:0 auto 14px;display:grid;place-items:center;
  background:var(--elevated);border:1px solid var(--border);color:var(--primary-hover)}
.arch-node.hl .arch-ico{background:var(--primary);color:#fff;border-color:transparent}
.arch-node h3{font-size:17px;font-weight:600}
.arch-node p{font-size:13px;color:var(--text-2);margin-top:6px;line-height:1.5}
.arch-tags{display:flex;flex-wrap:wrap;gap:5px;justify-content:center;margin-top:12px}
.arch-tags span{font-size:11px;font-weight:600;padding:3px 8px;border-radius:999px;
  background:var(--elevated);border:1px solid var(--border);color:var(--text-2)}
.arch-arrow{color:var(--text-3);padding:0 14px}
.arch-arrow svg{width:26px;height:26px}

/* Split: phone mockup + copy */
.split{display:grid;grid-template-columns:380px 1fr;gap:56px;align-items:center}
.split.rev{grid-template-columns:1fr 380px}
.split.rev .split-visual{order:2}
.split-copy h2{font-size:30px;font-weight:700;letter-spacing:-.02em;line-height:1.2}
.split-copy .lp-sub{margin-top:14px}
.feat-list{margin-top:24px;display:grid;gap:14px}
.feat-row{display:flex;gap:13px;align-items:flex-start}
.feat-ico{width:32px;height:32px;border-radius:9px;flex:none;display:grid;place-items:center;
  background:var(--primary-soft);color:var(--primary-hover);border:1px solid rgba(99,102,241,.3)}
.feat-row b{font-size:15px;font-weight:600}
.feat-row p{font-size:14px;color:var(--text-2);margin-top:2px;line-height:1.5}

/* Phone */
.phone{width:340px;margin:0 auto;border-radius:46px;background:linear-gradient(160deg,#1c2436,#0a0e18);
  border:1px solid var(--border-2);padding:13px;box-shadow:0 40px 90px -30px rgba(0,0,0,.85),0 0 0 1px rgba(255,255,255,.04)}
.phone-screen{border-radius:34px;overflow:hidden;background:#0c111c;position:relative}
.phone-notch{position:absolute;top:0;left:50%;transform:translateX(-50%);width:120px;height:24px;
  background:#0a0e18;border-radius:0 0 16px 16px;z-index:3}
.chat-hd{display:flex;align-items:center;gap:10px;padding:16px 16px 12px;
  background:rgba(17,24,39,.9);border-bottom:1px solid var(--border)}
.chat-hd .av{width:34px;height:34px;border-radius:999px;display:grid;place-items:center;color:#fff;
  background:linear-gradient(135deg,var(--primary),#8B5CF6)}
.chat-hd .nm{font-size:14px;font-weight:600}
.chat-hd .st{font-size:11px;color:var(--success);display:flex;align-items:center;gap:5px}
.chat-hd .st i{width:6px;height:6px;border-radius:999px;background:var(--success);display:block}
.chat{padding:16px 14px;display:flex;flex-direction:column;gap:9px;height:476px;overflow:hidden;
  background:radial-gradient(120% 80% at 50% 0,rgba(99,102,241,.08),transparent 60%)}
.msg{max-width:84%;padding:9px 12px;border-radius:15px;font-size:12.5px;line-height:1.45;
  box-shadow:0 1px 2px rgba(0,0,0,.3)}
.msg .who{font-size:10px;font-weight:700;opacity:.8;margin-bottom:3px;display:flex;align-items:center;gap:5px}
.msg.in{background:var(--elevated);align-self:flex-start;border-bottom-left-radius:5px;border:1px solid var(--border)}
.msg.out{background:var(--primary);color:#fff;align-self:flex-end;border-bottom-right-radius:5px}
.msg.sys{align-self:center;background:transparent;border:1px dashed var(--border-2);color:var(--text-2);
  font-size:11px;padding:5px 11px;border-radius:999px;box-shadow:none}
.msg .mini{margin-top:6px;display:flex;gap:6px}
.msg .mini b{padding:5px 11px;border-radius:9px;font-size:11px;font-weight:600}
.msg .mini .yes{background:var(--success);color:#04130c}
.msg .mini .no{background:rgba(255,255,255,.12);color:#fff}
.msg code{background:rgba(0,0,0,.22);padding:1px 5px;border-radius:5px;font-size:11px}

/* Tenant isolation lanes */
.lanes{display:grid;gap:13px;max-width:780px;margin:0 auto}
.lane{display:flex;align-items:center;gap:16px;padding:15px 18px;border-radius:14px;
  border:1px solid var(--border);background:var(--surface)}
.lane .who{display:flex;align-items:center;gap:11px;width:190px;flex:none}
.lane .av{width:38px;height:38px;border-radius:10px;display:grid;place-items:center;font-weight:700;font-size:14px;color:#fff}
.lane .nm{font-size:14px;font-weight:600}.lane .nm small{display:block;color:var(--text-3);font-weight:500;font-size:11px}
.lane .wall{flex:1;display:flex;align-items:center;gap:10px;color:var(--text-3);font-size:12px}
.lane .wall .bar{flex:1;height:1px;background:repeating-linear-gradient(90deg,var(--border-2) 0 6px,transparent 6px 12px)}
.lane .box{display:flex;align-items:center;gap:8px;padding:8px 12px;border-radius:10px;
  background:var(--elevated);border:1px solid var(--border);font-size:12px;font-weight:600;font-family:ui-monospace,monospace}
.lane .box svg{width:14px;height:14px;color:var(--success)}
.iso-points{display:grid;grid-template-columns:repeat(2,1fr);gap:14px;max-width:780px;margin:34px auto 0}
.iso-pt{display:flex;gap:12px;align-items:flex-start;padding:16px;border-radius:13px;
  border:1px solid var(--border);background:var(--surface)}
.iso-pt .pi{width:34px;height:34px;border-radius:9px;flex:none;display:grid;place-items:center;
  background:rgba(16,185,129,.12);color:#6EE7B7;border:1px solid rgba(16,185,129,.3)}
.iso-pt b{font-size:14px;font-weight:600}.iso-pt p{font-size:13px;color:var(--text-2);margin-top:3px;line-height:1.5}

/* Channels */
.chan-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;max-width:760px;margin:0 auto}
.chan{padding:24px;border-radius:16px;border:1px solid var(--border);background:var(--surface);box-shadow:var(--shadow)}
.chan .top{display:flex;align-items:center;gap:13px;margin-bottom:12px}
.chan .ci{width:44px;height:44px;border-radius:12px;display:grid;place-items:center;color:#fff}
.chan h3{font-size:17px;font-weight:600}
.chan p{font-size:14px;color:var(--text-2);line-height:1.55}
.chan .tags{display:flex;flex-wrap:wrap;gap:6px;margin-top:14px}
.chan .tags span{font-size:12px;font-weight:500;padding:4px 10px;border-radius:999px;
  background:var(--elevated);border:1px solid var(--border);color:var(--text-2)}
.chan-soon{max-width:760px;margin:22px auto 0;text-align:center}
.chan-soon .cs-label{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:600;
  letter-spacing:.05em;text-transform:uppercase;color:var(--text-3)}
.chan-soon .cs-label svg{color:var(--primary)}
.cs-list{display:flex;flex-wrap:wrap;justify-content:center;gap:10px;margin-top:14px}
.cs{display:inline-flex;align-items:center;gap:9px;padding:8px 15px 8px 8px;border-radius:999px;
  border:1px solid var(--border);background:var(--surface);font-size:13px;font-weight:500;color:var(--text-2)}
.cs i{width:24px;height:24px;border-radius:7px;display:grid;place-items:center;font-size:12px;font-weight:700;font-style:normal;color:#fff}

/* Browser mockup (dashboard preview) */
.browser{border-radius:16px;border:1px solid var(--border);overflow:hidden;
  box-shadow:0 40px 90px -40px rgba(0,0,0,.8);background:var(--bg);max-width:900px;margin:0 auto}
.browser-bar{display:flex;align-items:center;gap:8px;padding:12px 16px;border-bottom:1px solid var(--border);background:var(--elevated)}
.browser-dot{width:11px;height:11px;border-radius:999px;background:var(--text-3);opacity:.6}
.browser-url{flex:1;margin-left:10px;height:26px;border-radius:7px;background:var(--surface);
  border:1px solid var(--border);display:flex;align-items:center;padding:0 12px;font-size:12px;color:var(--text-3)}
.browser-body{padding:22px;background:var(--bg)}
.bp-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:16px}
.bp-head h4{font-size:20px;font-weight:700}
.bp-pill{font-size:12px;font-weight:600;padding:7px 13px;border-radius:9px;background:var(--primary);color:#fff}
.bp-row{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:13px 15px;
  border-radius:11px;border:1px solid var(--border);background:var(--surface);margin-bottom:9px}
.bp-row .l{display:flex;align-items:center;gap:11px;min-width:0}
.bp-row .bi{width:34px;height:34px;border-radius:9px;flex:none;display:grid;place-items:center;
  background:var(--elevated);border:1px solid var(--border);color:var(--text-2)}
.bp-row .nm{font-size:14px;font-weight:600}.bp-row .sub{font-size:12px;color:var(--text-3)}
.bp-st{display:flex;align-items:center;gap:7px;font-size:12.5px;color:var(--text-2);white-space:nowrap}
.bp-st i{width:8px;height:8px;border-radius:999px;display:block}

/* Final CTA */
.lp-cta{text-align:center;background:linear-gradient(180deg,var(--primary-soft),transparent);
  border-radius:24px;border:1px solid rgba(99,102,241,.25);padding:56px 28px;margin:0 24px}
.lp-foot{text-align:center;color:var(--text-3);font-size:13px;padding:36px 24px 56px}

/* iPhone demo — tin nhắn đến dần dần (CSS thuần, không file video) */
.demo-wrap{max-width:356px;margin:0 auto;padding:0 8px}
.iphone{position:relative;width:100%;max-width:340px;margin:0 auto;border-radius:54px;
  background:linear-gradient(155deg,#3a4255,#0b0f17 62%);padding:13px;
  box-shadow:0 50px 120px -34px rgba(0,0,0,.92),0 0 0 1px rgba(255,255,255,.06),inset 0 1px 1px rgba(255,255,255,.14)}
.iphone::after{content:"";position:absolute;inset:6px;border-radius:48px;pointer-events:none;z-index:9;
  border:1px solid rgba(255,255,255,.05)}
.iscreen{position:relative;border-radius:44px;overflow:hidden;background:#0b0f17;height:740px;display:flex;flex-direction:column}
.island{position:absolute;top:12px;left:50%;transform:translateX(-50%);width:104px;height:30px;border-radius:999px;
  background:#000;z-index:8;box-shadow:0 0 0 1px rgba(255,255,255,.06)}
.istatus{display:flex;align-items:center;justify-content:space-between;padding:15px 24px 8px;
  font-size:13px;font-weight:600;color:#fff;position:relative;z-index:6}
.istatus .rt{display:flex;align-items:center;gap:6px}.istatus svg{display:block}
.ihead{display:flex;align-items:center;gap:11px;padding:5px 16px 11px;border-bottom:1px solid var(--border);
  background:rgba(17,24,39,.5);position:relative;z-index:5}
.ihead .av{width:36px;height:36px;border-radius:999px;display:grid;place-items:center;color:#fff;
  background:linear-gradient(135deg,var(--primary),#8B5CF6)}
.ihead .nm{font-size:14px;font-weight:600;line-height:1.2}
.ihead .st{font-size:11px;color:var(--success);display:flex;align-items:center;gap:5px;margin-top:1px}
.ihead .st i{width:6px;height:6px;border-radius:999px;background:var(--success);display:block}
.ibody{flex:1;overflow:hidden;position:relative}
.ifeed{position:absolute;inset:0;padding:16px 13px 16px;display:flex;flex-direction:column;gap:10px}
.ifeed .msg{max-width:82%;opacity:0;will-change:transform,opacity}

/* Flow timeline (thay phone tĩnh ở section mobile) */
.tl-item{display:flex;gap:14px;position:relative;padding-bottom:20px}
.tl-item:last-child{padding-bottom:0}
.tl-item:not(:last-child)::before{content:"";position:absolute;left:18px;top:40px;bottom:0;width:2px;background:var(--border)}
.tl-dot{width:38px;height:38px;border-radius:11px;flex:none;display:grid;place-items:center;position:relative;z-index:1;
  background:var(--elevated);border:1px solid var(--border);color:var(--primary-hover)}
.tl-item.ok .tl-dot{background:rgba(16,185,129,.14);border-color:rgba(16,185,129,.35);color:#6EE7B7}
.tl-tx b{font-size:15px;font-weight:600;display:block}
.tl-tx span{font-size:13px;color:var(--text-2)}

@media(max-width:860px){
  .arch{grid-template-columns:1fr}
  .arch-arrow{transform:rotate(90deg);padding:8px 0}
  .split,.split.rev{grid-template-columns:1fr;gap:36px}
  .split.rev .split-visual{order:0}
  .iso-points,.chan-grid{grid-template-columns:1fr}
  .lane{flex-direction:column;align-items:stretch;gap:11px}.lane .who{width:auto}
  .lp-title,.split-copy h2{font-size:26px}
}
@media(prefers-reduced-motion:reduce){
  .ifeed .msg{opacity:1 !important;animation:none !important;transform:none !important}
}
</style>"""


# Status-bar icons (inline SVG, không phụ thuộc bộ icon chung)
_SIG = ("<svg width='18' height='12' viewBox='0 0 18 12' fill='white'>"
        "<rect x='0' y='8' width='3' height='4' rx='1'/><rect x='5' y='5' width='3' height='7' rx='1'/>"
        "<rect x='10' y='2.5' width='3' height='9.5' rx='1'/><rect x='15' y='0' width='3' height='12' rx='1'/></svg>")
_WIFI = ("<svg width='17' height='12' viewBox='0 0 17 13' fill='white'>"
         "<path d='M8.5 2C5.6 2 3 3.1 1 5l1.4 1.4C4 4.8 6.2 4 8.5 4s4.5.8 6.1 2.4L16 5C14 3.1 11.4 2 8.5 2Z'/>"
         "<path d='M8.5 6c-1.7 0-3.3.7-4.4 1.8L5.5 9.2c.8-.8 1.9-1.2 3-1.2s2.2.4 3 1.2l1.4-1.4C11.8 6.7 10.2 6 8.5 6Z'/>"
         "<circle cx='8.5' cy='11.2' r='1.3'/></svg>")
_BATT = ("<svg width='26' height='13' viewBox='0 0 26 13' fill='none'>"
         "<rect x='.5' y='.5' width='21' height='12' rx='3.5' stroke='white' stroke-opacity='.5'/>"
         "<rect x='2' y='2' width='16' height='9' rx='2' fill='white'/>"
         "<path d='M23.5 4.5c1 0 1.5.7 1.5 2s-.5 2-1.5 2v-4Z' fill='white' fill-opacity='.55'/></svg>")

_DEMO_T = 16  # giây/vòng lặp


def _demo_phone() -> str:
    # (side, inner) — tin nhắn lần lượt hiện ra (mỗi cái 1 keyframe đồng bộ → loop sạch)
    msgs = [
        ("out", t("demo.m1")),
        ("in", f"<div class='who'>{icon('sparkles', 11)} Luna</div>" + t("demo.m2")),
        ("in", f"<div class='who'>{icon('sparkles', 11)} Luna</div>" + t("demo.m3")
               + f"<div class='mini'><b class='yes'>{t('demo.btn.approve')}</b>"
               + f"<b class='no'>{t('demo.btn.fix')}</b></div>"),
        ("out", t("demo.btn.approve")),
        ("in", f"<div class='who'>{icon('check', 11)} Luna</div>" + t("demo.m5")
               + f"<div class='mini'><b class='yes'>{t('demo.btn.approve_merge')}</b></div>"),
        ("out", t("demo.btn.approve_merge")),
        ("in", "<div class='who'>🚀 Luna</div>" + t("demo.m7")),
    ]
    n = len(msgs)
    spread = 79 / (n - 1)  # rải thời điểm hiện từ 5% → 84% của vòng lặp
    bubbles, keyframes, applies = [], [], []
    for i, (side, inner) in enumerate(msgs):
        bubbles.append(f"<div class='msg {side} dm{i}'>{inner}</div>")
        a = 5 + i * spread
        keyframes.append(
            f"@keyframes dm{i}{{0%,{a:.1f}%{{opacity:0;transform:translateY(15px) scale(.95)}}"
            f"{a + 2:.1f}%,93%{{opacity:1;transform:none}}100%{{opacity:0;transform:translateY(-8px)}}}}")
        applies.append(f".ifeed .dm{i}{{animation:dm{i} {_DEMO_T}s cubic-bezier(.2,.85,.25,1) infinite}}")
    style = f"<style>{''.join(keyframes)}{''.join(applies)}</style>"
    return f"""
    <section class='lp-section'><div class='lp-inner'>
      <div class='lp-head'>
        <div class='lp-eyebrow'>{icon('send')} {t('demo.eyebrow')}</div>
        <h2 class='lp-title'>{t('demo.title')}</h2>
        <p class='lp-sub'>{t('demo.sub')}</p>
      </div>
      <div class='demo-wrap'>
        <div class='iphone'><div class='iscreen'>
          <div class='island'></div>
          <div class='istatus'><span>9:41</span><span class='rt'>{_SIG}{_WIFI}{_BATT}</span></div>
          <div class='ihead'><span class='av'>{icon('moon', 18)}</span>
            <div style='flex:1'><div class='nm'>Luna</div>
              <div class='st'><i></i> {t('demo.status')}</div></div>{icon('send', 16, 'muted')}</div>
          <div class='ibody'><div class='ifeed'>{''.join(bubbles)}</div></div>
        </div></div>
      </div>
    </div></section>{style}"""


def _architecture() -> str:
    def node(ic, title, desc, tags, hl=False):
        cls = "arch-node hl" if hl else "arch-node"
        t = "".join(f"<span>{esc(x)}</span>" for x in tags)
        return (f"<div class='{cls}'><div class='arch-ico'>{icon(ic, 22)}</div>"
                f"<h3>{esc(title)}</h3><p>{esc(desc)}</p><div class='arch-tags'>{t}</div></div>")
    arrow = f"<div class='arch-arrow'>{icon('arrow-right', 26)}</div>"
    return f"""
    <section class='lp-section'><div class='lp-inner'>
      <div class='lp-head'>
        <div class='lp-eyebrow'>{icon('dashboard')} {t('arch.eyebrow')}</div>
        <h2 class='lp-title'>{t('arch.title')}</h2>
        <p class='lp-sub'>{t('arch.sub')}</p>
      </div>
      <div class='arch'>
        {node('requests', t('arch.node1.title'), t('arch.node1.desc'), ['Telegram', 'Google Chat'])}
        {arrow}
        {node('moon', t('arch.node2.title'), t('arch.node2.desc'), ['FSM', 'Claude Code', t('arch.node2.tag_gate')], hl=True)}
        {arrow}
        {node('github', t('arch.node3.title'), t('arch.node3.desc'), ['GitHub App', 'dev → main'])}
      </div>
    </div></section>"""


def _mobile_flow() -> str:
    feats = [
        ("zap", "mobile.feat1.title", "mobile.feat1.desc"),
        ("shield", "mobile.feat2.title", "mobile.feat2.desc"),
        ("check-circle", "mobile.feat3.title", "mobile.feat3.desc"),
    ]
    rows = "".join(
        f"<div class='feat-row'><span class='feat-ico'>{icon(ic, 17)}</span>"
        f"<div><b>{esc(t(tk))}</b><p>{esc(t(dk))}</p></div></div>" for ic, tk, dk in feats)
    steps = [
        ("send", "mobile.step1.t", "mobile.step1.d"),
        ("sparkles", "mobile.step2.t", "mobile.step2.d"),
        ("requests", "mobile.step3.t", "mobile.step3.d"),
        ("branch", "mobile.step4.t", "mobile.step4.d"),
        ("check-circle", "mobile.step5.t", "mobile.step5.d"),
        ("shield", "mobile.step6.t", "mobile.step6.d"),
        ("rocket", "mobile.step7.t", "mobile.step7.d", True),
    ]
    timeline = "".join(
        f"<div class='tl-item{' ok' if len(s) > 3 and s[3] else ''}'>"
        f"<span class='tl-dot'>{icon(s[0], 18)}</span>"
        f"<div class='tl-tx'><b>{esc(t(s[1]))}</b><span>{esc(t(s[2]))}</span></div></div>" for s in steps)
    return f"""
    <section class='lp-section'><div class='lp-inner'><div class='split'>
      <div class='split-visual'><div class='card'>{timeline}</div></div>
      <div class='split-copy'>
        <div class='lp-eyebrow'>{icon('zap')} {t('mobile.eyebrow')}</div>
        <h2>{t('mobile.title')}</h2>
        <p class='lp-sub'>{t('mobile.sub')}</p>
        <div class='feat-list'>{rows}</div>
      </div>
    </div></div></section>"""


_SOTATEK_LOGO = (
    "<svg viewBox='0 0 41 55' width='16' height='22' fill='none'>"
    "<path d='M40.0583 15.9172C39.063 17.261 37.7987 18.3833 36.3456 19.2127C34.8926 20.0421 33.2826 20.5604 31.6181 20.7347C29.9537 20.9089 28.2711 20.7353 26.6774 20.2249C25.0838 19.7145 23.6139 18.8785 22.3613 17.7699C21.1086 16.6614 20.1007 15.3047 19.4015 13.786C18.7023 12.2673 18.3271 10.6199 18.2999 8.94859C18.2727 7.27726 18.594 5.61856 19.2434 4.07797C19.8928 2.53738 20.8561 1.14862 22.0719 0L40.0583 15.9172Z' fill='#036AE5'/>"
    "<path d='M5.56315 38.0315C4.1559 37.1326 2.95094 35.9515 2.0246 34.5631C1.09826 33.1747 0.470742 31.6093 0.181808 29.966C-0.107126 28.3228 -0.0511784 26.6374 0.346105 25.0169C0.743388 23.3964 1.47335 21.8759 2.48973 20.5518C3.50611 19.2278 4.78676 18.129 6.25054 17.3252C7.71432 16.5213 9.32931 16.0299 10.9932 15.882C12.6571 15.7341 14.3336 15.933 15.9164 16.4661C17.4993 16.9992 18.9541 17.8549 20.1886 18.9789L5.56315 38.0315Z' fill='#036AE5'/>"
    "<path d='M7.40967 39.1751C8.39938 37.8295 9.65826 36.7041 11.1065 35.8702C12.5547 35.0363 14.1606 34.5121 15.8223 34.3308C17.4841 34.1496 19.1654 34.3152 20.7597 34.8173C22.354 35.3193 23.8264 36.1468 25.0836 37.2472C26.3407 38.3477 27.3552 39.6971 28.0626 41.2098C28.7701 42.7225 29.155 44.3656 29.1931 46.0348C29.2311 47.7039 28.9215 49.3628 28.2837 50.9061C27.646 52.4494 26.694 53.8436 25.4883 55L7.40967 39.1751Z' fill='#036AE5'/>"
    "</svg>"
)


def _isolation() -> str:
    tenants = [
        (_SOTATEK_LOGO, "#fff", "Sotatek Korea", "sotatek_kr", "sotatek/core"),
        ("B", "linear-gradient(135deg,#10B981,#059669)", "Globex", "tenant_b", "globex/api"),
        ("C", "linear-gradient(135deg,#F59E0B,#EF4444)", "Initech", "tenant_c", "initech/web"),
    ]
    lanes = "".join(
        f"<div class='lane'><div class='who'><span class='av' style='background:{g}'>{l}</span>"
        f"<span class='nm'>{esc(nm)}<small>{esc(tid)}</small></span></div>"
        f"<div class='wall'><span class='bar'></span>{icon('shield', 16)}"
        f"<span>{t('iso.separated')}</span><span class='bar'></span></div>"
        f"<span class='box'>{icon('check', 14)} {esc(repo)}</span></div>"
        for l, g, nm, tid, repo in tenants)
    pts = [
        ("shield", "iso.pt1.t", "iso.pt1.d"),
        ("zap", "iso.pt2.t", "iso.pt2.d"),
        ("bot", "iso.pt3.t", "iso.pt3.d"),
        ("settings", "iso.pt4.t", "iso.pt4.d"),
    ]
    grid = "".join(
        f"<div class='iso-pt'><span class='pi'>{icon(ic, 17)}</span>"
        f"<div><b>{t(tk)}</b><p>{t(dk)}</p></div></div>" for ic, tk, dk in pts)
    return f"""
    <section class='lp-section'><div class='lp-inner'>
      <div class='lp-head'>
        <div class='lp-eyebrow'>{icon('shield')} {t('iso.eyebrow')}</div>
        <h2 class='lp-title'>{t('iso.title')}</h2>
        <p class='lp-sub'>{t('iso.sub')}</p>
      </div>
      <div class='lanes'>{lanes}</div>
      <div class='iso-points'>{grid}</div>
    </div></section>"""


def _channels() -> str:
    return f"""
    <section class='lp-section'><div class='lp-inner'>
      <div class='lp-head'>
        <div class='lp-eyebrow'>{icon('send')} {t('chan.eyebrow')}</div>
        <h2 class='lp-title'>{t('chan.title')}</h2>
        <p class='lp-sub'>{t('chan.sub')}</p>
      </div>
      <div class='chan-grid'>
        <div class='chan'>
          <div class='top'><span class='ci' style='background:#229ED9'>{icon('send', 22)}</span>
            <h3>Telegram</h3></div>
          <p>{t('chan.tg.desc')}</p>
          <div class='tags'><span>{t('chan.tg.tag1')}</span><span>{t('chan.tg.tag2')}</span><span>{t('chan.tg.tag3')}</span></div>
        </div>
        <div class='chan'>
          <div class='top'><span class='ci' style='background:linear-gradient(135deg,#34A853,#4285F4)'>{icon('users', 22)}</span>
            <h3>Google Chat</h3></div>
          <p>{t('chan.gc.desc')}</p>
          <div class='tags'><span>{t('chan.gc.tag1')}</span><span>{t('chan.gc.tag2')}</span><span>{t('chan.gc.tag3')}</span></div>
        </div>
      </div>
      <div class='chan-soon'>
        <span class='cs-label'>{icon('zap', 14)} {t('chan.soon.label')}</span>
        <div class='cs-list'>
          <span class='cs'><i style='background:#4A154B'>S</i>Slack</span>
          <span class='cs'><i style='background:#6264A7'>T</i>Microsoft Teams</span>
          <span class='cs'><i style='background:#FEE500;color:#3A1D1D'>K</i>KakaoTalk</span>
          <span class='cs'><i style='background:#03C75A'>W</i>Naver Works</span>
        </div>
      </div>
    </div></section>"""


def _dashboard_preview() -> str:
    rows = [
        (t("dprev.row1_name"), "acme/shop · @ShopMaintBot", t("dprev.status.running"), "var(--primary)"),
        ("API Gateway", "globex/api · " + t("common.luna_shared"), t("dprev.status.ready"), "var(--success)"),
        ("Billing Service", "initech/billing · " + t("common.luna_shared"), t("dprev.status.pending"), "var(--warning)"),
    ]
    body = "".join(
        f"<div class='bp-row'><div class='l'><span class='bi'>{icon('bot', 18)}</span>"
        f"<div><div class='nm'>{esc(nm)}</div><div class='sub'>{esc(sub)}</div></div></div>"
        f"<div class='bp-st'><i style='background:{c}'></i>{esc(st)}</div></div>"
        for nm, sub, st, c in rows)
    return f"""
    <section class='lp-section'><div class='lp-inner'>
      <div class='lp-head'>
        <div class='lp-eyebrow'>{icon('dashboard')} {t('dprev.eyebrow')}</div>
        <h2 class='lp-title'>{t('dprev.title')}</h2>
        <p class='lp-sub'>{t('dprev.sub')}</p>
      </div>
      <div class='browser'>
        <div class='browser-bar'><span class='browser-dot'></span><span class='browser-dot'></span>
          <span class='browser-dot'></span><span class='browser-url'>app.luna.dev/dashboard</span></div>
        <div class='browser-body'>
          <div class='bp-head'><h4>{t('dprev.bots')}</h4><span class='bp-pill'>{t('dprev.new')}</span></div>
          {body}
        </div>
      </div>
    </div></section>"""


def sections(login_url: str) -> str:
    cta = f"""
    <section class='lp-section' style='border-bottom:1px solid var(--border)'><div class='lp-inner'>
      <div class='lp-cta'>
        <h2 class='lp-title'>{t('cta.title')}</h2>
        <p class='lp-sub' style='max-width:520px;margin:14px auto 26px'>{t('cta.sub')}</p>
        <a class='btn btn-github btn-lg' href='{esc(login_url)}'>{icon('github')}{t('cta.btn')}</a>
      </div>
    </div></section>
    <div class='lp-foot'>{t('foot')}</div>"""
    return (_demo_phone() + _architecture() + _mobile_flow() + _isolation()
            + _channels() + _dashboard_preview() + cta)
