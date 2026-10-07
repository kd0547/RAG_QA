"""담당자 알림 메일용 HTML 템플릿."""
from __future__ import annotations
from urllib.parse import quote

import html as html_lib

from entity.type import MailEntity
import markdown


def _markdown_to_email_html(text: str) -> str:
    html = markdown.markdown(
        text,
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

    # 검토/수정 화면
    edit_url = f"{base_url}/mail?task_id={encoded_task_id}"
    send_url = f"{base_url}/mails/{encoded_task_id}/review"

    # 실제 API
    approve_api_url = f"{base_url}/api/mails/{encoded_task_id}/approve"

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
                                            href="{send_url}?action=send"
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
                                전송 전 답변 내용을 다시 확인해주세요.
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
