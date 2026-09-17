import poplib
import base64
import os
from email import parser
import msal
from dotenv import load_dotenv
from email.utils import parsedate_to_datetime, parseaddr

from entity.type import MailEntity

load_dotenv()
from email.header import decode_header

POP3_SERVER = "outlook.office365.com"
POP3_PORT = 995

CLIENT_ID = os.environ["CLIENT_ID"]
TENANT_ID = os.environ["TENANT_ID"]
USER_EMAIL = os.environ["MAIL_ID"]

AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPES = ["https://outlook.office365.com/POP.AccessAsUser.All"]
TOKEN_CACHE_FILE = "storage/token_cache.bin"
import logging
logger = logging.getLogger(__name__)




def decode_mime_header(value: str) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    decoded = ""
    for text, charset in parts:
        if isinstance(text, bytes):
            decoded += text.decode(charset or "utf-8", errors="ignore")
        else:
            decoded += text
    return decoded


def get_access_token():
    # 토큰 캐시 로드 (있으면 브라우저 로그인 생략)
    cache = msal.SerializableTokenCache()
    if os.path.exists(TOKEN_CACHE_FILE):
        cache.deserialize(open(TOKEN_CACHE_FILE, "r").read())

    app = msal.PublicClientApplication(
        CLIENT_ID, authority=AUTHORITY, token_cache=cache
    )

    result = None
    accounts = app.get_accounts()
    if accounts:
        # 캐시된 계정으로 조용히 갱신 시도
        result = app.acquire_token_silent(SCOPES, account=accounts[0])

    if not result:
        # 최초 1회: 브라우저가 열리고 로그인 + 동의 화면
        result = app.acquire_token_interactive(SCOPES)

    # 캐시 저장
    if cache.has_state_changed:
        with open(TOKEN_CACHE_FILE, "w") as f:
            f.write(cache.serialize())

    if "access_token" not in result:
        raise RuntimeError(
            f"토큰 획득 실패: {result.get('error')} / {result.get('error_description')}"
        )

    return result["access_token"]


def build_xoauth2_string(user: str, token: str) -> str:
    return f"user={user}\x01auth=Bearer {token}\x01\x01"

def extract_email_address(from_header: str) -> str:
    """'김동욱 <dongwook.kim@trigem.co.kr>' -> 'dongwook.kim@trigem.co.kr'"""
    name, addr = parseaddr(from_header)
    return addr

def get_body(msg):
    plain, html = None, None

    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            charset = part.get_content_charset() or "utf-8"
            payload = part.get_payload(decode=True)

            if payload is None:
                continue  # 컨테이너 파트(예: multipart/alternative 자체)는 payload가 None

            if ctype == "text/plain" and plain is None:
                plain = payload.decode(charset, errors="ignore")
            elif ctype == "text/html" and html is None:
                html = payload.decode(charset, errors="ignore")
    else:
        charset = msg.get_content_charset() or "utf-8"
        payload = msg.get_payload(decode=True)
        if payload is not None:
            content = payload.decode(charset, errors="ignore")
            if msg.get_content_type() == "text/html":
                html = content
            else:
                plain = content

    if plain:
        return plain
    if html:
        from bs4 import BeautifulSoup
        return BeautifulSoup(html, "html.parser").get_text(separator=" ", strip=True)

    return ""




def fetch_new_emails(processed_uids: set[str]) -> list[MailEntity]:
    conn = None
    new_entities: list[MailEntity] = []

    try:
        token = get_access_token()
        auth_string = build_xoauth2_string(USER_EMAIL, token)

        conn = poplib.POP3_SSL(POP3_SERVER, POP3_PORT)
        conn._shortcmd("AUTH XOAUTH2")
        conn._shortcmd(base64.b64encode(auth_string.encode()).decode())

        resp, listings, octets = conn.uidl()
        uid_map = {}
        for line in listings:
            num, uid = line.decode().split(" ", 1)
            uid_map[int(num)] = uid

        p = parser.Parser()

        for num, uid in uid_map.items():
            if uid in processed_uids:
                continue

            try:

                raw_lines = conn.retr(num)[1]
                raw_email = b"\r\n".join(raw_lines).decode("utf-8", errors="ignore")
                msg = p.parsestr(raw_email)
                print(get_body(msg))

                sender = extract_email_address( decode_mime_header(msg["From"]))

                new_entities.append(
                    MailEntity(
                        uid=uid,
                        subject=decode_mime_header(msg["Subject"]),
                        sender= sender,
                        body=get_body(msg),
                        received_at=parsedate_to_datetime(msg["Date"]),
                    )
                )
            except Exception:
                logger.exception("메일 파싱 실패 (uid=%s, num=%s)", uid, num)
                continue

    except poplib.error_proto as e:
        logger.error("POP3 프로토콜 오류: %s", e)
    except Exception:
        logger.exception("메일 수신 중 알 수 없는 오류 발생")
    finally:
        if conn is not None:
            try:
                conn.quit()
            except Exception:
                logger.exception("POP3 연결 종료 실패")

    return new_entities


