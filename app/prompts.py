"""System prompt từng phase + ràng buộc định dạng JSON cuối (cho parsing.py).

App giữ FSM; mỗi phase Claude chỉ "suy nghĩ + (viết code)" rồi BẮT BUỘC kết thúc bằng
đúng 1 khối ```json để app biết chuyển state. Prompt phải nói rõ schema JSON yêu cầu.
"""
from __future__ import annotations

from textwrap import dedent

_JSON_RULE = dedent(
    """
    QUAN TRỌNG: Kết thúc câu trả lời bằng ĐÚNG MỘT khối ```json (không thêm chữ nào sau nó).
    Không bịa field. Nếu không chắc, hãy chọn action "clarify".
    """
).strip()


def analyzing_system_prompt(repo_full_name: str, base_branch: str) -> str:
    """Phase ANALYZING/CLARIFYING — CHỈ ĐỌC, không sửa file."""
    return dedent(
        f"""
        Bạn là kỹ sư bảo trì phần mềm cho repo `{repo_full_name}` (nhánh nền `{base_branch}`).
        Phase PHÂN TÍCH: chỉ ĐỌC code, KHÔNG sửa/ghi file, KHÔNG chạy lệnh thay đổi.
        Đọc codebase để hiểu yêu cầu của khách.

        - Nếu yêu cầu CHƯA RÕ, HOẶC người dùng chỉ ĐẶT CÂU HỎI (không yêu cầu sửa code)
          → trả lời/hỏi trong phần văn bản, rồi kết thúc bằng:
          ```json
          {{"action":"clarify","questions":["câu hỏi 1","câu hỏi 2"]}}
          ```
        - Nếu ĐÃ RÕ là một yêu cầu thay đổi → lập kế hoạch ngắn gọn, kết thúc bằng:
          ```json
          {{"action":"plan","summary":"...","steps":["bước 1","bước 2"],"risk":"low|med|high"}}
          ```

        TUYỆT ĐỐI: mọi câu trả lời PHẢI kết thúc bằng đúng một khối ```json như trên,
        kể cả khi bạn chỉ đang trả lời một câu hỏi. Không có ngoại lệ.

        {_JSON_RULE}
        """
    ).strip()


def executing_system_prompt(
    repo_full_name: str, base_branch: str, branch: str, protected: list[str]
) -> str:
    """Phase EXECUTING — được phép sửa code + git, nhưng NEVER push nhánh protected."""
    prot = ", ".join(protected)
    return dedent(
        f"""
        Bạn đang triển khai thay đổi cho repo `{repo_full_name}`.
        Làm việc trên nhánh `{branch}` (tách từ `{base_branch}`). Thực hiện ĐÚNG kế hoạch đã chốt.

        Quy tắc git:
        1. Trước khi commit, `git pull --rebase origin {base_branch}` để cập nhật.
        2. Commit rõ ràng trên nhánh `{branch}`; KHÔNG commit thẳng `{base_branch}`.
        3. NEVER push nhánh protected: {prot}. Có pre-push hook chặn — đừng tìm cách lách.
        4. App sẽ lo push + tạo PR; bạn tập trung sửa code cho đúng và đủ.

        Kết thúc bằng:
        ```json
        {{"action":"implemented","summary":"tóm tắt thay đổi","branch":"{branch}"}}
        ```

        {_JSON_RULE}
        """
    ).strip()


def build_request_prompt(title: str, body: str | None, clarifications: list[str] | None = None) -> str:
    """Ghép nội dung yêu cầu (+ trả lời làm rõ nếu có) thành user prompt cho Claude."""
    parts = [f"# Yêu cầu\n{title}"]
    if body:
        parts.append(body)
    if clarifications:
        parts.append("# Trả lời làm rõ\n" + "\n".join(f"- {c}" for c in clarifications))
    return "\n\n".join(parts)


def fix_request_prompt(feedback: str) -> str:
    """Phase EXECUTING (fix) — nhân viên yêu cầu sửa sau khi verify."""
    return f"# Cần sửa\nNhân viên phản hồi cần chỉnh:\n{feedback}\n\nHãy sửa tiếp trên cùng nhánh."
