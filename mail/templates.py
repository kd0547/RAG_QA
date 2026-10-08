"""메일 HTML 템플릿: 고객 답변 메일, 담당자 검토 요청 메일, 메일 버튼이 여는 전송 결과 페이지."""
from __future__ import annotations
from urllib.parse import quote

import html as html_lib
import json
import re

from entity.type import MailEntity
import markdown


_FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
_LIST_ITEM_RE = re.compile(r"^\s{0,3}([-*+]|\d+[.)])\s+\S")
_ANY_LIST_ITEM_RE = re.compile(r"^([ \t]*)(?:[-*+]|\d+[.)])\s+\S")
_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")


def _ensure_block_spacing(text: str) -> str:
    """GFM(웹 화면의 remark-gfm)으로 쓴 마크다운을 Python-Markdown이 같은 모양으로 그리도록 고친다.

    LLM 답변에서 자주 나오는 두 가지가 메일에서 깨진다.
    1. `**제목**` 바로 다음 줄에 붙은 표·`- ` 목록: Python-Markdown은 앞에 빈 줄이 없으면 문단으로 보고
       `| 항목 | 사양 | |---|---|` 처럼 한 줄로 이어 붙인다 → 빈 줄을 넣는다.
    2. 2~3칸 들여쓴 하위 목록(`1. 항목` 아래 `   * 세부`): Python-Markdown은 4칸 단위만 하위 목록으로 봐서
       `* 세부`가 글자 그대로 나온다 → 단계마다 4칸으로 맞춘다.
    """
    lines = text.splitlines()
    out: list[str] = []
    fence: str | None = None
    list_indents: list[int] = []  # 현재 목록에서 단계별 원래 들여쓰기

    for i, line in enumerate(lines):
        fence_match = _FENCE_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            if fence is None:
                fence = marker[0]
            elif marker[0] == fence:
                fence = None
            out.append(line)
            continue
        if fence is not None:  # 코드 블록 안은 건드리지 않는다
            out.append(line)
            continue

        prev = out[-1] if out else ""

        item = _ANY_LIST_ITEM_RE.match(line)
        if item:
            indent = len(item.group(1).expandtabs(4))
            if list_indents or indent < 4:  # 목록 밖의 4칸 들여쓰기는 코드 블록이므로 그대로
                while list_indents and list_indents[-1] > indent:
                    list_indents.pop()
                if not list_indents or list_indents[-1] < indent:
                    list_indents.append(indent)
                level = len(list_indents) - 1
                if level > 0:
                    line = " " * (4 * level) + line.lstrip()
        elif line.strip() and not line.startswith((" ", "\t")) and not prev.strip():
            list_indents = []  # 빈 줄 뒤에 들여쓰지 않은 문단이 오면 목록이 끝난 것
        if prev.strip():
            next_line = lines[i + 1] if i + 1 < len(lines) else ""
            starts_table = "|" in line and "|" not in prev and _TABLE_SEPARATOR_RE.match(next_line)
            # 이전 줄이 목록 항목이거나 들여쓴 줄(항목의 이어지는 내용)이면 같은 목록이므로 그대로 둔다
            starts_list = (
                _LIST_ITEM_RE.match(line)
                and not _LIST_ITEM_RE.match(prev)
                and not prev.startswith((" ", "\t"))
            )
            if starts_table or starts_list:
                out.append("")

        out.append(line)

    return "\n".join(out)


def _markdown_to_email_html(text: str) -> str:
    html = markdown.markdown(
        _ensure_block_spacing(text),
        extensions=[
            "tables",
            "fenced_code",
            "sane_lists",
        ],
    )

    styles = {
        "<table>": (
            '<table style="width:100%; border-collapse:collapse; '
            'margin:16px 0; font-size:13px;">'
        ),
        "<th>": (
            '<th style="border:1px solid #e5e7eb; padding:8px 10px; '
            'background:#f9fafb; text-align:left; font-weight:600;">'
        ),
        "<td>": (
            '<td style="border:1px solid #e5e7eb; padding:8px 10px; '
            'vertical-align:top;">'
        ),
        "<pre>": (
            '<pre style="margin:12px 0; padding:12px; '
            'background:#f3f4f6; border-radius:4px; '
            'overflow-x:auto; font-size:12px; line-height:1.5;">'
        ),
        "<code>": (
            '<code style="font-family:Consolas, Monaco, monospace; '
            'font-size:12px;">'
        ),
        "<blockquote>": (
            '<blockquote style="margin:12px 0; padding-left:12px; '
            'border-left:3px solid #d1d5db; color:#6b7280;">'
        ),
    }

    for tag, styled_tag in styles.items():
        html = html.replace(tag, styled_tag)

    return html


def render_answer_email(answer: str) -> str:
    """질문자에게 전달할 AI 답변 메일 HTML."""

    answer_html = _markdown_to_email_html(answer)

    return f"""
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
</head>

<body style="
    margin:0;
    padding:0;
    background:#f5f5f5;
    font-family:'Segoe UI','Malgun Gothic',Arial,sans-serif;
    color:#111827;
">
    <table
        role="presentation"
        width="100%"
        cellpadding="0"
        cellspacing="0"
        border="0"
        style="background:#f5f5f5;"
    >
        <tr>
            <td align="center" style="padding:32px 16px;">

                <table
                    role="presentation"
                    width="100%"
                    cellpadding="0"
                    cellspacing="0"
                    border="0"
                    style="
                        max-width:640px;
                        background:#ffffff;
                        border:1px solid #e5e7eb;
                        border-radius:6px;
                    "
                >

                    <!-- Header -->
                    <tr>
                        <td style="padding:24px 28px 18px;">
                            <h1 style="
                                margin:0 0 6px;
                                font-size:18px;
                                line-height:1.4;
                                font-weight:600;
                                color:#111827;
                            ">
                                문의하신 내용에 대한 답변입니다
                            </h1>

                            <p style="
                                margin:0;
                                font-size:13px;
                                line-height:1.6;
                                color:#6b7280;
                            ">
                                문의해주신 내용에 대해 아래와 같이 답변드립니다.
                            </p>
                        </td>
                    </tr>

                    <!-- Divider -->
                    <tr>
                        <td style="padding:0 28px;">
                            <div style="
                                border-top:1px solid #e5e7eb;
                                height:1px;
                            "></div>
                        </td>
                    </tr>

                    <!-- Answer -->
                    <tr>
                        <td style="padding:24px 28px;">
                            <div style="
                                font-size:14px;
                                line-height:1.7;
                                color:#374151;
                                word-break:break-word;
                            ">
                                {answer_html}
                            </div>
                        </td>
                    </tr>

                    <!-- Footer -->
                    <tr>
                        <td style="
                            padding:16px 28px;
                            background:#fafafa;
                            border-top:1px solid #e5e7eb;
                        ">
                            <p style="
                                margin:0;
                                font-size:11px;
                                line-height:1.5;
                                color:#9ca3af;
                            ">
                                본 메일은 문의 내용에 대한 답변 안내 메일입니다.
                            </p>
                        </td>
                    </tr>

                </table>

            </td>
        </tr>
    </table>
</body>
</html>
"""



def render_mail_review_email(
    mail: MailEntity,
    answer: str,
    task_id: str,
    base_url: str,
) -> str:
    """AI 답변 초안을 담당자에게 검토 요청하는 메일 HTML."""

    subject = html_lib.escape(mail.subject)
    sender = html_lib.escape(mail.sender)
    body_html = html_lib.escape(mail.body).replace("\n", "<br>")

    answer_html = _markdown_to_email_html(answer)

    encoded_task_id = quote(task_id, safe="")
    base_url = base_url.rstrip("/")

    # 답변 수정: 웹 앱의 메일 검토 화면을 연다
    edit_url = f"{base_url}/mail?task_id={encoded_task_id}"
    # 답변 전송: 웹 앱을 거치지 않고 바로 전송하는 단독 페이지 (app/routers/mail_links.py)
    send_url = f"{base_url}/mails/{encoded_task_id}/send"

    return f"""
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
</head>

<body style="
    margin:0;
    padding:0;
    background:#f5f5f5;
    font-family:'Segoe UI','Malgun Gothic',Arial,sans-serif;
    color:#111827;
">
    <table
        role="presentation"
        width="100%"
        cellpadding="0"
        cellspacing="0"
        border="0"
        style="background:#f5f5f5;"
    >
        <tr>
            <td align="center" style="padding:32px 16px;">

                <table
                    role="presentation"
                    width="100%"
                    cellpadding="0"
                    cellspacing="0"
                    border="0"
                    style="
                        max-width:640px;
                        background:#ffffff;
                        border:1px solid #e5e7eb;
                        border-radius:6px;
                    "
                >

                    <!-- Header -->
                    <tr>
                        <td style="padding:24px 28px 18px;">
                            <h1 style="
                                margin:0 0 6px;
                                font-size:18px;
                                font-weight:600;
                                color:#111827;
                            ">
                                메일 답변 검토 요청
                            </h1>

                            <p style="
                                margin:0;
                                font-size:13px;
                                line-height:1.6;
                                color:#6b7280;
                            ">
                                AI가 답변 초안을 생성했습니다.
                                내용을 확인한 후 수정하거나 전송해주세요.
                            </p>
                        </td>
                    </tr>

                    <!-- Divider -->
                    <tr>
                        <td style="padding:0 28px;">
                            <div style="border-top:1px solid #e5e7eb;"></div>
                        </td>
                    </tr>

                    <!-- Mail Info -->
                    <tr>
                        <td style="padding:22px 28px 0;">
                            <table
                                role="presentation"
                                width="100%"
                                cellpadding="0"
                                cellspacing="0"
                                border="0"
                            >
                                <tr>
                                    <td style="
                                        width:80px;
                                        padding-bottom:8px;
                                        font-size:13px;
                                        color:#6b7280;
                                    ">
                                        보낸 사람
                                    </td>

                                    <td style="
                                        padding-bottom:8px;
                                        font-size:13px;
                                        color:#111827;
                                    ">
                                        {sender}
                                    </td>
                                </tr>

                                <tr>
                                    <td style="
                                        width:80px;
                                        font-size:13px;
                                        color:#6b7280;
                                    ">
                                        제목
                                    </td>

                                    <td style="
                                        font-size:13px;
                                        font-weight:500;
                                        color:#111827;
                                    ">
                                        {subject}
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>

                    <!-- Content -->
                    <tr>
                        <td style="padding:24px 28px;">

                            <p style="
                                margin:0 0 8px;
                                font-size:12px;
                                font-weight:600;
                                color:#6b7280;
                            ">
                                원본 질문
                            </p>

                            <div style="
                                padding:16px;
                                margin-bottom:22px;
                                background:#f9fafb;
                                border:1px solid #e5e7eb;
                                border-radius:5px;
                                font-size:14px;
                                line-height:1.7;
                                color:#374151;
                                word-break:break-word;
                            ">
                                {body_html}
                            </div>

                            <p style="
                                margin:0 0 8px;
                                font-size:12px;
                                font-weight:600;
                                color:#6b7280;
                            ">
                                AI 답변 초안
                            </p>

                            <div style="
                                padding:16px;
                                background:#ffffff;
                                border:1px solid #d1d5db;
                                border-radius:5px;
                                font-size:14px;
                                line-height:1.7;
                                color:#374151;
                                word-break:break-word;
                            ">
                                {answer_html}
                            </div>

                        </td>
                    </tr>

                    <!-- Actions -->
                    <tr>
                        <td
                            align="center"
                            style="padding:0 28px 28px;"
                        >
                            <table
                                role="presentation"
                                cellpadding="0"
                                cellspacing="0"
                                border="0"
                            >
                                <tr>

                                    <!-- 수정 -->
                                    <td style="padding-right:8px;">
                                        <a
                                            href="{edit_url}"
                                            style="
                                                display:inline-block;
                                                padding:11px 22px;
                                                background:#ffffff;
                                                border:1px solid #d1d5db;
                                                border-radius:5px;
                                                color:#374151;
                                                font-size:14px;
                                                font-weight:600;
                                                text-decoration:none;
                                            "
                                        >
                                            답변 수정
                                        </a>
                                    </td>

                                    <!-- 전송 -->
                                    <td style="padding-left:8px;">
                                        <a
                                            href="{send_url}"
                                            style="
                                                display:inline-block;
                                                padding:11px 22px;
                                                background:#2563eb;
                                                border:1px solid #2563eb;
                                                border-radius:5px;
                                                color:#ffffff;
                                                font-size:14px;
                                                font-weight:600;
                                                text-decoration:none;
                                            "
                                        >
                                            답변 전송
                                        </a>
                                    </td>

                                </tr>
                            </table>

                            <p style="
                                margin:12px 0 0;
                                font-size:11px;
                                line-height:1.5;
                                color:#9ca3af;
                            ">
                                '답변 전송'을 누르면 위 초안이 바로 고객에게 전송됩니다.
                                고칠 내용이 있으면 '답변 수정'을 눌러주세요.
                            </p>

                        </td>
                    </tr>

                    <!-- Footer -->
                    <tr>
                        <td style="
                            padding:14px 28px;
                            background:#fafafa;
                            border-top:1px solid #e5e7eb;
                        ">
                            <p style="
                                margin:0;
                                font-size:11px;
                                line-height:1.5;
                                color:#9ca3af;
                            ">
                                AI가 생성한 답변이므로 전송 전 내용을 확인해주세요.
                            </p>
                        </td>
                    </tr>

                </table>

            </td>
        </tr>
    </table>
</body>
</html>
"""


# 상태값 → 화면 표시 이름 (frontend/src/mail/format.ts 의 STATUS_META 와 맞춘다)
_STATUS_LABEL = {
    "pending": "초안 생성 대기",
    "drafted": "초안 준비",
    "in_review": "검토 중",
    "rejected": "반려",
    "approved": "전송 대기",
    "sent": "전송 완료",
    "failed": "전송 실패",
}


def render_quick_send_page(
    task_id: str,
    subject: str | None,
    sender: str | None,
    status: str | None,
) -> str:
    """검토 요청 메일의 '답변 전송' 버튼이 여는 단독 페이지 HTML.

    페이지가 열리면 스크립트가 POST /mails/{task_id}/approve 를 호출해 바로 전송하고 결과만 보여준다.
    GET 만으로 전송하지 않는 이유: 메일 보안 스캐너(링크 미리 열기)가 사람 대신 링크를 열어도
    스크립트를 실행하지 않는 한 전송되지 않게 하려는 것이다.
    status 가 None 이면 task 를 찾지 못한 경우다.
    """
    encoded_task_id = quote(task_id, safe="")
    review_url = f"/mail/review?task_id={encoded_task_id}"

    if status is None:
        initial = "error"
        title, message = "메일을 찾을 수 없습니다", "이미 삭제되었거나 잘못된 링크입니다."
    elif status != "drafted":
        initial = "done-before"
        label = _STATUS_LABEL.get(status, status)
        title, message = "이미 처리된 메일입니다", f"현재 상태: {label}. 다시 전송하지 않았습니다."
    else:
        initial = "sending"
        title, message = "답변을 전송하는 중…", "잠시만 기다려주세요."

    subject_html = html_lib.escape(subject or "")
    sender_html = html_lib.escape(sender or "")
    # <script> 안에 넣는 값은 JSON 으로 만들고 '</' 를 끊어 스크립트 탈출을 막는다
    approve_path = json.dumps(f"/mails/{encoded_task_id}/approve").replace("</", "<\\/")
    initial_js = json.dumps(initial)

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>답변 전송</title>
<style>
    :root {{ --ink:#141C2B; --muted:#6b7280; --line:#E9EDF1; --brand:#00A4E4; --ok:#0f9d58; --danger:#E5484D; }}
    * {{ box-sizing:border-box; }}
    body {{
        margin:0; min-height:100vh; display:flex; align-items:center; justify-content:center;
        padding:24px 16px; background:#FAFBFC; color:var(--ink);
        font-family:'Pretendard','Segoe UI','Malgun Gothic',Arial,sans-serif;
    }}
    main {{ width:100%; max-width:440px; text-align:center; }}
    .icon {{
        width:56px; height:56px; margin:0 auto 20px; border-radius:50%;
        display:flex; align-items:center; justify-content:center; font-size:26px; font-weight:700;
    }}
    .sending .icon {{ border:4px solid #D6F0FB; border-top-color:var(--brand); animation:spin .8s linear infinite; }}
    .done .icon, .done-before .icon {{ background:#E6F6EE; color:var(--ok); }}
    .done-before .icon {{ background:#F5F6F7; color:var(--muted); }}
    .error .icon {{ background:#FFE8E9; color:var(--danger); }}
    @keyframes spin {{ to {{ transform:rotate(360deg); }} }}
    h1 {{ margin:0 0 8px; font-size:20px; letter-spacing:-0.01em; }}
    p {{ margin:0; font-size:14px; line-height:1.6; color:var(--muted); }}
    .mail {{ margin:24px 0 0; padding:14px 0 0; border-top:1px solid var(--line); text-align:left; }}
    .mail dt {{ font-size:11px; color:var(--muted); }}
    .mail dd {{ margin:2px 0 10px; font-size:13px; font-weight:600; word-break:break-all; }}
    a.link {{ display:inline-block; margin-top:18px; font-size:13px; font-weight:600; color:#0092CC; text-decoration:none; }}
    a.link:hover {{ text-decoration:underline; }}
</style>
</head>
<body>
<main id="root" class="{initial}">
    <div class="icon" id="icon" aria-hidden="true"></div>
    <h1 id="title">{html_lib.escape(title)}</h1>
    <p id="message">{html_lib.escape(message)}</p>
    <dl class="mail">
        <dt>제목</dt><dd>{subject_html or "—"}</dd>
        <dt>받는 사람</dt><dd>{sender_html or "—"}</dd>
    </dl>
    <a class="link" href="{review_url}">웹에서 열어 확인하기 →</a>
</main>
<script>
(function () {{
    var root = document.getElementById("root");
    var icon = document.getElementById("icon");
    var title = document.getElementById("title");
    var message = document.getElementById("message");

    function show(state, t, m) {{
        root.className = state;
        icon.textContent = state === "done" ? "✓" : state === "error" ? "!" : state === "done-before" ? "–" : "";
        title.textContent = t;
        message.textContent = m;
    }}

    // approve API 의 오류 코드(detail) → 안내 문구
    var ERROR_TEXT = {{
        not_found: "메일을 찾을 수 없습니다. 이미 삭제되었거나 잘못된 링크입니다.",
        smtp_error: "메일 서버 오류로 전송하지 못했습니다. 웹에서 열어 재전송해주세요."
    }};

    var initial = {initial_js};
    if (initial !== "sending") {{
        show(initial, title.textContent, message.textContent);
        return;
    }}

    fetch({approve_path}, {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: "{{}}"
    }})
        .then(function (res) {{
            return res.json().catch(function () {{ return {{}}; }}).then(function (data) {{
                if (res.ok) {{
                    show("done", "전송 완료", (data.to ? data.to + " 에게 " : "") + "답변을 보냈습니다. 이 창은 닫아도 됩니다.");
                }} else {{
                    show("error", "전송하지 못했습니다", ERROR_TEXT[data.detail] || data.detail || ("오류 " + res.status));
                }}
            }});
        }})
        .catch(function () {{
            show("error", "전송하지 못했습니다", "서버에 연결할 수 없습니다.");
        }});
}})();
</script>
</body>
</html>
"""
