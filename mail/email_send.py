import io
import logging
import mimetypes
import smtplib
import time
from dataclasses import dataclass
from email import encoders
from email.generator import BytesGenerator
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from enum import Enum
from pathlib import Path

from dotenv import load_dotenv

from logging_config import mask_email

load_dotenv()  # 같은 폴더의 .env 파일을 읽어옴

logger = logging.getLogger(__name__)

SMTP_SERVER = "outlook.office365.com"
SMTP_PORT = 587  # 아래 참고

SENDER_EMAIL = os.environ["MAIL_ID"]       # 환경변수로 관리 권장
SENDER_PASSWORD = os.environ["MAIL_PW"]

class SendOutcome(Enum):
    SENT = "sent"
    FAILED = "send_failed"      # 서버가 받지 않았음이 확실하다 → 담당자가 다시 승인할 수 있다
    UNKNOWN = "send_unknown"    # 본문을 보내다 끊겨 서버가 받았는지 모른다 → 담당자가 확인한다


@dataclass
class SendResult:
    outcome: SendOutcome
    detail: str                           # SMTP 응답 코드·예외 이름
    cleanup_warning: str | None = None    # 서버가 수락한 뒤 연결 정리(quit)에서 난 오류


# 연결이 멈춰 sending 상태로 무한정 붙잡히지 않게 한다. 본문 전송 중 시간 초과는 UNKNOWN이 된다.
SMTP_TIMEOUT_SECONDS = 60


def send_email(to_addr: str, subject: str, body: str, html: bool = False,
               attachments: list[dict] | None = None) -> SendResult:
    """메일을 보내고 결과를 돌려준다. 예외를 던지지 않는다.

    attachments: [{"filename": 표시할 파일명, "path": 디스크 경로, "mime_type": 선택}]

    결과는 서버가 메일을 수락했는지(DATA 뒤 250 응답)를 기준으로 나눈다.
    - 연결·로그인·MAIL·RCPT 단계 실패, DATA 거절 응답 → FAILED (서버가 받지 않았다)
    - DATA 본문 전송 중 끊김·시간 초과 → UNKNOWN (받았을 수도 있다. 자동으로 다시 보내지 않는다)
    - DATA 250 → SENT. 그 뒤 quit 실패는 SENT를 유지하고 cleanup_warning에 남긴다
    send_message()는 이 단계들을 한 번에 처리해 어디서 실패했는지 알 수 없으므로 mail/rcpt/data를 직접 부른다.
    """
    started = time.perf_counter()
    server: smtplib.SMTP | None = None
    try:
        msg = _build_message(to_addr, subject, body, html, attachments)
        payload = _flatten(msg)
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=SMTP_TIMEOUT_SECONDS)
        server.ehlo()
        server.starttls()   # TLS 암호화 시작
        server.ehlo()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        code, response = server.mail(SENDER_EMAIL)
        if code != 250:
            return _finish(server, SendResult(SendOutcome.FAILED, f"MAIL {code} {_text(response)}"), to_addr, started)
        code, response = server.rcpt(to_addr)
        if code not in (250, 251):
            return _finish(server, SendResult(SendOutcome.FAILED, f"RCPT {code} {_text(response)}"), to_addr, started)
    except Exception as exc:
        return _finish(server, SendResult(SendOutcome.FAILED, _describe(exc)), to_addr, started)

    try:
        code, response = server.data(payload)
    except smtplib.SMTPResponseException as exc:
        # DATA 명령 자체를 거절(354가 아님)한 경우. 본문을 보내기 전이므로 수락되지 않았다.
        return _finish(server, SendResult(SendOutcome.FAILED, f"DATA {exc.smtp_code} {_text(exc.smtp_error)}"), to_addr, started)
    except Exception as exc:
        # 본문을 보내는 중 끊김·시간 초과: 서버가 받았는지 알 수 없다
        return _finish(server, SendResult(SendOutcome.UNKNOWN, _describe(exc)), to_addr, started)

    if code != 250:
        return _finish(server, SendResult(SendOutcome.FAILED, f"DATA {code} {_text(response)}"), to_addr, started)

    attached = len(msg.get_payload()) - 1  # 본문 파트를 뺀 실제 첨부 수 (없는 파일은 건너뜀)
    result = SendResult(SendOutcome.SENT, f"DATA {code}")
    try:
        server.quit()
    except Exception as exc:
        result.cleanup_warning = f"quit 실패: {_describe(exc)}"
        _close(server)
    logger.info(
        "메일 발송 완료: to=%s, subject=%s, attachments=%d, %.1f초%s",
        mask_email(to_addr), subject, attached, time.perf_counter() - started,
        f", 경고={result.cleanup_warning}" if result.cleanup_warning else "",
    )
    return result


def _build_message(to_addr: str, subject: str, body: str, html: bool, attachments: list[dict] | None) -> MIMEMultipart:
    msg = MIMEMultipart()
    msg["From"] = SENDER_EMAIL
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "html" if html else "plain", "utf-8"))

    for attachment in attachments or []:
        part = _build_attachment(attachment)
        if part is not None:
            msg.attach(part)
    return msg


def _flatten(msg: MIMEMultipart) -> bytes:
    """smtplib.send_message와 같은 방식(CRLF 줄바꿈)으로 메시지를 바이트로 만든다."""
    with io.BytesIO() as buffer:
        BytesGenerator(buffer).flatten(msg, linesep="\r\n")
        return buffer.getvalue()


def _finish(server: smtplib.SMTP | None, result: SendResult, to_addr: str, started: float) -> SendResult:
    """실패·불명 결과를 로그로 남기고 연결을 닫는다."""
    if server is not None:
        _close(server)
    logger.warning(
        "메일 발송 %s: to=%s, %s, %.1f초",
        "실패" if result.outcome == SendOutcome.FAILED else "결과 불명",
        mask_email(to_addr), result.detail, time.perf_counter() - started,
    )
    return result


def _close(server: smtplib.SMTP) -> None:
    try:
        server.close()
    except Exception:
        pass


def _describe(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:500]


def _text(response) -> str:
    if isinstance(response, bytes):
        return response.decode("utf-8", "replace")[:300]
    return str(response)[:300]


def _build_attachment(attachment: dict) -> MIMEBase | None:
    path = Path(attachment["path"])
    if not path.is_file():
        # 문서가 지워졌어도 답변 메일은 나가도록 해당 첨부만 건너뜀
        logger.warning("첨부할 파일이 없어 건너뜀: %s", path)
        return None

    filename = attachment.get("filename") or path.name
    mime_type = attachment.get("mime_type") or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    maintype, _, subtype = mime_type.partition("/")

    part = MIMEBase(maintype, subtype or "octet-stream")
    part.set_payload(path.read_bytes())
    encoders.encode_base64(part)
    # 한글 파일명이 깨지지 않도록 RFC 2231 형식으로 넣는다
    part.add_header("Content-Disposition", "attachment", filename=("utf-8", "", filename))
    return part
