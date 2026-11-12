from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


class TaskStatus(Enum):
    """작업 상태.

    pending → processing → drafted → sending → sent
                         ↘ failed              ↘ send_failed   (담당자 재승인 가능)
                                               ↘ send_unknown  (담당자 확인 후 sent 처리 또는 재승인)
    drafted → rejected → pending  (requeue 반려)
    """
    PENDING = "pending"        # 메일 수신 완료, AI 답변 생성 대기 중
    PROCESSING = "processing"  # AI가 답변 생성 중. 서버가 재시작되면 pending으로 되돌린다
    DRAFTED = "drafted"        # AI가 답변 초안 생성 완료, 담당자 검토 대기
    IN_REVIEW = "in_review"    # 담당자가 검토 중
    REJECTED = "rejected"        # 반려 → 재추론 필요
    APPROVED = "approved"
    SENDING = "sending"        # 승인 후 SMTP 발송 중 (재시작해도 되돌리지 않는다: 이미 나갔을 수 있다)
    SENT = "sent"              # 담당자 승인 후 최종 전송 완료
    SEND_FAILED = "send_failed"    # 서버가 수락하지 않음이 확실한 발송 실패 → 재승인 가능
    SEND_UNKNOWN = "send_unknown"  # 본문 전송 중 끊겨 수락 여부를 모름 → 담당자가 확인
    FAILED = "failed"          # 답변 생성 실패 (발송 실패에는 쓰지 않는다)

class DocumentType(Enum):
    PDF = "pdf"
    IMAGE = "image"
    DOCX = "docx"
    PPTX = "pptx"
    XLSX = "xlsx"
    HWP = "hwp"
    HWPX = "hwpx"



def parse_status_filter(status:str)-> list[TaskStatus] | None:
    if not status:
        return None

    tokens = [s.strip() for s in status.split(",")]
    if not tokens:
        return None

    result = []
    invalid = []
    for token in tokens:
        try:
            result.append(TaskStatus(token))
        except ValueError:
            invalid.append(token)
    if invalid:
        return None

    return result

@dataclass
class Attachment:
    type: DocumentType
    filename: str
    content_type: str
    image:Optional[str]
    path: Optional[str]

@dataclass
class MailEntity:
    uid: str
    subject: str
    sender: str
    body: str = ""                          # 기본값
    received_at: datetime = field(default_factory=datetime.now)
    attachments: list[Attachment] = field(default_factory=list)


@dataclass
class TaskEntity:
    task_id: str
    mail_uid: str                 # MailEntity 참조 (1:1 또는 1:N)
    status: TaskStatus = field(default_factory=lambda: TaskStatus.PENDING)
    assignee: str | None = None
    retry_count: int = 0
    draft_answer: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
