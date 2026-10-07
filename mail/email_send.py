import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from dotenv import load_dotenv
load_dotenv()  # 같은 폴더의 .env 파일을 읽어옴

SMTP_SERVER = "outlook.office365.com"
SMTP_PORT = 587  # 아래 참고

SENDER_EMAIL = os.environ["MAIL_ID"]       # 환경변수로 관리 권장
SENDER_PASSWORD = os.environ["MAIL_PW"]

def send_email(to_addr: str, subject: str, body: str, html: bool = False):
    msg = MIMEMultipart()
    msg["From"] = SENDER_EMAIL
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "html" if html else "plain", "utf-8"))

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.ehlo()
        server.starttls()   # TLS 암호화 시작
        server.ehlo()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.send_message(msg)
