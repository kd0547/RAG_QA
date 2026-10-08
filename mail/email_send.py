import logging
import mimetypes
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()  # 같은 폴더의 .env 파일을 읽어옴

logger = logging.getLogger(__name__)

SMTP_SERVER = "outlook.office365.com"
SMTP_PORT = 587  # 아래 참고

SENDER_EMAIL = os.environ["MAIL_ID"]       # 환경변수로 관리 권장
SENDER_PASSWORD = os.environ["MAIL_PW"]

def send_email(to_addr: str, subject: str, body: str, html: bool = False,
               attachments: list[dict] | None = None):
    """attachments: [{"filename": 표시할 파일명, "path": 디스크 경로, "mime_type": 선택}]"""
    msg = MIMEMultipart()
    msg["From"] = SENDER_EMAIL
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "html" if html else "plain", "utf-8"))

    for attachment in attachments or []:
        part = _build_attachment(attachment)
        if part is not None:
            msg.attach(part)

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.ehlo()
        server.starttls()   # TLS 암호화 시작
        server.ehlo()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.send_message(msg)


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
