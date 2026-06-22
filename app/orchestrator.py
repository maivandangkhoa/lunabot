"""Orchestrator — FSM lifecycle của 1 request. Lõi nghiệp vụ của luna.

App giữ quyền điều phối: mỗi phase gọi Claude (claude_runner) với permission-mode phù hợp,
parse khối JSON cuối (parsing) để quyết chuyển state, lưu requests/events/approvals, và
nói chuyện với người dùng qua ChannelAdapter (inline buttons).

Mọi side-effect (claude/git/github/adapter) inject qua constructor ⇒ test bằng fake.
Isolation: serialize thao tác git theo repo bằng asyncio.Lock per repo_id.
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import git_ops, post_deploy, prompts
from app.cleanup import cleanup_branch
from app.claude_runner import PermissionMode, run_claude
from app.channels.base import Button, ChannelAdapter
from app.config import get_settings
from app.models import (
    Approval,
    ApprovalDecision,
    EventDirection,
    EventKind,
    Repository,
    Request,
    RequestEvent,
    RequestStatus,
    User,
    UserRole,
)
from app.parsing import Action, parse_signal, strip_json_block
from app.web.i18n import t

log = logging.getLogger("luna.orchestrator")

_repo_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

# Trạng thái "đang bận với user" → chặn tạo request mới (1 user/1 request đang chạy) và là
# tập mà /clear có thể huỷ để mở session mới. AWAIT_MANAGER/MERGED_DEV KHÔNG nằm đây: phần
# của requester đã xong, chỉ chờ manager → không chặn requester gửi yêu cầu khác.
BLOCKING_STATUSES = (
    RequestStatus.NEW, RequestStatus.ANALYZING, RequestStatus.CLARIFYING,
    RequestStatus.PLAN_REVIEW, RequestStatus.EXECUTING, RequestStatus.VERIFY,
)


def cb(action: str, req_id: int) -> str:
    return f"{action}:{req_id}"


def parse_cb(data: str) -> tuple[str, int] | None:
    try:
        action, rid = data.split(":", 1)
        return action, int(rid)
    except (ValueError, AttributeError):
        return None


# Từ user gõ để "chạy lại" sau khi tự sửa repo (vd vừa tạo nhánh). Khi request đang
# CLARIFYING, bất kỳ text nào cũng kích _analyze lại; các từ này được lọc khỏi nội dung
# "trả lời làm rõ" gửi Claude (chỉ là tín hiệu retry, không phải yêu cầu mới).
RETRY_WORDS = {
    "chạy lại", "chay lai", "chạy lại đi", "chay lai di", "thử lại", "thu lai",
    "retry", "chạy tiếp", "chay tiep", "tiếp tục", "tiep tuc", "tiếp", "tiep",
}


def friendly_repo_error(exc: Exception, repo: Repository, *, retry_hint: str) -> str:
    """Dịch lỗi chuẩn bị repo (git clone/fetch/token) sang thông báo thân thiện, có hướng xử lý.

    Tránh phơi stderr thô (vd 'fatal: Remote branch dev not found in upstream origin') —
    nhận diện các trường hợp phổ biến và chỉ rõ việc khách cần làm trên GitHub.
    """
    low = str(exc).lower()
    base, prod = repo.base_branch, repo.prod_branch
    if "remote branch" in low and "not found" in low:
        return t("orch.repo_err.no_base_branch", repo=repo.repo_full_name,
                 base=base, prod=prod, retry_hint=retry_hint)
    if any(k in low for k in ("authentication failed", "could not read from remote",
                              "permission denied", "403")):
        return t("orch.repo_err.no_access", repo=repo.repo_full_name,
                 retry_hint_lower=retry_hint.lower())
    if "repository not found" in low or "does not exist" in low or "404" in low:
        return t("orch.repo_err.not_found", repo=repo.repo_full_name,
                 retry_hint_lower=retry_hint.lower())
    # Mặc định: gọn, kèm ít chi tiết để debug nhưng không dài dòng.
    return t("orch.repo_err.generic", repo=repo.repo_full_name,
             detail=str(exc)[:300], retry_hint=retry_hint)


class Orchestrator:
    def __init__(
        self,
        db: Session,
        adapter: ChannelAdapter,
        *,
        github=None,
        claude_run=None,
        git=None,
        workspace: Path | None = None,
    ):
        self.db = db
        self.adapter = adapter
        self.github = github
        # Resolve ở init-time (không phải class-def) để test monkeypatch được.
        self.claude_run = claude_run if claude_run is not None else run_claude
        self.git = git if git is not None else git_ops
        self.workspace = workspace or get_settings().workspace

    # ---------------- helpers ----------------
    def _event(self, req: Request, kind: EventKind, direction: EventDirection,
               actor_id: int | None = None, **payload) -> None:
        self.db.add(RequestEvent(
            request_id=req.id, actor_user_id=actor_id, kind=kind,
            direction=direction, payload_json=payload,
        ))

    def _set_status(self, req: Request, status: RequestStatus) -> None:
        log.info("request %s: %s → %s", req.id, req.status.value, status.value)
        req.status = status

    async def _say(self, req: Request, user: User, text: str,
                   buttons: list[list[Button]] | None = None) -> None:
        """Trả lời hướng-tới-requester: đăng vào nơi khởi tạo request (group hoặc DM)."""
        self._event(req, EventKind.SYSTEM, EventDirection.OUT, payload=text[:500])
        await self.adapter.send(self._reply_target(req), text, buttons)

    def _reply_target(self, req: Request) -> str:
        """Đích đăng tin của 1 request: origin_chat_id (group/DM) nếu có, else DM requester
        (request cũ NULL origin / đường DM thuần)."""
        return req.origin_chat_id or self._requester(req).platform_user_id

    def _requester(self, req: Request) -> User:
        return self.db.get(User, req.requester_user_id)

    def _repo(self, req: Request) -> Repository:
        return self.db.get(Repository, req.repo_id)

    def _repo_dir(self, repo: Repository) -> Path:
        safe = repo.repo_full_name.replace("/", "__")
        return self.workspace / str(repo.tenant_id) / safe

    async def _ensure_repo_cloned(self, repo: Repository) -> Path:
        """Clone/fetch nhánh base để Claude đọc được codebase. Cần github + installation_id."""
        if self.github is None:
            raise RuntimeError("GitHub App chưa cấu hình (thiếu token).")
        token = await self.github.installation_token(repo.gh_installation_id)
        url = self.github.authed_remote_url(token, repo.repo_full_name)
        repo_dir = self._repo_dir(repo)
        await self.git.ensure_clone(repo_dir, url, repo.base_branch, [repo.prod_branch])
        return repo_dir

    # ---------------- entrypoints ----------------
    async def create_request(self, repo: Repository, requester: User,
                             title: str, body: str | None, attachments=None,
                             *, chat_id: str | None = None, platform: str | None = None,
                             is_group: bool = False) -> Request:
        req = Request(
            tenant_id=repo.tenant_id, repo_id=repo.id, requester_user_id=requester.id,
            title=title, body=body, status=RequestStatus.NEW,
            origin_platform=platform, origin_chat_id=chat_id, origin_is_group=is_group,
        )
        self.db.add(req)
        self.db.flush()
        self._event(req, EventKind.MSG, EventDirection.IN, actor_id=requester.id, title=title)
        self.db.commit()
        await self._analyze(req, attachments=attachments)
        return req

    async def handle_message(self, req: Request, actor: User, text: str, attachments=None) -> None:
        """Tin text: ý nghĩa tuỳ state hiện tại."""
        self._event(req, EventKind.MSG, EventDirection.IN, actor_id=actor.id, text=text[:500])
        if req.status == RequestStatus.CLARIFYING:
            await self._analyze(req, clarifications=[text], attachments=attachments)
        elif req.status == RequestStatus.VERIFY:
            await self._execute(req, fix_feedback=text)
        else:
            self.db.commit()  # chỉ lưu lại, không chuyển state

    async def _save_attachments(self, req: Request, repo_dir: Path, attachments) -> list[str]:
        """Tải ảnh đính kèm về repo_dir/.luna-attachments/ (loại khỏi git) → list path tương đối."""
        imgs = [a for a in (attachments or []) if getattr(a, "is_image", False)]
        download = getattr(self.adapter, "download_attachment", None)
        if not imgs or download is None:
            return []
        self.git.exclude_local(repo_dir, ".luna-attachments/")
        out_dir = Path(repo_dir) / ".luna-attachments" / f"req-{req.id}"
        out_dir.mkdir(parents=True, exist_ok=True)
        paths: list[str] = []
        for i, att in enumerate(imgs):
            try:
                data = await download(att)
            except Exception as exc:  # noqa: BLE001
                log.warning("tải ảnh req %s lỗi: %s", req.id, exc)
                continue
            fp = out_dir / f"{i}_{att.file_name.replace('/', '_')[:60]}"
            fp.write_bytes(data)
            paths.append(str(fp.relative_to(repo_dir)))
        if paths:
            self._event(req, EventKind.MSG, EventDirection.IN, images=paths)
        return paths

    async def handle_callback(self, req: Request, actor: User, data: str,
                              *, reply_to: str | None = None) -> None:
        parsed = parse_cb(data)
        if not parsed:
            return
        action, _ = parsed
        # Nơi báo lỗi/ephemeral cho NGƯỜI BẤM (đúng chat họ bấm): group thì trong group, DM thì DM.
        target = reply_to or req.origin_chat_id or actor.platform_user_id
        is_mgr_action = action in ("mgr_approve", "mgr_reject")

        # An ninh group: nút của request hiện công khai → người khác cũng bấm được.
        # Hành động của requester chỉ requester (hoặc manager/admin) mới được thao tác.
        if not is_mgr_action and actor.id != req.requester_user_id \
                and actor.role not in (UserRole.MANAGER, UserRole.ADMIN):
            await self.adapter.send(target, t("orch.not_owner", id=req.id))
            return
        # Chống double-click manager (nhiều manager trong group): đã rời AWAIT_MANAGER ⇒ bỏ qua.
        if is_mgr_action and req.status != RequestStatus.AWAIT_MANAGER:
            await self.adapter.send(target, t("orch.already_handled", id=req.id))
            return

        self._event(req, EventKind.CONFIRM, EventDirection.IN, actor_id=actor.id, action=action)

        if action == "confirm" and req.status == RequestStatus.PLAN_REVIEW:
            await self._execute(req)
        elif action == "reject" and req.status == RequestStatus.PLAN_REVIEW:
            self._set_status(req, RequestStatus.CLARIFYING)
            self.db.commit()
            await self._say(req, self._requester(req), t("orch.plan_rejected"))
        elif action == "verify_ok" and req.status == RequestStatus.VERIFY:
            await self._merge_to_dev(req)
        elif action == "verify_fix" and req.status == RequestStatus.VERIFY:
            self.db.commit()
            await self._say(req, self._requester(req), t("orch.verify_fix_prompt"))
        elif action == "mgr_approve" and req.status == RequestStatus.AWAIT_MANAGER:
            await self._merge_to_main(req, actor, target)
        elif action == "mgr_reject" and req.status == RequestStatus.AWAIT_MANAGER:
            await self._manager_reject(req, actor, target)
        elif action == "cancel":
            self._set_status(req, RequestStatus.CANCELLED)
            self.db.commit()
            warns = await cleanup_branch(self, req, revert_dev=False)
            msg = t("orch.cancelled")
            if warns:
                msg += t("orch.cleanup_warn", warns="; ".join(warns))
            await self._say(req, self._requester(req), msg)

    async def clear_open_request(self, user: User, *, reply_to: str | None = None) -> None:
        """Lệnh /clear: huỷ request đang mở (blocking) của user để bắt đầu session mới.

        Dùng được ở MỌI trạng thái blocking (kể cả ANALYZING/EXECUTING, nơi không có nút huỷ).
        Chỉ dừng FSM + đóng session Claude hiện tại — KHÔNG đụng nhánh dev/commit đã tạo.
        """
        target = reply_to or user.platform_user_id
        req = self.db.scalars(
            select(Request).where(
                Request.requester_user_id == user.id,
                Request.status.in_(BLOCKING_STATUSES),
            ).order_by(Request.id.desc())
        ).first()
        if req is None:
            await self.adapter.send(target, t("orch.no_open_request"))
            return
        self._event(req, EventKind.CONFIRM, EventDirection.IN, actor_id=user.id, action="clear")
        self._set_status(req, RequestStatus.CANCELLED)
        self.db.commit()
        await self.adapter.send(target, t("orch.cleared", id=req.id))

    async def ask(self, repo: Repository, user: User, question: str,
                  *, reply_to: str | None = None) -> None:
        """Lệnh /ask: hỏi-đáp CHỈ-ĐỌC về dự án, KHÔNG qua FSM (không tạo request, không
        nhánh/commit/PR, không neo session). Tái dùng bản clone sẵn (fetch nhẹ), chạy Claude
        read-only một lần. Giữ lock per-repo để không đọc lúc một request khác đang EXECUTING."""
        target = reply_to or user.platform_user_id
        async with _repo_locks[repo.id]:
            try:
                repo_dir = await self._ensure_repo_cloned(repo)
            except Exception as exc:  # noqa: BLE001
                await self.adapter.send(target, friendly_repo_error(
                    exc, repo, retry_hint=t("orch.retry_hint.ask")))
                return
            sysp = prompts.ask_system_prompt(repo.repo_full_name, repo.base_branch)
            res = await self.claude_run(
                prompt=question, cwd=repo_dir,
                permission_mode=PermissionMode.READONLY, system_prompt=sysp,
            )
        if not res.ok:
            await self.adapter.send(target, t("orch.ask_failed", detail=res.result[:800]))
            return
        await self.adapter.send(target, res.result[:3500] or t("orch.ask_empty"))

    # ---------------- phases ----------------
    async def _analyze(self, req: Request, clarifications: list[str] | None = None,
                       attachments=None) -> None:
        repo = self._repo(req)
        requester = self._requester(req)
        self._set_status(req, RequestStatus.ANALYZING)
        self.db.commit()
        await self._say(req, requester, t("orch.received"))

        try:
            repo_dir = await self._ensure_repo_cloned(repo)
        except Exception as exc:  # noqa: BLE001
            # Không để request kẹt ở ANALYZING (user không retry được, lại báo "đang bận").
            # Chuyển CLARIFYING: khách tự sửa repo (vd tạo nhánh) rồi nhắn "chạy lại" → _analyze lại.
            self._set_status(req, RequestStatus.CLARIFYING)
            self.db.commit()
            await self._say(req, requester, friendly_repo_error(
                exc, repo, retry_hint=t("orch.retry_hint.analyze")))
            return

        # "chạy lại"/"thử lại"… chỉ là tín hiệu retry sau khi khách sửa repo — không phải nội
        # dung làm rõ, lọc bỏ để không lẫn vào prompt gửi Claude.
        clarifications = [c for c in (clarifications or []) if c.strip().lower() not in RETRY_WORDS]
        img_paths = await self._save_attachments(req, repo_dir, attachments)
        prompt = prompts.build_request_prompt(req.title, req.body, clarifications,
                                              image_paths=img_paths)
        sysp = prompts.analyzing_system_prompt(repo.repo_full_name, repo.base_branch)
        res = await self.claude_run(
            prompt=prompt, cwd=repo_dir,
            permission_mode=PermissionMode.READONLY,
            session_id=req.claude_session_id, system_prompt=sysp,
        )
        req.claude_session_id = res.session_id
        self._event(req, EventKind.SYSTEM, EventDirection.OUT, ok=res.ok, result=res.result[:500])

        if not res.ok:
            # Lỗi tạm khi chạy Claude → cho retriable thay vì kẹt ANALYZING.
            self._set_status(req, RequestStatus.CLARIFYING)
            self.db.commit()
            await self._say(req, requester, t("orch.analyze_failed", detail=res.result[:300]))
            return

        sig = parse_signal(res.result)
        if not sig.ok:
            # Claude chạy OK nhưng không ra JSON (vd nó "trả lời câu hỏi" thay vì lập kế
            # hoạch): relay nội dung cho user + chuyển CLARIFYING để hỏi muốn thay đổi gì,
            # thay vì chết cứng. Chỉ "cần can thiệp" khi output thực sự rỗng.
            if res.result.strip():
                self._set_status(req, RequestStatus.CLARIFYING)
                self.db.commit()
                await self._say(
                    req, requester,
                    t("orch.relay_then_clarify", result=res.result[:3500]))
            else:
                self.db.commit()
                await self._say(req, requester, t("orch.no_signal", error=sig.error))
            return

        if sig.action == Action.CLARIFY:
            self._set_status(req, RequestStatus.CLARIFYING)
            self._event(req, EventKind.CLARIFY, EventDirection.OUT, questions=sig.data["questions"])
            self.db.commit()
            # Relay câu TRẢ LỜI Claude viết (phần text trước khối json) — vd khi user chỉ
            # HỎI thông tin thì đây mới là nội dung họ cần; trước đây bị vứt bỏ.
            answer = strip_json_block(res.result)
            qs = "\n".join(t("orch.clarify_question", q=q) for q in sig.data["questions"])
            body = t("orch.clarify_with_answer", answer=answer, qs=qs) if answer else qs
            await self._say(req, requester, t("orch.clarify_body", body=body))
        elif sig.action == Action.PLAN:
            self._set_status(req, RequestStatus.PLAN_REVIEW)
            self._event(req, EventKind.PLAN, EventDirection.OUT, **sig.data)
            self.db.commit()
            steps = "\n".join(f"{i}. {s}" for i, s in enumerate(sig.data["steps"], 1))
            text = t("orch.plan_text", risk=sig.data.get("risk", "?"),
                     summary=sig.data["summary"], steps=steps)
            await self._say(req, requester, text, buttons=[[
                Button(t("orch.btn.confirm"), cb("confirm", req.id)),
                Button(t("orch.btn.edit"), cb("reject", req.id)),
                Button(t("orch.btn.cancel"), cb("cancel", req.id)),
            ]])

    async def _execute(self, req: Request, fix_feedback: str | None = None) -> None:
        repo = self._repo(req)
        requester = self._requester(req)
        await self._say(req, requester, t("orch.executing"))
        async with _repo_locks[repo.id]:
            self._set_status(req, RequestStatus.EXECUTING)
            self.db.commit()
            branch = req.branch_name or f"bot/req-{req.id}"
            req.branch_name = branch

            try:
                repo_dir = await self._ensure_repo_cloned(repo)
                await self.git.prepare_branch(repo_dir, branch, repo.base_branch)
            except Exception as exc:
                self.db.commit()
                await self._say(req, requester, t("orch.prepare_repo_error", detail=str(exc)))
                return

            prompt = (prompts.fix_request_prompt(fix_feedback) if fix_feedback
                      else prompts.build_request_prompt(req.title, req.body))
            sysp = prompts.executing_system_prompt(
                repo.repo_full_name, repo.base_branch, branch, [repo.prod_branch],
                build_cmd=(repo.settings_json or {}).get("build_cmd"))
            res = await self.claude_run(
                prompt=prompt, cwd=repo_dir, permission_mode=PermissionMode.BYPASS,
                session_id=req.claude_session_id, system_prompt=sysp,
            )
            req.claude_session_id = res.session_id
            if not res.ok or not parse_signal(res.result).ok:
                self.db.commit()
                await self._say(req, requester, t("orch.execute_failed", detail=res.result[:800]))
                return

            try:
                await self.git.commit_all(repo_dir, f"luna: req-{req.id} {req.title[:60]}")
                await self.git.push_branch(repo_dir, branch)
                if not req.pr_number:
                    pr = await self.github.create_pull_request(
                        repo.gh_installation_id, repo.repo_full_name,
                        head=branch, base=repo.base_branch,
                        title=f"[luna] {req.title}", body=res.result[:1000])
                    req.pr_number = pr.get("number")
                    req.pr_url = pr.get("html_url")
            except Exception as exc:
                self.db.commit()
                await self._say(req, requester, t("orch.push_pr_error", detail=str(exc)))
                return

        self._set_status(req, RequestStatus.VERIFY)
        self._event(req, EventKind.SYSTEM, EventDirection.OUT, pr_url=req.pr_url)
        self.db.commit()
        await self._say(req, requester,
                        t("orch.deployed", pr_url=req.pr_url,
                          summary=parse_signal(res.result).data.get("summary", "")),
                        buttons=self._verify_buttons(req))

    def _verify_buttons(self, req: Request) -> list[list["Button"]]:
        return [[
            Button(t("orch.btn.verify_ok"), cb("verify_ok", req.id)),
            Button(t("orch.btn.verify_fix"), cb("verify_fix", req.id)),
            Button(t("orch.btn.cancel"), cb("cancel", req.id)),
        ]]

    def _dev_pipeline_holder(self, req: Request) -> Request | None:
        """Request KHÁC cùng repo đang chiếm 'slot' dev (MERGED_DEV/AWAIT_MANAGER). Serialize:
        chỉ 1 request chưa-release/lúc, nếu không approve cuốn cả dev → mồ côi (app/reconcile.py)."""
        return self.db.scalars(
            select(Request).where(
                Request.repo_id == req.repo_id,
                Request.id != req.id,
                Request.status.in_((RequestStatus.MERGED_DEV, RequestStatus.AWAIT_MANAGER)),
            ).order_by(Request.id)
        ).first()

    async def _merge_to_dev(self, req: Request) -> None:
        holder = self._dev_pipeline_holder(req)
        if holder is not None:
            self.db.commit()  # giữ VERIFY; gửi LẠI nút vì click đã xoá nút (Google Chat)
            await self._say(
                req, self._requester(req),
                t("orch.dev_holder_wait", holder_id=holder.id, id=req.id),
                buttons=self._verify_buttons(req))
            return
        repo = self._repo(req)
        requester = self._requester(req)
        try:
            res = await self.github.merge_pull_request(
                repo.gh_installation_id, repo.repo_full_name, req.pr_number)
        except Exception as exc:
            self.db.commit()
            await self._say(req, requester, t("orch.merge_dev_error", base=repo.base_branch, detail=str(exc)))
            return
        req.dev_merge_sha = (res or {}).get("sha")  # để revert dev / poll deploy theo sha này
        self._set_status(req, RequestStatus.MERGED_DEV)
        self.db.commit()

        # Deploy-gate (opt-in per repo): chờ CI build+deploy + curl trang dev rồi mới mời manager.
        # Chạy nền (poll lâu) để KHÔNG chặn poller. Repo chưa bật → mời manager ngay như cũ.
        settings = get_settings()
        if settings.dev_verify_enabled and post_deploy.dev_verify_configured(repo):
            await self._say(req, requester,
                            t("orch.merged_dev_waiting_deploy", base=repo.base_branch))
            asyncio.create_task(
                post_deploy.verify_after_dev_merge(req.id, settings=settings, github=self.github))
        else:
            await post_deploy.enter_await_manager(self, req)

    async def _merge_to_main(self, req: Request, approver: User, reply_to: str | None = None) -> None:
        if approver.role not in (UserRole.MANAGER, UserRole.ADMIN):
            await self.adapter.send(reply_to or approver.platform_user_id,
                                    t("orch.only_manager"))
            return
        repo = self._repo(req)
        try:
            pr = await self.github.create_pull_request(
                repo.gh_installation_id, repo.repo_full_name,
                head=repo.base_branch, base=repo.prod_branch,
                title=f"[luna] release req-{req.id}", body=req.title)
            await self.github.merge_pull_request(repo.gh_installation_id, repo.repo_full_name, pr["number"])
        except Exception as exc:
            self.db.commit()
            await self._say(req, approver, t("orch.merge_main_error", prod=repo.prod_branch, detail=str(exc)))
            return
        self.db.add(Approval(request_id=req.id, approver_user_id=approver.id,
                             decision=ApprovalDecision.APPROVED))
        self._set_status(req, RequestStatus.MERGED_MAIN)
        self.db.commit()
        self._set_status(req, RequestStatus.CLOSED)
        self.db.commit()
        # Dọn nhánh feature đã merge xong (best-effort) — tránh tích tụ bot/req-* trên repo khách.
        if req.branch_name:
            try:
                await self.github.delete_branch(repo.gh_installation_id, repo.repo_full_name, req.branch_name)
            except Exception as exc:  # noqa: BLE001
                log.warning("xoá nhánh %s req %s lỗi: %s", req.branch_name, req.id, exc)
        await self._say(req, self._requester(req), t("orch.merged_main_closed", id=req.id, prod=repo.prod_branch))

    async def _manager_reject(self, req: Request, approver: User, reply_to: str | None = None) -> None:
        if approver.role not in (UserRole.MANAGER, UserRole.ADMIN):
            await self.adapter.send(reply_to or approver.platform_user_id,
                                    t("orch.only_manager"))
            return
        self.db.add(Approval(request_id=req.id, approver_user_id=approver.id,
                             decision=ApprovalDecision.REJECTED))
        self._set_status(req, RequestStatus.CANCELLED)
        self.db.commit()
        repo = self._repo(req)
        warns = await cleanup_branch(self, req, revert_dev=True)
        msg = t("orch.manager_rejected", id=req.id, base=repo.base_branch)
        if warns:
            msg += t("orch.cleanup_partial_warn", warns="; ".join(warns))
        await self._say(req, self._requester(req), msg)
