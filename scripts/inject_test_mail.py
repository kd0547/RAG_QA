"""메일 수신(POP3) 없이 테스트 메일을 대기 작업으로 넣는다.

Outlook 장애 등으로 메일을 받을 수 없을 때, 메일 처리 흐름(초안 생성 → 검토 화면 → 반려 → 같은 대화로 재작성)을
확인하기 위한 도구다. 수신부가 하는 일(mails 저장 + tasks 생성, mail/email_service.intake_mail)을 그대로 한다.
서버가 떠 있으면 메일 처리 루프가 10초 안에 이 작업을 집어 초안을 만든다.

사용 예 (프로젝트 루트에서):
    # 새 질문
    .venv/Scripts/python.exe scripts/inject_test_mail.py --subject "KC 인증서" --body "N5800 KC 인증번호 알려줘"

    # 첨부와 함께 (문서는 temp/manual/ 아래로 복사해 둔다)
    .venv/Scripts/python.exe scripts/inject_test_mail.py --subject "입찰 사양" --body "첨부 사양에 맞는 모델 찾아줘" --attach "tests/data/노트북 입찰 사양.jpg"

    # 예전에 받은 메일을 그대로 다시 처리 (task_id 또는 메일 uid, 첨부도 같이 복제)
    .venv/Scripts/python.exe scripts/inject_test_mail.py --clone 3f2a...

주의
- 발신자 기본값은 검토 담당자 주소(config.REVIEWER_EMAIL)다. 검토 화면에서 승인하면 답변 메일이 그 발신자에게
  실제로 나간다. 고객 주소를 --sender로 넣지 않는다.
- 검토 알림 메일은 메일 서버가 죽어 있으면 실패하지만 초안은 drafted로 남는다 (대시보드에서 확인).
- 운영 DB(storage/mail.db)에 행을 추가한다. 넣은 메일의 uid는 manual- 로 시작한다.
"""
from __future__ import annotations

import argparse
import base64
import mimetypes
import shutil
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config  # noqa: E402
import repository  # noqa: E402
from entity.type import Attachment, DocumentType, MailEntity  # noqa: E402

UID_PREFIX = "manual-"
SUBJECT_PREFIX = "[주입] "
ATTACH_DIR = ROOT / "temp" / "manual"
IMAGE_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
DOCUMENT_EXTS = {f".{t.value}" for t in DocumentType if t is not DocumentType.IMAGE}


def new_uid() -> str:
    return f"{UID_PREFIX}{datetime.now():%Y%m%d-%H%M%S}-{uuid4().hex[:6]}"


def build_attachment(path: Path, uid: str, attach_dir: Path = ATTACH_DIR) -> Attachment:
    """파일 하나를 메일 첨부로 만든다. 이미지는 data URL, 문서는 attach_dir/<uid>/ 아래로 복사한 경로."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"첨부 파일이 없습니다: {path}")
    ext = path.suffix.lower()
    if ext in IMAGE_MIME:
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return Attachment(
            type="image", filename=path.name, content_type=IMAGE_MIME[ext],
            image=f"data:{IMAGE_MIME[ext]};base64,{encoded}", path=None,
        )
    if ext not in DOCUMENT_EXTS:
        supported = ", ".join(sorted(DOCUMENT_EXTS | set(IMAGE_MIME)))
        raise ValueError(f"지원하지 않는 첨부 형식입니다: {path.name} (지원: {supported})")
    target_dir = attach_dir / uid
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / path.name
    shutil.copyfile(path, target)
    return Attachment(
        type=ext.lstrip("."), filename=path.name,
        content_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        image=None, path=str(target),
    )


def find_mail(key: str) -> MailEntity | None:
    """task_id 또는 메일 uid로 예전 메일을 찾는다."""
    task = repository.task_repo.get_task(key)
    mail_uid = task.mail_uid if task else key
    return repository.email_repo.get_mail_by_id(mail_uid)


def inject(
    subject: str,
    body: str,
    sender: str | None = None,
    attachments: list[Attachment] | None = None,
    uid: str | None = None,
) -> dict:
    """메일과 대기 작업을 한 트랜잭션으로 넣는다 (intake_mail과 같은 동작). 넣은 uid·task_id를 돌려준다."""
    if not body or not body.strip():
        raise ValueError("본문이 비어 있으면 메일 처리 루프가 failed로 처리합니다. 본문을 넣어 주세요.")
    uid = uid or new_uid()
    mail = MailEntity(
        uid=uid,
        subject=subject,
        sender=sender or config.REVIEWER_EMAIL,
        body=body,
        received_at=datetime.now(),
        # 수신부처럼 attachment_id 없이 넣는다 (DB가 번호를 매긴다)
        attachments=[
            Attachment(type=a.type, filename=a.filename, content_type=a.content_type, image=a.image, path=a.path)
            for a in attachments or []
        ],
    )
    with repository.db.transaction() as conn:
        repository.email_repo.save_pending(mail, conn)
        task = repository.task_repo.create_task(mail.uid, conn)
    return {"uid": uid, "task_id": task.task_id, "sender": mail.sender, "subject": mail.subject,
            "attachments": [a.filename for a in mail.attachments]}


def clone(key: str, subject: str | None = None, body: str | None = None, sender: str | None = None) -> dict:
    """예전 메일(본문·첨부)을 새 대기 작업으로 복제한다. 발신자는 원래 주소가 아니라 검토 담당자로 바꾼다."""
    original = find_mail(key)
    if original is None:
        raise LookupError(f"메일을 찾을 수 없습니다: {key} (task_id 또는 메일 uid)")
    missing = [a.filename for a in original.attachments if a.path and not Path(a.path).is_file()]
    kept = [a for a in original.attachments if not (a.path and not Path(a.path).is_file())]
    result = inject(
        subject=subject or f"{SUBJECT_PREFIX}{original.subject}",
        body=body or original.body,
        sender=sender,
        attachments=kept,
    )
    result["cloned_from"] = original.uid
    result["missing_attachments"] = missing
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="메일 수신 없이 테스트 메일을 대기 작업으로 넣는다.")
    ap.add_argument("--subject", help="메일 제목")
    ap.add_argument("--body", help="메일 본문 (질문)")
    ap.add_argument("--body-file", help="본문을 읽을 텍스트 파일 (UTF-8)")
    ap.add_argument("--attach", action="append", default=[], help="첨부 파일 경로 (여러 번 지정 가능)")
    ap.add_argument("--sender", help=f"발신자 주소. 기본값은 검토 담당자({config.REVIEWER_EMAIL}). 승인하면 이 주소로 실제 발송된다")
    ap.add_argument("--clone", metavar="TASK_ID|UID", help="예전에 받은 메일을 본문·첨부째 복제해 다시 처리한다")
    args = ap.parse_args(argv)

    body = args.body
    if args.body_file:
        body = Path(args.body_file).read_text(encoding="utf-8")

    try:
        if args.clone:
            if args.attach:
                ap.error("--clone과 --attach는 같이 쓸 수 없습니다 (복제는 원래 첨부를 쓴다)")
            result = clone(args.clone, subject=args.subject, body=body, sender=args.sender)
        else:
            if not args.subject or not body:
                ap.error("--subject와 --body(또는 --body-file)가 필요합니다 (또는 --clone)")
            uid = new_uid()
            attachments = [build_attachment(Path(p), uid) for p in args.attach]
            result = inject(f"{SUBJECT_PREFIX}{args.subject}", body, sender=args.sender, attachments=attachments, uid=uid)
    except (FileNotFoundError, ValueError, LookupError) as exc:
        print(f"실패: {exc}", file=sys.stderr)
        return 1

    print("대기 작업을 넣었습니다.")
    print(f"  task_id : {result['task_id']}")
    print(f"  uid     : {result['uid']}")
    print(f"  제목    : {result['subject']}")
    print(f"  발신자  : {result['sender']}  (승인하면 이 주소로 실제 발송됩니다)")
    if result["attachments"]:
        print(f"  첨부    : {', '.join(result['attachments'])}")
    if result.get("missing_attachments"):
        print(f"  빠진 첨부(원본 파일 없음): {', '.join(result['missing_attachments'])}")
    print(f"  검토 화면: {config.PUBLIC_BASE_URL.rstrip('/')}/mail?task_id={result['task_id']}")
    print("서버가 떠 있으면 10초 안에 초안 생성이 시작됩니다. 서버 로그의 '메일 처리 시작'을 확인하세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
