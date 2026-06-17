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

from app import git_ops, prompts
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
from app.parsing import Action, parse_signal

log = logging.getLogger("luna.orchestrator")

_repo_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)


def cb(action: str, req_id: int) -> str:
    return f"{action}:{req_id}"


def parse_cb(data: str) -> tuple[str, int] | None:
    try:
        action, rid = data.split(":", 1)
        return action, int(rid)
    except (ValueError, AttributeError):
        return None


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
        self._event(req, EventKind.SYSTEM, EventDirection.OUT, payload=text[:500])
        await self.adapter.send(user.platform_user_id, text, buttons)

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
                             title: str, body: str | None) -> Request:
        req = Request(
            tenant_id=repo.tenant_id, repo_id=repo.id, requester_user_id=requester.id,
            title=title, body=body, status=RequestStatus.NEW,
        )
        self.db.add(req)
        self.db.flush()
        self._event(req, EventKind.MSG, EventDirection.IN, actor_id=requester.id, title=title)
        self.db.commit()
        await self._analyze(req)
        return req

    async def handle_message(self, req: Request, actor: User, text: str) -> None:
        """Tin text: ý nghĩa tuỳ state hiện tại."""
        self._event(req, EventKind.MSG, EventDirection.IN, actor_id=actor.id, text=text[:500])
        if req.status == RequestStatus.CLARIFYING:
            await self._analyze(req, clarifications=[text])
        elif req.status == RequestStatus.VERIFY:
            await self._execute(req, fix_feedback=text)
        else:
            self.db.commit()  # chỉ lưu lại, không chuyển state

    async def handle_callback(self, req: Request, actor: User, data: str) -> None:
        parsed = parse_cb(data)
        if not parsed:
            return
        action, _ = parsed
        self._event(req, EventKind.CONFIRM, EventDirection.IN, actor_id=actor.id, action=action)

        if action == "confirm" and req.status == RequestStatus.PLAN_REVIEW:
            await self._execute(req)
        elif action == "reject" and req.status == RequestStatus.PLAN_REVIEW:
            self._set_status(req, RequestStatus.CLARIFYING)
            self.db.commit()
            await self._say(req, self._requester(req),
                            "Kế hoạch bị từ chối. Anh/chị muốn điều chỉnh gì? (trả lời tin này)")
        elif action == "verify_ok" and req.status == RequestStatus.VERIFY:
            await self._merge_to_dev(req)
        elif action == "verify_fix" and req.status == RequestStatus.VERIFY:
            self.db.commit()
            await self._say(req, self._requester(req),
                            "🔧 Cần sửa gì? Trả lời tin này để bot sửa tiếp.")
        elif action == "mgr_approve" and req.status == RequestStatus.AWAIT_MANAGER:
            await self._merge_to_main(req, actor)
        elif action == "mgr_reject" and req.status == RequestStatus.AWAIT_MANAGER:
            await self._manager_reject(req, actor)
        elif action == "cancel":
            self._set_status(req, RequestStatus.CANCELLED)
            self.db.commit()
            await self._say(req, self._requester(req), "❌ Đã huỷ yêu cầu.")

    # ---------------- phases ----------------
    async def _analyze(self, req: Request, clarifications: list[str] | None = None) -> None:
        repo = self._repo(req)
        requester = self._requester(req)
        self._set_status(req, RequestStatus.ANALYZING)
        self.db.commit()
        await self._say(req, requester,
                        "📥 Em đã nhận yêu cầu, chờ em kiểm tra rồi báo lại nhé…")

        try:
            repo_dir = await self._ensure_repo_cloned(repo)
        except Exception as exc:  # noqa: BLE001
            self.db.commit()
            await self._say(req, requester, f"⚠️ Không chuẩn bị được repo để phân tích: {exc}")
            return

        prompt = prompts.build_request_prompt(req.title, req.body, clarifications)
        sysp = prompts.analyzing_system_prompt(repo.repo_full_name, repo.base_branch)
        res = await self.claude_run(
            prompt=prompt, cwd=repo_dir,
            permission_mode=PermissionMode.READONLY,
            session_id=req.claude_session_id, system_prompt=sysp,
        )
        req.claude_session_id = res.session_id
        self._event(req, EventKind.SYSTEM, EventDirection.OUT, ok=res.ok, result=res.result[:500])

        if not res.ok:
            self.db.commit()
            await self._say(req, requester, f"⚠️ Lỗi phân tích, cần người can thiệp:\n{res.result}")
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
                    f"{res.result[:3500]}\n\n———\nAnh/chị muốn em *thực hiện thay đổi gì*? "
                    "Trả lời cụ thể để em lập kế hoạch.")
            else:
                self.db.commit()
                await self._say(req, requester,
                                f"⚠️ Không hiểu phản hồi của Claude ({sig.error}). Cần người can thiệp.")
            return

        if sig.action == Action.CLARIFY:
            self._set_status(req, RequestStatus.CLARIFYING)
            self._event(req, EventKind.CLARIFY, EventDirection.OUT, questions=sig.data["questions"])
            self.db.commit()
            qs = "\n".join(f"❓ {q}" for q in sig.data["questions"])
            await self._say(req, requester, f"Cần làm rõ:\n{qs}\n\n(trả lời tin này)")
        elif sig.action == Action.PLAN:
            self._set_status(req, RequestStatus.PLAN_REVIEW)
            self._event(req, EventKind.PLAN, EventDirection.OUT, **sig.data)
            self.db.commit()
            steps = "\n".join(f"{i}. {s}" for i, s in enumerate(sig.data["steps"], 1))
            text = (f"📋 Kế hoạch (risk: {sig.data.get('risk', '?')}):\n{sig.data['summary']}\n\n{steps}"
                    "\n\n(Bấm nút, hoặc trả lời: ok để duyệt · sửa · huỷ)")
            await self._say(req, requester, text, buttons=[[
                Button("✅ Confirm", cb("confirm", req.id)),
                Button("✏️ Sửa", cb("reject", req.id)),
                Button("❌ Huỷ", cb("cancel", req.id)),
            ]])

    async def _execute(self, req: Request, fix_feedback: str | None = None) -> None:
        repo = self._repo(req)
        requester = self._requester(req)
        await self._say(req, requester,
                        "🛠 Em bắt đầu thực hiện thay đổi + tạo PR, xong em báo lại nhé…")
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
                await self._say(req, requester, f"⚠️ Lỗi chuẩn bị repo: {exc}")
                return

            prompt = (prompts.fix_request_prompt(fix_feedback) if fix_feedback
                      else prompts.build_request_prompt(req.title, req.body))
            sysp = prompts.executing_system_prompt(
                repo.repo_full_name, repo.base_branch, branch, [repo.prod_branch])
            res = await self.claude_run(
                prompt=prompt, cwd=repo_dir, permission_mode=PermissionMode.BYPASS,
                session_id=req.claude_session_id, system_prompt=sysp,
            )
            req.claude_session_id = res.session_id
            if not res.ok or not parse_signal(res.result).ok:
                self.db.commit()
                await self._say(req, requester,
                                f"⚠️ Thực thi gặp vấn đề, cần người can thiệp:\n{res.result[:800]}")
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
                await self._say(req, requester, f"⚠️ Lỗi push/PR: {exc}")
                return

        self._set_status(req, RequestStatus.VERIFY)
        self._event(req, EventKind.SYSTEM, EventDirection.OUT, pr_url=req.pr_url)
        self.db.commit()
        await self._say(req, requester,
                        f"✅ Đã triển khai. PR: {req.pr_url}\n{parse_signal(res.result).data.get('summary', '')}"
                        "\n\n(Bấm nút, hoặc trả lời: ok nếu đạt · huỷ)",
                        buttons=[[
                            Button("✅ Đạt", cb("verify_ok", req.id)),
                            Button("🔧 Cần sửa", cb("verify_fix", req.id)),
                            Button("❌ Huỷ", cb("cancel", req.id)),
                        ]])

    async def _merge_to_dev(self, req: Request) -> None:
        repo = self._repo(req)
        requester = self._requester(req)
        try:
            await self.github.merge_pull_request(repo.gh_installation_id, repo.repo_full_name, req.pr_number)
        except Exception as exc:
            self.db.commit()
            await self._say(req, requester, f"⚠️ Merge vào {repo.base_branch} lỗi: {exc}")
            return
        self._set_status(req, RequestStatus.MERGED_DEV)
        self.db.commit()
        self._set_status(req, RequestStatus.AWAIT_MANAGER)
        self.db.commit()
        await self._say(req, requester, f"✅ Đã merge vào `{repo.base_branch}`. Đang chờ manager duyệt.")
        await self._notify_managers(req, repo)

    async def _notify_managers(self, req: Request, repo: Repository) -> None:
        managers = self.db.scalars(
            select(User).where(User.tenant_id == repo.tenant_id, User.role == UserRole.MANAGER,
                               User.platform_user_id.is_not(None))
        ).all()
        for m in managers:
            await self.adapter.send(
                m.platform_user_id,
                f"🔔 Yêu cầu #{req.id} '{req.title}' đã sẵn sàng merge `{repo.prod_branch}`.\nPR: {req.pr_url}"
                "\n\n(Bấm nút, hoặc trả lời: ok để duyệt · từ chối)",
                [[Button("✅ Cho merge", cb("mgr_approve", req.id)),
                  Button("❌ Từ chối", cb("mgr_reject", req.id))]],
            )

    async def _merge_to_main(self, req: Request, approver: User) -> None:
        if approver.role not in (UserRole.MANAGER, UserRole.ADMIN):
            await self.adapter.send(approver.platform_user_id, "⛔ Chỉ manager được duyệt merge.")
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
            await self._say(req, approver, f"⚠️ Merge `{repo.prod_branch}` lỗi: {exc}")
            return
        self.db.add(Approval(request_id=req.id, approver_user_id=approver.id,
                             decision=ApprovalDecision.APPROVED))
        self._set_status(req, RequestStatus.MERGED_MAIN)
        self.db.commit()
        self._set_status(req, RequestStatus.CLOSED)
        self.db.commit()
        await self._say(req, self._requester(req), f"🎉 Yêu cầu #{req.id} đã merge `{repo.prod_branch}` và đóng.")

    async def _manager_reject(self, req: Request, approver: User) -> None:
        if approver.role not in (UserRole.MANAGER, UserRole.ADMIN):
            await self.adapter.send(approver.platform_user_id, "⛔ Chỉ manager được duyệt merge.")
            return
        self.db.add(Approval(request_id=req.id, approver_user_id=approver.id,
                             decision=ApprovalDecision.REJECTED))
        self._set_status(req, RequestStatus.CANCELLED)
        self.db.commit()
        await self._say(req, self._requester(req), f"❌ Manager từ chối merge yêu cầu #{req.id}.")
