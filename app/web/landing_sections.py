"""Các section marketing cho landing page (kiến trúc, isolation, đa kênh, mobile flow).

Tách khỏi templates.py để giữ mỗi file ≤500 LOC. `LANDING_CSS` được inject qua
`doc(..., extra_head=...)`. HTML tĩnh (không nhận giá trị động ngoài login_url ở CTA).
Các "screenshot" là mockup CSS/SVG thuần — không cần asset ngoài.
"""
from __future__ import annotations

from html import escape as esc

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

/* Demo "video" player (screencast hoạt hoạ CSS, không cần file ngoài) */
.demo-wrap{max-width:860px;margin:0 auto}
.demo-player{position:relative;border-radius:18px;overflow:hidden;border:1px solid var(--border-2);
  background:#0a0e18;box-shadow:0 50px 110px -40px rgba(0,0,0,.85),0 0 0 1px rgba(255,255,255,.04)}
.demo-top{display:flex;align-items:center;gap:12px;padding:11px 16px;background:rgba(17,24,39,.92);
  border-bottom:1px solid var(--border);position:relative;z-index:3}
.demo-rec{display:flex;align-items:center;gap:7px;font-size:12px;font-weight:600;color:var(--text-2)}
.demo-rec i{width:8px;height:8px;border-radius:999px;background:var(--danger);display:block;animation:blink 1.4s steps(1,end) infinite}
@keyframes blink{50%{opacity:.2}}
.demo-file{margin-left:auto;font-size:12px;color:var(--text-3);font-family:ui-monospace,monospace}
.demo-stage{position:relative;height:392px;overflow:hidden;cursor:pointer;
  background:radial-gradient(120% 70% at 50% 0,rgba(99,102,241,.1),transparent 60%)}
.demo-phase{position:absolute;top:14px;left:14px;z-index:3;height:28px;width:240px}
.demo-phase span{position:absolute;left:0;top:0;white-space:nowrap;display:inline-flex;align-items:center;gap:7px;
  padding:6px 12px;border-radius:999px;font-size:12px;font-weight:600;background:rgba(11,15,25,.78);
  border:1px solid var(--border-2);color:var(--text);opacity:0}
.demo-phase span svg{width:13px;height:13px;color:var(--primary-hover)}
.demo-phase span:first-child{opacity:1}
.demo-feed{padding:56px 18px 30px;display:flex;flex-direction:column;gap:9px;will-change:transform}
.demo-feed .msg{max-width:80%}
.demo-scrim{position:absolute;inset:0;z-index:2;pointer-events:none;
  background:linear-gradient(180deg,transparent 60%,rgba(10,14,24,.5))}
.demo-play{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);z-index:4;
  width:66px;height:66px;border-radius:999px;display:grid;place-items:center;
  background:rgba(99,102,241,.95);color:#fff;box-shadow:0 12px 34px -6px var(--primary);transition:opacity .25s ease}
.demo-play::before{content:"";position:absolute;inset:-12px;border-radius:999px;
  border:2px solid rgba(99,102,241,.5);animation:ring 2.2s ease-out infinite}
@keyframes ring{0%{transform:scale(.82);opacity:.85}100%{transform:scale(1.55);opacity:0}}
.demo-ctrl{display:flex;align-items:center;gap:13px;padding:12px 16px;background:rgba(17,24,39,.92);
  border-top:1px solid var(--border);position:relative;z-index:3;color:var(--text-2)}
.demo-ctrl .pp{display:flex}.demo-ctrl .pp .ico-pause{display:none}
.demo-bar{flex:1;height:5px;border-radius:999px;background:rgba(255,255,255,.1);overflow:hidden}
.demo-bar i{display:block;height:100%;width:0;border-radius:999px;
  background:linear-gradient(90deg,var(--primary),#8B5CF6)}
.demo-time{font-size:12px;color:var(--text-3);font-variant-numeric:tabular-nums}
/* play-state: chỉ chạy khi .playing */
.demo-feed{transform:translateY(0)}
.demo-player.playing .demo-feed{animation:scroll 17s ease-in-out infinite}
.demo-player.playing .demo-bar i{animation:prog 17s linear infinite}
.demo-player.playing .demo-phase span{animation:cyc 17s infinite}
.demo-player.playing .demo-play{opacity:0;pointer-events:none}
.demo-player.playing .demo-ctrl .pp .ico-play{display:none}
.demo-player.playing .demo-ctrl .pp .ico-pause{display:flex}
@keyframes scroll{0%,8%{transform:translateY(0)}24%,32%{transform:translateY(-72px)}
  48%,56%{transform:translateY(-168px)}72%,80%{transform:translateY(-262px)}96%,100%{transform:translateY(-320px)}}
@keyframes prog{from{width:0}to{width:100%}}
@keyframes cyc{0%,18%,100%{opacity:0;transform:translateY(-4px)}3%,15%{opacity:1;transform:none}}

@media(max-width:860px){
  .arch{grid-template-columns:1fr}
  .arch-arrow{transform:rotate(90deg);padding:8px 0}
  .split,.split.rev{grid-template-columns:1fr;gap:36px}
  .split.rev .split-visual{order:0}
  .iso-points,.chan-grid{grid-template-columns:1fr}
  .lane{flex-direction:column;align-items:stretch;gap:11px}.lane .who{width:auto}
  .lp-title,.split-copy h2{font-size:26px}
  .demo-stage{height:340px}
}
@media(prefers-reduced-motion:reduce){
  .demo-player.playing .demo-feed,.demo-player.playing .demo-bar i,
  .demo-player.playing .demo-phase span,.demo-rec i,.demo-play::before{animation:none}
}
</style>"""


def _phone() -> str:
    return f"""
    <div class='phone'><div class='phone-screen'><div class='phone-notch'></div>
      <div class='chat-hd'><span class='av'>{icon('moon', 18)}</span>
        <div style='flex:1'><div class='nm'>Luna Maintenance Bot</div>
          <div class='st'><i></i> online · ShopTeam</div></div>{icon('send', 16, 'muted')}</div>
      <div class='chat'>
        <div class='msg sys'>Hôm nay</div>
        <div class='msg out'>Trang checkout báo lỗi 500 khi bấm thanh toán 😟</div>
        <div class='msg in'><div class='who'>{icon('sparkles', 11)} Luna</div>
          Đã nhận. Mình đang phân tích repo <code>shop</code>…</div>
        <div class='msg in'><div class='who'>{icon('sparkles', 11)} Luna</div>
          Nguyên nhân: thiếu null-check ở <code>PaymentService.charge()</code>.
          <b>Kế hoạch:</b> thêm guard + test hồi quy.
          <div class='mini'><b class='yes'>✓ Duyệt</b><b class='no'>Sửa lại</b></div></div>
        <div class='msg out'>✓ Duyệt</div>
        <div class='msg sys'>⚙️ Đang viết code trên nhánh <b>dev</b></div>
        <div class='msg in'><div class='who'>{icon('check', 11)} Luna</div>
          Đã verify ✅ — PR <code>#42</code> sẵn sàng. Duyệt merge production?
          <div class='mini'><b class='yes'>✓ Duyệt merge</b></div></div>
        <div class='msg out'>✓ Duyệt merge</div>
        <div class='msg in'><div class='who'>🚀 Luna</div>
          Đã merge <code>main</code> & deploy. Checkout hoạt động trở lại.</div>
      </div></div></div>"""


def _demo_video() -> str:
    phases = [
        ("send", "Nhận yêu cầu"), ("sparkles", "Đang phân tích"),
        ("requests", "Trình kế hoạch"), ("branch", "Viết code trên dev"),
        ("check-circle", "Verify & mở PR"), ("rocket", "Đã deploy"),
    ]
    step = 17 / len(phases)
    chips = "".join(
        f"<span style='animation-delay:{i * step:.2f}s'>{icon(ic, 13)}{esc(t)}</span>"
        for i, (ic, t) in enumerate(phases))
    feed = f"""
      <div class='msg sys'>Phiên bảo trì · ShopTeam</div>
      <div class='msg out'>Trang checkout báo lỗi 500 khi bấm thanh toán 😟</div>
      <div class='msg in'><div class='who'>{icon('sparkles', 11)} Luna</div>
        Đã nhận. Đang phân tích repo <code>acme/shop</code>…</div>
      <div class='msg in'><div class='who'>{icon('sparkles', 11)} Luna</div>
        Nguyên nhân: thiếu null-check ở <code>PaymentService.charge()</code>.
        <b>Kế hoạch:</b> thêm guard + test hồi quy.
        <div class='mini'><b class='yes'>✓ Duyệt</b><b class='no'>Sửa lại</b></div></div>
      <div class='msg out'>✓ Duyệt</div>
      <div class='msg sys'>⚙️ Đang viết code trên nhánh <b>dev</b></div>
      <div class='msg in'><div class='who'>{icon('check', 11)} Luna</div>
        Đã verify ✅ — PR <code>#42</code> sẵn sàng. Duyệt merge production?
        <div class='mini'><b class='yes'>✓ Duyệt merge</b></div></div>
      <div class='msg out'>✓ Duyệt merge</div>
      <div class='msg in'><div class='who'>🚀 Luna</div>
        Đã merge <code>main</code> & deploy thành công. Checkout hoạt động trở lại 🎉</div>"""
    return f"""
    <section class='lp-section'><div class='lp-inner'>
      <div class='lp-head'>
        <div class='lp-eyebrow'>{icon('play')} Xem demo</div>
        <h2 class='lp-title'>Toàn bộ vòng đời trong 17 giây</h2>
        <p class='lp-sub'>Từ một tin nhắn báo lỗi đến khi bản vá lên production — bấm play để xem
          Luna chạy hết quy trình, có cổng người duyệt ở mỗi bước.</p>
      </div>
      <div class='demo-wrap'>
        <div class='demo-player' id='demoPlayer'>
          <div class='demo-top'><span class='demo-rec'><i></i> LIVE DEMO</span>
            <span class='demo-file'>luna-checkout-fix.mp4</span></div>
          <div class='demo-stage' id='demoStage'>
            <div class='demo-phase'>{chips}</div>
            <div class='demo-feed'>{feed}</div>
            <div class='demo-scrim'></div>
            <div class='demo-play' id='demoPlay' role='button' tabindex='0' aria-label='Phát demo'>
              {icon('play', 26)}</div>
          </div>
          <div class='demo-ctrl'>
            <span class='pp'><span class='ico-play'>{icon('play', 17)}</span><span class='ico-pause'>{icon('pause', 17)}</span></span>
            <div class='demo-bar'><i></i></div>
            <span class='demo-time'>0:17</span>
            {icon('volume', 17)}{icon('maximize', 17)}
          </div>
        </div>
      </div>
    </div></section>
    <script>
    (function(){{
      var p=document.getElementById('demoPlayer');if(!p)return;
      var stage=document.getElementById('demoStage'),pp=p.querySelector('.pp');
      function toggle(on){{p.classList.toggle('playing',on);}}
      function flip(){{toggle(!p.classList.contains('playing'));}}
      stage.addEventListener('click',flip);
      pp.addEventListener('click',function(e){{e.stopPropagation();flip();}});
      document.getElementById('demoPlay').addEventListener('keydown',function(e){{
        if(e.key==='Enter'||e.key===' '){{e.preventDefault();toggle(true);}}}});
    }})();
    </script>"""


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
        <div class='lp-eyebrow'>{icon('dashboard')} Kiến trúc</div>
        <h2 class='lp-title'>Một pipeline có cổng người duyệt</h2>
        <p class='lp-sub'>Luna đứng giữa cuộc trò chuyện của bạn và codebase: điều phối quy trình
          (FSM), để Claude Code suy nghĩ & viết code, nhưng <b>không bao giờ tự merge production</b>
          khi chưa có người duyệt.</p>
      </div>
      <div class='arch'>
        {node('requests', 'Bạn & team', 'Gửi yêu cầu bảo trì qua chat sẵn có.', ['Telegram', 'Google Chat'])}
        {arrow}
        {node('moon', 'Luna Orchestrator', 'FSM điều phối + Claude Code headless chạy trong sandbox.', ['FSM', 'Claude Code', 'Approval gate'], hl=True)}
        {arrow}
        {node('github', 'Repo của bạn', 'Sửa trên dev → PR → chỉ merge main khi được duyệt.', ['GitHub App', 'dev → main'])}
      </div>
    </div></section>"""


def _mobile_flow() -> str:
    feats = [
        ("zap", "Phát hiện → fix → deploy không rời điện thoại",
         "Báo lỗi bằng một tin nhắn; Luna lo phần còn lại và cập nhật tiến độ ngay trong thread."),
        ("shield", "Bạn luôn nắm quyền quyết định",
         "Duyệt kế hoạch và duyệt merge production chỉ bằng một chạm — không có gì lên main sau lưng bạn."),
        ("check-circle", "Minh bạch từng bước",
         "Phân tích, kế hoạch, PR, kết quả verify và deploy đều hiện trong cuộc trò chuyện."),
    ]
    rows = "".join(
        f"<div class='feat-row'><span class='feat-ico'>{icon(ic, 17)}</span>"
        f"<div><b>{esc(t)}</b><p>{esc(d)}</p></div></div>" for ic, t, d in feats)
    return f"""
    <section class='lp-section'><div class='lp-inner'><div class='split'>
      <div class='split-visual'>{_phone()}</div>
      <div class='split-copy'>
        <div class='lp-eyebrow'>{icon('zap')} Mobile-first</div>
        <h2>Bảo trì phần mềm<br>chỉ bằng điện thoại</h2>
        <p class='lp-sub'>Từ lúc khách báo lỗi đến khi bản vá lên production — toàn bộ vòng đời
          diễn ra trong một cuộc trò chuyện. Không cần mở laptop, không cần truy cập server.</p>
        <div class='feat-list'>{rows}</div>
      </div>
    </div></div></section>"""


def _isolation() -> str:
    tenants = [
        ("A", "linear-gradient(135deg,#6366F1,#8B5CF6)", "Acme Corp", "tenant_a", "acme/shop"),
        ("B", "linear-gradient(135deg,#10B981,#059669)", "Globex", "tenant_b", "globex/api"),
        ("C", "linear-gradient(135deg,#F59E0B,#EF4444)", "Initech", "tenant_c", "initech/web"),
    ]
    lanes = "".join(
        f"<div class='lane'><div class='who'><span class='av' style='background:{g}'>{l}</span>"
        f"<span class='nm'>{esc(nm)}<small>{esc(tid)}</small></span></div>"
        f"<div class='wall'><span class='bar'></span>{icon('shield', 16)}"
        f"<span>tách biệt</span><span class='bar'></span></div>"
        f"<span class='box'>{icon('check', 14)} {esc(repo)}</span></div>"
        for l, g, nm, tid, repo in tenants)
    pts = [
        ("shield", "Workspace cô lập từng tenant", "Mỗi repo clone riêng tại WORKSPACE/&lt;tenant&gt;/&lt;repo&gt;; khoá theo repo để không bao giờ lẫn dữ liệu."),
        ("zap", "Token GitHub ngắn hạn", "Dùng installation token TTL ~1h, sinh lại trước mỗi thao tác và không bao giờ ghi log."),
        ("bot", "Bot & quyền riêng từng khách", "Bot chung hoặc bot riêng của bạn; chỉ requester cùng tenant mới thao tác được request."),
        ("settings", "Tuỳ chọn container riêng", "Khối lượng nhạy cảm có thể chạy trên container cô lập thật, tách hẳn hạ tầng chung."),
    ]
    grid = "".join(
        f"<div class='iso-pt'><span class='pi'>{icon(ic, 17)}</span>"
        f"<div><b>{t}</b><p>{d}</p></div></div>" for ic, t, d in pts)
    return f"""
    <section class='lp-section'><div class='lp-inner'>
      <div class='lp-head'>
        <div class='lp-eyebrow'>{icon('shield')} Bảo mật đa tenant</div>
        <h2 class='lp-title'>Dữ liệu mỗi khách hàng được tách biệt</h2>
        <p class='lp-sub'>Luna là nền tảng multi-tenant: code, bot và quyền của từng doanh nghiệp
          sống trong vùng cô lập của riêng họ — không bao giờ chạm vào nhau.</p>
      </div>
      <div class='lanes'>{lanes}</div>
      <div class='iso-points'>{grid}</div>
    </div></section>"""


def _channels() -> str:
    return f"""
    <section class='lp-section'><div class='lp-inner'>
      <div class='lp-head'>
        <div class='lp-eyebrow'>{icon('send')} Đa kênh</div>
        <h2 class='lp-title'>Dùng ngay app chat doanh nghiệp đang có</h2>
        <p class='lp-sub'>Không bắt cả team đổi thói quen. Luna nói chuyện qua kênh bạn đã dùng —
          hỗ trợ nhóm, thread và cộng tác nhiều người. Một thread = một yêu cầu bảo trì.</p>
      </div>
      <div class='chan-grid'>
        <div class='chan'>
          <div class='top'><span class='ci' style='background:#229ED9'>{icon('send', 22)}</span>
            <h3>Telegram</h3></div>
          <p>Bot Luna chung không cần cài đặt, hoặc bot riêng mang tên & avatar thương hiệu của bạn.</p>
          <div class='tags'><span>Nhóm</span><span>Bot riêng</span><span>Zero-setup</span></div>
        </div>
        <div class='chan'>
          <div class='top'><span class='ci' style='background:linear-gradient(135deg,#34A853,#4285F4)'>{icon('users', 22)}</span>
            <h3>Google Chat</h3></div>
          <p>Tích hợp thẳng vào Google Workspace — quản lý yêu cầu bảo trì ngay trong Space của team.</p>
          <div class='tags'><span>Spaces</span><span>Thread</span><span>Workspace</span></div>
        </div>
      </div>
    </div></section>"""


def _dashboard_preview() -> str:
    rows = [
        ("Bot bảo trì Shop", "acme/shop · @ShopMaintBot", "Đang chạy", "var(--primary)"),
        ("API Gateway", "globex/api · Luna chung", "Sẵn sàng", "var(--success)"),
        ("Billing Service", "initech/billing · Luna chung", "Chờ duyệt", "var(--warning)"),
    ]
    body = "".join(
        f"<div class='bp-row'><div class='l'><span class='bi'>{icon('bot', 18)}</span>"
        f"<div><div class='nm'>{esc(nm)}</div><div class='sub'>{esc(sub)}</div></div></div>"
        f"<div class='bp-st'><i style='background:{c}'></i>{esc(st)}</div></div>"
        for nm, sub, st, c in rows)
    return f"""
    <section class='lp-section'><div class='lp-inner'>
      <div class='lp-head'>
        <div class='lp-eyebrow'>{icon('dashboard')} Dashboard</div>
        <h2 class='lp-title'>Mọi bot & yêu cầu ở một nơi</h2>
        <p class='lp-sub'>Theo dõi trạng thái mọi bot và tiến độ từng yêu cầu bảo trì theo thời gian thực.</p>
      </div>
      <div class='browser'>
        <div class='browser-bar'><span class='browser-dot'></span><span class='browser-dot'></span>
          <span class='browser-dot'></span><span class='browser-url'>app.luna.dev/dashboard</span></div>
        <div class='browser-body'>
          <div class='bp-head'><h4>Bots</h4><span class='bp-pill'>＋ Tạo bot mới</span></div>
          {body}
        </div>
      </div>
    </div></section>"""


def sections(login_url: str) -> str:
    cta = f"""
    <section class='lp-section' style='border-bottom:1px solid var(--border)'><div class='lp-inner'>
      <div class='lp-cta'>
        <h2 class='lp-title'>Sẵn sàng để Luna lo phần bảo trì?</h2>
        <p class='lp-sub' style='max-width:520px;margin:14px auto 26px'>Kết nối repo trong vài phút và
          gửi yêu cầu bảo trì đầu tiên ngay từ điện thoại của bạn.</p>
        <a class='btn btn-github btn-lg' href='{esc(login_url)}'>{icon('github')}Bắt đầu với GitHub</a>
      </div>
    </div></section>
    <div class='lp-foot'>🌙 Luna — AI Maintenance Engineer · Bảo trì có kiểm soát, deploy có người duyệt.</div>"""
    return (_demo_video() + _architecture() + _mobile_flow() + _isolation()
            + _channels() + _dashboard_preview() + cta)
