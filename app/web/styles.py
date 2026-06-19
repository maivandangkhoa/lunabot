"""Design system cho web UI của Luna — premium SaaS, dark-mode-first.

Tách riêng khỏi templates.py: chứa CSS (design tokens + components), bộ icon Lucide
(inline SVG, không thêm dep), và 2 layout shell — `doc()` (tài liệu HTML) + `shell()`
(app shell có sidebar) + `onboarding()` (khung onboarding căn giữa).

KHÔNG đụng backend: chỉ phục vụ render HTML/CSS.
"""
from __future__ import annotations

from html import escape as esc

# ── Design tokens + component system ──────────────────────────────────────────
CSS = """
:root{
  --bg:#0B0F19; --surface:#111827; --elevated:#151C2B;
  --primary:#6366F1; --primary-hover:#7C7FF8; --primary-soft:rgba(99,102,241,.14);
  --success:#10B981; --warning:#F59E0B; --danger:#EF4444;
  --text:#F9FAFB; --text-2:#9CA3AF; --text-3:#6B7280;
  --border:rgba(255,255,255,.08); --border-2:rgba(255,255,255,.14);
  --radius:16px; --radius-sm:12px; --radius-pill:999px;
  --shadow:0 1px 2px rgba(0,0,0,.4),0 8px 24px rgba(0,0,0,.36);
  --ring:0 0 0 3px var(--primary-soft);
  --sidebar-w:248px;
}
*{box-sizing:border-box;margin:0;padding:0}
html{-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
body{font-family:Inter,ui-sans-serif,system-ui,sans-serif;background:var(--bg);
  color:var(--text);font-size:16px;line-height:1.6;min-height:100vh}
body::before{content:"";position:fixed;inset:0;pointer-events:none;z-index:0;
  background:radial-gradient(900px 500px at 80% -10%,rgba(99,102,241,.16),transparent 60%),
             radial-gradient(700px 500px at -10% 110%,rgba(16,185,129,.08),transparent 55%)}
a{color:inherit;text-decoration:none}
svg{display:block;flex:none}
::selection{background:var(--primary-soft);color:var(--text)}

h1,h2,h3{line-height:1.2;letter-spacing:-.02em;font-weight:700}
.hero{font-size:48px;font-weight:700;letter-spacing:-.03em}
.page-title{font-size:32px;font-weight:700}
.section-title{font-size:20px;font-weight:600;letter-spacing:-.01em}
.muted{color:var(--text-2)}
.small{font-size:14px} .label-text{font-size:13px}
.code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.85em;
  background:rgba(255,255,255,.06);border:1px solid var(--border);
  border-radius:6px;padding:2px 7px;color:#C7D2FE}

/* ── Buttons ── */
.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;height:44px;
  padding:0 20px;border-radius:var(--radius-sm);border:1px solid transparent;
  font:inherit;font-size:15px;font-weight:600;cursor:pointer;white-space:nowrap;
  transition:background .15s ease,border-color .15s ease,transform .06s ease,box-shadow .15s ease}
.btn:active{transform:translateY(1px)}
.btn-primary{background:var(--primary);color:#fff;box-shadow:0 1px 0 rgba(255,255,255,.08) inset,0 8px 20px -8px var(--primary)}
.btn-primary:hover{background:var(--primary-hover)}
.btn-secondary{background:var(--elevated);color:var(--text);border-color:var(--border-2)}
.btn-secondary:hover{background:#1b2334;border-color:rgba(255,255,255,.22)}
.btn-ghost{background:transparent;color:var(--text-2)}
.btn-ghost:hover{background:rgba(255,255,255,.05);color:var(--text)}
.btn-lg{height:52px;padding:0 26px;font-size:16px}
.btn-block{width:100%}
.btn[disabled]{opacity:.5;cursor:not-allowed}
.btn-github{background:#fff;color:#0B0F19}
.btn-github:hover{background:#e8e8ee}

/* ── Cards & surfaces ── */
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);
  padding:28px;box-shadow:var(--shadow)}
.card-tight{padding:20px}
.card-row{display:flex;align-items:center;gap:16px}

/* ── Forms ── */
.field{margin:18px 0}
.field > label{display:block;font-size:13px;font-weight:600;color:var(--text-2);
  margin-bottom:7px;letter-spacing:.01em}
.input{width:100%;height:44px;padding:0 14px;background:var(--bg);color:var(--text);
  border:1px solid var(--border-2);border-radius:var(--radius-sm);font:inherit;font-size:15px;
  transition:border-color .15s ease,box-shadow .15s ease}
.input::placeholder{color:var(--text-3)}
.input:hover{border-color:rgba(255,255,255,.22)}
.input:focus{outline:none;border-color:var(--primary);box-shadow:var(--ring)}
select.input{appearance:none;cursor:pointer;
  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%239CA3AF' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E");
  background-repeat:no-repeat;background-position:right 14px center;padding-right:40px}
.hint{font-size:13px;color:var(--text-3);margin-top:7px}
.field-2{display:flex;gap:14px} .field-2 .field{flex:1}

/* ── Selectable choice cards ── */
.choices{display:grid;gap:12px;grid-template-columns:1fr 1fr}
.choice{position:relative;display:block;cursor:pointer;background:var(--elevated);
  border:1px solid var(--border);border-radius:var(--radius-sm);padding:18px 18px 18px 18px;
  transition:border-color .15s ease,background .15s ease,box-shadow .15s ease}
.choice:hover{border-color:rgba(255,255,255,.2)}
.choice input{position:absolute;opacity:0;pointer-events:none}
.choice .ch-title{font-weight:600;font-size:15px;display:flex;align-items:center;gap:8px;padding-right:30px}
.choice .ch-desc{font-size:13px;color:var(--text-2);margin-top:6px}
.choice .ch-tick{position:absolute;top:14px;right:14px;width:22px;height:22px;border-radius:999px;
  border:1.5px solid var(--border-2);display:grid;place-items:center;color:transparent;transition:.15s}
.choice:has(input:checked){border-color:var(--primary);background:var(--primary-soft);
  box-shadow:var(--ring)}
.choice:has(input:checked) .ch-tick{background:var(--primary);border-color:var(--primary);color:#fff}

/* ── Badges & status ── */
.badge{display:inline-flex;align-items:center;gap:5px;height:24px;padding:0 10px;
  border-radius:var(--radius-pill);font-size:12px;font-weight:600;border:1px solid var(--border-2)}
.badge svg{width:13px;height:13px}
.badge-info{background:var(--primary-soft);color:#C7D2FE;border-color:rgba(99,102,241,.4)}
.badge-success{background:rgba(16,185,129,.14);color:#6EE7B7;border-color:rgba(16,185,129,.4)}
.badge-warning{background:rgba(245,158,11,.14);color:#FCD34D;border-color:rgba(245,158,11,.4)}
.badge-danger{background:rgba(239,68,68,.14);color:#FCA5A5;border-color:rgba(239,68,68,.4)}
.badge-muted{background:rgba(255,255,255,.05);color:var(--text-2)}
.status{display:inline-flex;align-items:center;gap:7px;font-size:13px;font-weight:500;color:var(--text-2)}
.dot{width:8px;height:8px;border-radius:999px;background:var(--text-3);flex:none}
.dot-success{background:var(--success);box-shadow:0 0 0 4px rgba(16,185,129,.18)}
.dot-warning{background:var(--warning);box-shadow:0 0 0 4px rgba(245,158,11,.18)}
.dot-danger{background:var(--danger);box-shadow:0 0 0 4px rgba(239,68,68,.18)}
.dot-running{background:var(--primary);box-shadow:0 0 0 4px var(--primary-soft);animation:pulse 1.6s ease-in-out infinite}
@keyframes pulse{50%{opacity:.45}}

/* ── Alert banners ── */
.alert{display:flex;gap:12px;align-items:flex-start;padding:14px 16px;border-radius:var(--radius-sm);
  font-size:14px;border:1px solid var(--border)}
.alert svg{flex:none;margin-top:1px}
.alert-danger{background:rgba(239,68,68,.1);border-color:rgba(239,68,68,.35);color:#FCA5A5}
.alert-success{background:rgba(16,185,129,.1);border-color:rgba(16,185,129,.35);color:#6EE7B7}

/* ── App shell ── */
.shell{display:grid;grid-template-columns:var(--sidebar-w) 1fr;min-height:100vh;position:relative;z-index:1}
.sidebar{border-right:1px solid var(--border);background:rgba(17,24,39,.6);
  backdrop-filter:blur(12px);padding:22px 16px;display:flex;flex-direction:column;gap:6px;
  position:sticky;top:0;height:100vh}
.brand{display:flex;align-items:center;gap:10px;font-size:19px;font-weight:700;
  padding:6px 10px 18px;letter-spacing:-.02em}
.brand .logo{width:34px;height:34px;border-radius:10px;display:grid;place-items:center;color:#fff;
  background:linear-gradient(135deg,var(--primary),#8B5CF6);box-shadow:0 6px 16px -6px var(--primary)}
.nav-label{font-size:11px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;
  color:var(--text-3);padding:14px 10px 6px}
.nav-item{display:flex;align-items:center;gap:11px;padding:9px 11px;border-radius:10px;
  color:var(--text-2);font-size:14px;font-weight:500;transition:.13s}
.nav-item:hover{background:rgba(255,255,255,.05);color:var(--text)}
.nav-item.active{background:var(--primary-soft);color:#fff}
.nav-item.active svg{color:var(--primary-hover)}
.nav-item svg{width:18px;height:18px;color:var(--text-3)}
.sidebar-foot{margin-top:auto;border-top:1px solid var(--border);padding-top:14px}
.main{display:flex;flex-direction:column;min-width:0}
.topbar{display:flex;align-items:center;gap:16px;padding:14px 28px;border-bottom:1px solid var(--border);
  position:sticky;top:0;background:rgba(11,15,25,.72);backdrop-filter:blur(12px);z-index:5}
.workspace{display:flex;align-items:center;gap:9px;font-weight:600;font-size:14px}
.workspace .ws-ico{width:26px;height:26px;border-radius:8px;background:var(--elevated);
  border:1px solid var(--border);display:grid;place-items:center;color:var(--text-2)}
.search{flex:1;max-width:420px;display:flex;align-items:center;gap:9px;height:38px;padding:0 12px;
  background:var(--surface);border:1px solid var(--border);border-radius:10px;color:var(--text-3);font-size:14px}
.icon-btn{width:38px;height:38px;border-radius:10px;display:grid;place-items:center;color:var(--text-2);
  border:1px solid var(--border);background:var(--surface);cursor:pointer;transition:.13s}
.icon-btn:hover{color:var(--text);border-color:var(--border-2)}
.avatar{width:34px;height:34px;border-radius:999px;display:grid;place-items:center;font-size:13px;
  font-weight:600;color:#fff;background:linear-gradient(135deg,var(--primary),#8B5CF6)}
.content{padding:32px 28px;max-width:1400px;width:100%;margin:0 auto}
.page-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:24px}

/* ── Onboarding (centered) ── */
.ob{position:relative;z-index:1;min-height:100vh;display:flex;flex-direction:column}
.ob-bar{display:flex;align-items:center;justify-content:space-between;padding:20px 28px}
.ob-bar .brand{padding:0}
.ob-wrap{flex:1;display:flex;justify-content:center;padding:24px 20px 64px}
.ob-col{width:100%;max-width:560px}
.ob-wide{max-width:720px}

/* ── Stepper ── */
.stepper{display:flex;align-items:center;gap:0;margin:8px 0 28px}
.step-node{display:flex;align-items:center;gap:10px;flex:1}
.step-num{width:30px;height:30px;border-radius:999px;display:grid;place-items:center;flex:none;
  font-size:13px;font-weight:600;background:var(--elevated);border:1px solid var(--border-2);color:var(--text-2)}
.step-name{font-size:13px;font-weight:500;color:var(--text-3);white-space:nowrap}
.step-line{height:1px;flex:1;background:var(--border);margin:0 8px}
.step-node.done .step-num,.step-node.current .step-num{border-color:var(--primary);background:var(--primary);color:#fff}
.step-node.current .step-name,.step-node.done .step-name{color:var(--text)}
.wstep{display:none;animation:fade .2s ease}
.wstep.show{display:block}
@keyframes fade{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
.wnav{display:flex;gap:12px;margin-top:24px}
.wnav .grow{flex:1}

/* ── Feature pills (landing) ── */
.pills{display:flex;flex-wrap:wrap;gap:10px;margin-top:26px}
.pill{display:inline-flex;align-items:center;gap:8px;padding:8px 14px;font-size:13px;font-weight:500;
  color:var(--text-2);background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-pill)}
.pill svg{width:15px;height:15px;color:var(--primary-hover)}
.flow{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin-top:8px;color:var(--text-2);font-size:14px}
.flow .fstep{padding:6px 12px;background:var(--elevated);border:1px solid var(--border);border-radius:8px;font-weight:500;color:var(--text)}
.flow svg{width:15px;height:15px;color:var(--text-3)}

/* ── Summary list (review/done) ── */
.summary{display:grid;gap:1px;background:var(--border);border:1px solid var(--border);border-radius:var(--radius-sm);overflow:hidden}
.summary .srow{display:flex;justify-content:space-between;gap:16px;padding:13px 16px;background:var(--surface);font-size:14px}
.summary .srow span:first-child{color:var(--text-2)}
.summary .srow span:last-child{font-weight:600;text-align:right}

/* ── Empty state ── */
.empty{text-align:center;padding:56px 24px}
.empty .e-ico{width:56px;height:56px;border-radius:16px;margin:0 auto 16px;display:grid;place-items:center;
  background:var(--elevated);border:1px solid var(--border);color:var(--text-2)}

.divider{height:1px;background:var(--border);margin:24px 0}
.stack-sm > * + *{margin-top:8px}

/* ── Responsive ── */
@media(max-width:960px){
  .shell{grid-template-columns:1fr}
  .sidebar{position:fixed;left:0;top:0;z-index:20;transform:translateX(-100%);transition:transform .2s ease;width:260px}
  .sidebar.open{transform:none}
  .menu-btn{display:grid !important}
}
.menu-btn{display:none}
@media(max-width:640px){
  .hero{font-size:34px} .page-title{font-size:26px}
  .choices{grid-template-columns:1fr}
  .field-2{flex-direction:column;gap:0}
  .step-name{display:none}
  .card{padding:20px} .content{padding:22px 16px}
  .search{display:none}
}
"""

# ── Lucide icons (inline SVG) ─────────────────────────────────────────────────
_ICONS = {
    "moon": '<path d="M12 3a6.4 6.4 0 0 0 9 9 9 9 0 1 1-9-9Z"/>',
    "dashboard": '<rect width="7" height="9" x="3" y="3" rx="1"/><rect width="7" height="5" x="14" y="3" rx="1"/><rect width="7" height="9" x="14" y="12" rx="1"/><rect width="7" height="5" x="3" y="16" rx="1"/>',
    "bot": '<path d="M12 8V4H8"/><rect width="16" height="12" x="4" y="8" rx="2"/><path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 13v2"/><path d="M9 13v2"/>',
    "repo": '<line x1="6" x2="6" y1="3" y2="15"/><circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M18 9a9 9 0 0 1-9 9"/>',
    "requests": '<path d="m3 17 2 2 4-4"/><path d="m3 7 2 2 4-4"/><path d="M13 6h8"/><path d="M13 12h8"/><path d="M13 18h8"/>',
    "activity": '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
    "settings": '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 0 2l-.15.08a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.38a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1 0-2l.15-.08a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2Z"/><circle cx="12" cy="12" r="3"/>',
    "search": '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    "bell": '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>',
    "github": '<path d="M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5.08-1.25-.27-2.48-1-3.5.28-1.15.28-2.35 0-3.5 0 0-1 0-3 1.5-2.64-.5-5.36-.5-8 0C6 2 5 2 5 2c-.3 1.15-.3 2.35 0 3.5A5.4 5.4 0 0 0 4 9c0 3.5 3 5.5 6 5.5-.39.49-.68 1.05-.85 1.65-.17.6-.22 1.23-.15 1.85v4"/><path d="M9 18c-4.51 2-5-2-7-2"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "check-circle": '<path d="M21.8 10A10 10 0 1 1 17 3.3"/><path d="m9 11 3 3L22 4"/>',
    "plus": '<path d="M5 12h14"/><path d="M12 5v14"/>',
    "arrow-right": '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
    "arrow-left": '<path d="m12 19-7-7 7-7"/><path d="M19 12H5"/>',
    "shield": '<path d="M20 13c0 5-3.5 7.5-7.7 9a1 1 0 0 1-.7 0C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.2-2.7a1.2 1.2 0 0 1 1.5 0C14.5 3.8 17 5 19 5a1 1 0 0 1 1 1Z"/><path d="m9 12 2 2 4-4"/>',
    "zap": '<path d="M4 14a1 1 0 0 1-.8-1.6l9.9-10.2a.5.5 0 0 1 .9.5l-1.9 6a1 1 0 0 0 .9 1.3h7a1 1 0 0 1 .8 1.6l-9.9 10.2a.5.5 0 0 1-.9-.5l1.9-6a1 1 0 0 0-.9-1.3Z"/>',
    "logout": '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5"/><path d="M21 12H9"/>',
    "send": '<path d="M14.5 9.5 21 3m0 0-6.5 18a.55.55 0 0 1-1 0L10 14l-6.5-3.5a.55.55 0 0 1 0-1Z"/>',
    "branch": '<line x1="6" x2="6" y1="3" y2="15"/><circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M18 9a9 9 0 0 1-9 9"/>',
    "users": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.9"/><path d="M16 3.1a4 4 0 0 1 0 7.8"/>',
    "menu": '<line x1="4" x2="20" y1="6" y2="6"/><line x1="4" x2="20" y1="12" y2="12"/><line x1="4" x2="20" y1="18" y2="18"/>',
    "alert": '<path d="m21.7 18-9-16a2 2 0 0 0-3.4 0l-9 16A2 2 0 0 0 2 21h18a2 2 0 0 0 1.7-3Z"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    "sparkles": '<path d="M9.9 2.6 8.5 6.4a2 2 0 0 1-1.2 1.2l-3.8 1.4a.5.5 0 0 0 0 .9l3.8 1.4a2 2 0 0 1 1.2 1.2l1.4 3.8a.5.5 0 0 0 .9 0l1.4-3.8a2 2 0 0 1 1.2-1.2l3.8-1.4a.5.5 0 0 0 0-.9l-3.8-1.4a2 2 0 0 1-1.2-1.2L10.8 2.6a.5.5 0 0 0-.9 0Z"/><path d="M18 5h.01"/><path d="M20 12h.01"/>',
    "play": '<path d="M6 3v18l15-9Z"/>',
    "pause": '<rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/>',
    "volume": '<path d="M11 5 6 9H2v6h4l5 4z"/><path d="M16 9a3 3 0 0 1 0 6"/><path d="M19.4 6.6a7 7 0 0 1 0 10.8"/>',
    "maximize": '<path d="M8 3H5a2 2 0 0 0-2 2v3"/><path d="M21 8V5a2 2 0 0 0-2-2h-3"/><path d="M3 16v3a2 2 0 0 0 2 2h3"/><path d="M16 21h3a2 2 0 0 0 2-2v-3"/>',
    "rocket": '<path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09Z"/><path d="m12 15-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2Z"/><path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0"/><path d="M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5"/>',
}


def icon(name: str, size: int = 20, cls: str = "") -> str:
    path = _ICONS.get(name, "")
    c = f" class='{esc(cls)}'" if cls else ""
    return (f"<svg{c} width='{size}' height='{size}' viewBox='0 0 24 24' fill='none' "
            f"stroke='currentColor' stroke-width='2' stroke-linecap='round' "
            f"stroke-linejoin='round' aria-hidden='true'>{path}</svg>")


def doc(title: str, body: str, body_class: str = "", extra_head: str = "") -> str:
    return (
        "<!doctype html><html lang='vi'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{esc(title)}</title>"
        "<link rel='preconnect' href='https://fonts.googleapis.com'>"
        "<link rel='preconnect' href='https://fonts.gstatic.com' crossorigin>"
        "<link href='https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap' rel='stylesheet'>"
        f"<style>{CSS}</style>{extra_head}</head>"
        f"<body class='{esc(body_class)}'>{body}</body></html>"
    )


def brand() -> str:
    return (f"<a class='brand' href='/'><span class='logo'>{icon('moon', 19)}</span>Luna</a>")


def onboarding(title: str, body: str, *, user_name: str | None = None) -> str:
    right = ""
    if user_name:
        right = (f"<a class='btn btn-ghost' href='/logout'>{icon('logout', 16)}Đăng xuất</a>")
    bar = f"<div class='ob-bar'>{brand()}{right}</div>"
    return doc(title, f"<div class='ob'>{bar}<div class='ob-wrap'>{body}</div></div>")


_NAV = [
    ("dashboard", "Dashboard", "/dashboard"),
    ("bot", "Bots", "/dashboard"),
    ("repo", "Repositories", "/wizard"),
    ("requests", "Requests", "/dashboard"),
    ("activity", "Activity", "/dashboard"),
    ("settings", "Settings", "/dashboard"),
]


def _sidebar(active: str) -> str:
    items = []
    for key, label, href in _NAV:
        cls = "nav-item active" if key == active else "nav-item"
        items.append(f"<a class='{cls}' href='{href}'>{icon(key)}<span>{label}</span></a>")
    foot = (f"<div class='sidebar-foot'><a class='nav-item' href='/logout'>"
            f"{icon('logout')}<span>Đăng xuất</span></a></div>")
    return (f"<aside class='sidebar' id='sidebar'>{brand()}"
            f"<div class='nav-label'>Workspace</div>{''.join(items)}{foot}</aside>")


def shell(title: str, *, active: str, user_name: str, body: str) -> str:
    initial = esc((user_name or "U").strip()[:1].upper())
    ws = esc(user_name or "Workspace")
    topbar = (
        "<header class='topbar'>"
        f"<button class='icon-btn menu-btn' onclick=\"document.getElementById('sidebar').classList.toggle('open')\" "
        f"aria-label='Menu'>{icon('menu', 18)}</button>"
        f"<div class='workspace'><span class='ws-ico'>{icon('moon', 15)}</span>{ws}</div>"
        f"<div class='search'>{icon('search', 15)}<span>Tìm kiếm…</span></div>"
        f"<button class='icon-btn' aria-label='Thông báo'>{icon('bell', 18)}</button>"
        f"<div class='avatar' title='{ws}'>{initial}</div>"
        "</header>"
    )
    return doc(title, (
        f"<div class='shell'>{_sidebar(active)}"
        f"<div class='main'>{topbar}<div class='content'>{body}</div></div></div>"
    ))
