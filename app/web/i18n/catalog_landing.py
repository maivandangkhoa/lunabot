"""Catalog dịch — landing page (hero) + các section marketing.
(xem app/web/i18n/__init__.py). Brand/tech-term giữ nguyên; <br>/<b>/<code> giữ trong chuỗi.
"""
from __future__ import annotations

TEXTS: dict[str, dict[str, str]] = {
    # ── Landing — disabled state ──
    "landing.disabled.title": {"vi": "Web wizard chưa được cấu hình.", "en": "Web wizard is not configured.", "ko": "웹 마법사가 구성되지 않았습니다."},
    "landing.disabled.body": {"vi": "Thiếu GitHub OAuth / PUBLIC_BASE_URL — xem ", "en": "Missing GitHub OAuth / PUBLIC_BASE_URL — see ", "ko": "GitHub OAuth / PUBLIC_BASE_URL 누락 — 참고: "},

    # ── Landing — flow chips ──
    "flow.request": {"vi": "Yêu cầu", "en": "Request", "ko": "요청"},
    "flow.analyze": {"vi": "Phân tích", "en": "Analyze", "ko": "분석"},
    "flow.plan": {"vi": "Kế hoạch", "en": "Plan", "ko": "계획"},
    "flow.approve": {"vi": "Duyệt", "en": "Approve", "ko": "승인"},
    "flow.code": {"vi": "Viết code", "en": "Code", "ko": "코딩"},
    "flow.verify": {"vi": "Verify", "en": "Verify", "ko": "검증"},
    "flow.merge": {"vi": "Merge", "en": "Merge", "ko": "병합"},

    # ── Landing — pills ──
    "pill.approved": {"vi": "Merge có người duyệt", "en": "Human-approved merges", "ko": "사람이 승인하는 병합"},
    "pill.repos": {"vi": "Chạy trên repo của bạn", "en": "Works on your repos", "ko": "내 저장소에서 작동"},
    "pill.zerosetup": {"vi": "Bot chung không cần cài đặt", "en": "Zero-setup shared bot", "ko": "설정 없는 공용 봇"},
    "pill.team": {"vi": "Cộng tác nhóm", "en": "Team collaboration", "ko": "팀 협업"},

    # ── Landing — hero ──
    "landing.badge": {"vi": "Nền tảng kỹ thuật AI", "en": "AI Engineering Platform", "ko": "AI 엔지니어링 플랫폼"},
    "landing.hero": {"vi": "Kỹ sư bảo trì AI<br>cho codebase của bạn", "en": "AI Maintenance Engineer<br>for your codebase", "ko": "당신의 코드베이스를 위한<br>AI 유지보수 엔지니어"},
    "landing.subtitle": {
        "vi": "Luna nhận yêu cầu bảo trì qua chat, tự phân tích, lập kế hoạch, viết code trên nhánh dev và chỉ merge production khi <b>người duyệt</b> đồng ý.",
        "en": "Luna takes maintenance requests over chat, analyzes them, plans, writes code on a dev branch, and only merges to production when an <b>approver</b> agrees.",
        "ko": "Luna는 채팅으로 유지보수 요청을 받아 분석하고 계획을 세우며 dev 브랜치에 코드를 작성하고, <b>승인자</b>가 동의할 때만 프로덕션에 병합합니다."},
    "landing.cta_github": {"vi": "Tiếp tục với GitHub", "en": "Continue with GitHub", "ko": "GitHub으로 계속하기"},
    "landing.hint_free": {"vi": "Miễn phí để bắt đầu · Không cần thẻ tín dụng", "en": "Free to start · No credit card required", "ko": "무료로 시작 · 신용카드 불필요"},

    # ── Demo section ──
    "demo.eyebrow": {"vi": "Demo trực tiếp", "en": "Live demo", "ko": "라이브 데모"},
    "demo.title": {"vi": "Toàn bộ vòng đời trong vài phút", "en": "The whole lifecycle in minutes", "ko": "전체 수명 주기를 몇 분 만에"},
    "demo.sub": {
        "vi": "Từ một tin nhắn báo lỗi đến khi bản vá lên production — mọi thứ diễn ra ngay trong khung chat trên điện thoại, có cổng người duyệt ở mỗi bước.",
        "en": "From a single bug report to a patch in production — it all happens right in your phone's chat, with an approval gate at every step.",
        "ko": "버그 신고 한 건부터 프로덕션 배포까지 — 모든 것이 휴대폰 채팅에서 이루어지며 각 단계마다 승인 단계가 있습니다."},
    "demo.status": {"vi": "online · ShopTeam", "en": "online · ShopTeam", "ko": "온라인 · ShopTeam"},
    "demo.m1": {"vi": "Trang checkout báo lỗi 500 khi bấm thanh toán 😟", "en": "The checkout page throws a 500 when I click pay 😟", "ko": "결제를 누르면 체크아웃 페이지에서 500 오류가 납니다 😟"},
    "demo.m2": {"vi": "Đã nhận — đang phân tích <code>acme/shop</code>…", "en": "Got it — analyzing <code>acme/shop</code>…", "ko": "확인했습니다 — <code>acme/shop</code> 분석 중…"},
    "demo.m3": {
        "vi": "Nguyên nhân: thiếu null-check ở <code>PaymentService.charge()</code>. <b>Kế hoạch:</b> thêm guard + test hồi quy.",
        "en": "Cause: missing null-check in <code>PaymentService.charge()</code>. <b>Plan:</b> add a guard + regression test.",
        "ko": "원인: <code>PaymentService.charge()</code>의 null 체크 누락. <b>계획:</b> 가드 + 회귀 테스트 추가."},
    "demo.btn.approve": {"vi": "✓ Duyệt", "en": "✓ Approve", "ko": "✓ 승인"},
    "demo.btn.fix": {"vi": "Sửa lại", "en": "Revise", "ko": "수정"},
    "demo.btn.approve_merge": {"vi": "✓ Duyệt merge", "en": "✓ Approve merge", "ko": "✓ 병합 승인"},
    "demo.m5": {
        "vi": "Đã sửa trên <b>dev</b>, verify ✅ — PR <code>#42</code>. Duyệt merge production?",
        "en": "Fixed on <b>dev</b>, verified ✅ — PR <code>#42</code>. Approve production merge?",
        "ko": "<b>dev</b>에서 수정 완료, 검증 ✅ — PR <code>#42</code>. 프로덕션 병합을 승인할까요?"},
    "demo.m7": {"vi": "Đã merge <code>main</code> & deploy. Checkout hoạt động trở lại 🎉", "en": "Merged <code>main</code> & deployed. Checkout works again 🎉", "ko": "<code>main</code> 병합 및 배포 완료. 체크아웃이 다시 작동합니다 🎉"},

    # ── Architecture section ──
    "arch.eyebrow": {"vi": "Kiến trúc", "en": "Architecture", "ko": "아키텍처"},
    "arch.title": {"vi": "Một pipeline có cổng người duyệt", "en": "A pipeline with an approval gate", "ko": "승인 단계가 있는 파이프라인"},
    "arch.sub": {
        "vi": "Luna đứng giữa cuộc trò chuyện của bạn và codebase: điều phối quy trình (FSM), để Claude Code suy nghĩ & viết code, nhưng <b>không bao giờ tự merge production</b> khi chưa có người duyệt.",
        "en": "Luna sits between your conversation and your codebase: it orchestrates the workflow (FSM), lets Claude Code think & write code, but <b>never merges to production on its own</b> without an approver.",
        "ko": "Luna는 대화와 코드베이스 사이에 위치합니다: 워크플로(FSM)를 조율하고 Claude Code가 사고하고 코드를 작성하게 하지만, 승인자 없이는 <b>절대 스스로 프로덕션에 병합하지 않습니다</b>."},
    "arch.node1.title": {"vi": "Bạn & team", "en": "You & your team", "ko": "나와 팀"},
    "arch.node1.desc": {"vi": "Gửi yêu cầu bảo trì qua chat sẵn có.", "en": "Send maintenance requests over your existing chat.", "ko": "기존 채팅으로 유지보수 요청을 보냅니다."},
    "arch.node2.title": {"vi": "Luna Orchestrator", "en": "Luna Orchestrator", "ko": "Luna 오케스트레이터"},
    "arch.node2.desc": {"vi": "FSM điều phối + Claude Code headless chạy trong sandbox.", "en": "FSM orchestration + headless Claude Code running in a sandbox.", "ko": "FSM 조율 + 샌드박스에서 실행되는 헤드리스 Claude Code."},
    "arch.node2.tag_gate": {"vi": "Cổng duyệt", "en": "Approval gate", "ko": "승인 단계"},
    "arch.node3.title": {"vi": "Repo của bạn", "en": "Your repo", "ko": "내 저장소"},
    "arch.node3.desc": {"vi": "Sửa trên dev → PR → chỉ merge main khi được duyệt.", "en": "Edit on dev → PR → merge main only when approved.", "ko": "dev에서 수정 → PR → 승인될 때만 main 병합."},

    # ── Mobile flow section ──
    "mobile.feat1.title": {"vi": "Phát hiện → fix → deploy không rời điện thoại", "en": "Detect → fix → deploy without leaving your phone", "ko": "휴대폰을 떠나지 않고 감지 → 수정 → 배포"},
    "mobile.feat1.desc": {"vi": "Báo lỗi bằng một tin nhắn; Luna lo phần còn lại và cập nhật tiến độ ngay trong thread.", "en": "Report a bug in one message; Luna handles the rest and posts progress right in the thread.", "ko": "메시지 하나로 버그를 신고하면 Luna가 나머지를 처리하고 스레드에 진행 상황을 게시합니다."},
    "mobile.feat2.title": {"vi": "Bạn luôn nắm quyền quyết định", "en": "You're always in control", "ko": "항상 당신이 결정권을 가집니다"},
    "mobile.feat2.desc": {"vi": "Duyệt kế hoạch và duyệt merge production chỉ bằng một chạm — không có gì lên main sau lưng bạn.", "en": "Approve the plan and the production merge with one tap — nothing reaches main behind your back.", "ko": "한 번의 탭으로 계획과 프로덕션 병합을 승인하세요 — 당신 모르게 main에 올라가는 것은 없습니다."},
    "mobile.feat3.title": {"vi": "Minh bạch từng bước", "en": "Transparent at every step", "ko": "모든 단계가 투명합니다"},
    "mobile.feat3.desc": {"vi": "Phân tích, kế hoạch, PR, kết quả verify và deploy đều hiện trong cuộc trò chuyện.", "en": "Analysis, plan, PR, verification results and deploy all show up in the conversation.", "ko": "분석, 계획, PR, 검증 결과, 배포가 모두 대화에 표시됩니다."},
    "mobile.eyebrow": {"vi": "Mobile-first", "en": "Mobile-first", "ko": "모바일 우선"},
    "mobile.title": {"vi": "Bảo trì phần mềm<br>chỉ bằng điện thoại", "en": "Maintain software<br>from your phone alone", "ko": "휴대폰만으로<br>소프트웨어 유지보수"},
    "mobile.sub": {
        "vi": "Từ lúc khách báo lỗi đến khi bản vá lên production — toàn bộ vòng đời diễn ra trong một cuộc trò chuyện. Không cần mở laptop, không cần truy cập server.",
        "en": "From a customer's bug report to a patch in production — the entire lifecycle happens in one conversation. No laptop, no server access needed.",
        "ko": "고객의 버그 신고부터 프로덕션 배포까지 — 전체 수명 주기가 하나의 대화에서 이루어집니다. 노트북도, 서버 접근도 필요 없습니다."},
    "mobile.step1.t": {"vi": "Yêu cầu", "en": "Request", "ko": "요청"},
    "mobile.step1.d": {"vi": "Báo lỗi hoặc đổi tính năng bằng một tin nhắn.", "en": "Report a bug or request a change in one message.", "ko": "메시지 하나로 버그를 신고하거나 변경을 요청하세요."},
    "mobile.step2.t": {"vi": "Phân tích", "en": "Analyze", "ko": "분석"},
    "mobile.step2.d": {"vi": "Luna đọc repo, tìm nguyên nhân gốc.", "en": "Luna reads the repo and finds the root cause.", "ko": "Luna가 저장소를 읽고 근본 원인을 찾습니다."},
    "mobile.step3.t": {"vi": "Kế hoạch", "en": "Plan", "ko": "계획"},
    "mobile.step3.d": {"vi": "Đề xuất cách sửa — bạn duyệt.", "en": "Proposes a fix — you approve.", "ko": "수정 방안을 제안 — 당신이 승인합니다."},
    "mobile.step4.t": {"vi": "Viết code", "en": "Code", "ko": "코딩"},
    "mobile.step4.d": {"vi": "Sửa an toàn trên nhánh dev.", "en": "Makes safe changes on the dev branch.", "ko": "dev 브랜치에서 안전하게 수정합니다."},
    "mobile.step5.t": {"vi": "Verify & PR", "en": "Verify & PR", "ko": "검증 & PR"},
    "mobile.step5.d": {"vi": "Chạy kiểm thử rồi mở pull request.", "en": "Runs tests, then opens a pull request.", "ko": "테스트를 실행한 뒤 풀 리퀘스트를 엽니다."},
    "mobile.step6.t": {"vi": "Duyệt merge", "en": "Approve merge", "ko": "병합 승인"},
    "mobile.step6.d": {"vi": "Manager duyệt đưa lên production.", "en": "A manager approves the push to production.", "ko": "관리자가 프로덕션 반영을 승인합니다."},
    "mobile.step7.t": {"vi": "Deploy", "en": "Deploy", "ko": "배포"},
    "mobile.step7.d": {"vi": "Bản vá lên production tự động.", "en": "The patch ships to production automatically.", "ko": "패치가 프로덕션에 자동으로 배포됩니다."},

    # ── Isolation section ──
    "iso.eyebrow": {"vi": "Bảo mật đa tenant", "en": "Multi-tenant security", "ko": "멀티테넌트 보안"},
    "iso.title": {"vi": "Dữ liệu mỗi khách hàng được tách biệt", "en": "Every customer's data stays isolated", "ko": "모든 고객의 데이터가 격리됩니다"},
    "iso.sub": {
        "vi": "Luna là nền tảng multi-tenant: code, bot và quyền của từng doanh nghiệp sống trong vùng cô lập của riêng họ — không bao giờ chạm vào nhau.",
        "en": "Luna is a multi-tenant platform: each company's code, bot and permissions live in their own isolated space — never touching each other.",
        "ko": "Luna는 멀티테넌트 플랫폼입니다: 각 회사의 코드, 봇, 권한이 자체 격리 공간에 존재하며 서로 닿지 않습니다."},
    "iso.separated": {"vi": "tách biệt", "en": "isolated", "ko": "격리됨"},
    "iso.pt1.t": {"vi": "Workspace cô lập từng tenant", "en": "Per-tenant isolated workspace", "ko": "테넌트별 격리 워크스페이스"},
    "iso.pt1.d": {"vi": "Mỗi repo clone riêng tại WORKSPACE/&lt;tenant&gt;/&lt;repo&gt;; khoá theo repo để không bao giờ lẫn dữ liệu.", "en": "Each repo is cloned separately at WORKSPACE/&lt;tenant&gt;/&lt;repo&gt;; locked per repo so data never mixes.", "ko": "각 저장소는 WORKSPACE/&lt;tenant&gt;/&lt;repo&gt;에 개별 복제되며, 저장소별로 잠겨 데이터가 섞이지 않습니다."},
    "iso.pt2.t": {"vi": "Token GitHub ngắn hạn", "en": "Short-lived GitHub tokens", "ko": "단기 GitHub 토큰"},
    "iso.pt2.d": {"vi": "Dùng installation token TTL ~1h, sinh lại trước mỗi thao tác và không bao giờ ghi log.", "en": "Uses installation tokens with ~1h TTL, regenerated before each action and never logged.", "ko": "~1시간 TTL의 설치 토큰을 사용하며, 각 작업 전에 재발급하고 절대 로그에 남기지 않습니다."},
    "iso.pt3.t": {"vi": "Bot & quyền riêng từng khách", "en": "Per-customer bot & permissions", "ko": "고객별 봇 및 권한"},
    "iso.pt3.d": {"vi": "Bot chung hoặc bot riêng của bạn; chỉ requester cùng tenant mới thao tác được request.", "en": "Shared bot or your own bot; only requesters in the same tenant can act on a request.", "ko": "공용 봇 또는 자체 봇; 동일 테넌트의 요청자만 요청을 처리할 수 있습니다."},
    "iso.pt4.t": {"vi": "Tuỳ chọn container riêng", "en": "Optional dedicated container", "ko": "선택적 전용 컨테이너"},
    "iso.pt4.d": {"vi": "Khối lượng nhạy cảm có thể chạy trên container cô lập thật, tách hẳn hạ tầng chung.", "en": "Sensitive workloads can run on a truly isolated container, fully separated from shared infrastructure.", "ko": "민감한 워크로드는 공용 인프라와 완전히 분리된 진정한 격리 컨테이너에서 실행할 수 있습니다."},

    # ── Channels section ──
    "chan.eyebrow": {"vi": "Đa kênh", "en": "Multi-channel", "ko": "멀티 채널"},
    "chan.title": {"vi": "Dùng ngay app chat doanh nghiệp đang có", "en": "Use the team chat app you already have", "ko": "이미 쓰는 업무용 채팅 앱을 그대로 사용"},
    "chan.sub": {
        "vi": "Không bắt cả team đổi thói quen. Luna nói chuyện qua kênh bạn đã dùng — hỗ trợ nhóm, thread và cộng tác nhiều người. Một thread = một yêu cầu bảo trì.",
        "en": "No need to change your team's habits. Luna talks over the channel you already use — with groups, threads and multi-person collaboration. One thread = one maintenance request.",
        "ko": "팀의 습관을 바꿀 필요가 없습니다. Luna는 이미 사용하는 채널에서 대화합니다 — 그룹, 스레드, 다중 사용자 협업을 지원합니다. 스레드 하나 = 유지보수 요청 하나."},
    "chan.tg.desc": {"vi": "Bot Luna chung không cần cài đặt, hoặc bot riêng mang tên & avatar thương hiệu của bạn.", "en": "The zero-setup shared Luna bot, or your own bot with your brand's name & avatar.", "ko": "설정이 필요 없는 공용 Luna 봇, 또는 브랜드 이름과 아바타가 있는 자체 봇."},
    "chan.tg.tag1": {"vi": "Nhóm", "en": "Groups", "ko": "그룹"},
    "chan.tg.tag2": {"vi": "Bot riêng", "en": "Own bot", "ko": "자체 봇"},
    "chan.tg.tag3": {"vi": "Zero-setup", "en": "Zero-setup", "ko": "설정 불필요"},
    "chan.gc.desc": {"vi": "Tích hợp thẳng vào Google Workspace — quản lý yêu cầu bảo trì ngay trong Space của team.", "en": "Integrates straight into Google Workspace — manage maintenance requests right in your team's Space.", "ko": "Google Workspace에 바로 통합 — 팀 Space에서 유지보수 요청을 관리하세요."},
    "chan.gc.tag1": {"vi": "Spaces", "en": "Spaces", "ko": "Spaces"},
    "chan.gc.tag2": {"vi": "Thread", "en": "Threads", "ko": "스레드"},
    "chan.gc.tag3": {"vi": "Workspace", "en": "Workspace", "ko": "Workspace"},
    "chan.soon.label": {"vi": "Sắp ra mắt", "en": "Coming soon", "ko": "출시 예정"},

    # ── Dashboard preview section ──
    "dprev.eyebrow": {"vi": "Dashboard", "en": "Dashboard", "ko": "대시보드"},
    "dprev.title": {"vi": "Mọi bot & yêu cầu ở một nơi", "en": "Every bot & request in one place", "ko": "모든 봇과 요청을 한곳에서"},
    "dprev.sub": {"vi": "Theo dõi trạng thái mọi bot và tiến độ từng yêu cầu bảo trì theo thời gian thực.", "en": "Track the status of every bot and the progress of each maintenance request in real time.", "ko": "모든 봇의 상태와 각 유지보수 요청의 진행 상황을 실시간으로 추적하세요."},
    "dprev.bots": {"vi": "Bots", "en": "Bots", "ko": "봇"},
    "dprev.row1_name": {"vi": "Bot bảo trì Shop", "en": "Shop Maintenance Bot", "ko": "Shop 유지보수 봇"},
    "dprev.new": {"vi": "＋ Tạo bot mới", "en": "＋ New bot", "ko": "＋ 새 봇"},
    "dprev.status.running": {"vi": "Đang chạy", "en": "Running", "ko": "실행 중"},
    "dprev.status.ready": {"vi": "Sẵn sàng", "en": "Ready", "ko": "준비됨"},
    "dprev.status.pending": {"vi": "Chờ duyệt", "en": "Pending approval", "ko": "승인 대기"},

    # ── Final CTA + footer ──
    "cta.title": {"vi": "Sẵn sàng để Luna lo phần bảo trì?", "en": "Ready to let Luna handle maintenance?", "ko": "Luna에게 유지보수를 맡길 준비가 되셨나요?"},
    "cta.sub": {"vi": "Kết nối repo trong vài phút và gửi yêu cầu bảo trì đầu tiên ngay từ điện thoại của bạn.", "en": "Connect a repo in minutes and send your first maintenance request right from your phone.", "ko": "몇 분 만에 저장소를 연결하고 휴대폰에서 첫 유지보수 요청을 보내세요."},
    "cta.btn": {"vi": "Bắt đầu với GitHub", "en": "Get started with GitHub", "ko": "GitHub으로 시작하기"},
    "foot": {"vi": "🌙 Luna — Kỹ sư bảo trì AI · Bảo trì có kiểm soát, deploy có người duyệt.", "en": "🌙 Luna — AI Maintenance Engineer · Controlled maintenance, human-approved deploys.", "ko": "🌙 Luna — AI 유지보수 엔지니어 · 통제된 유지보수, 사람이 승인하는 배포."},
}
