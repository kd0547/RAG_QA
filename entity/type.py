from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime

class TaskStatus(Enum):
    PENDING = "pending"        # 메일 수신 완료, AI 답변 생성 대기 중
    DRAFTED = "drafted"        # AI가 답변 초안 생성 완료, 담당자 검토 대기
    IN_REVIEW = "in_review"    # 담당자가 검토 중
    REJECTED = "rejected"        # 반려 → 재추론 필요
    APPROVED = "approved"
    SENT = "sent"              # 담당자 승인 후 최종 전송 완료
    FAILED = "failed"          # 처리 중 오류 발생 (재시도 대상)

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
class MailEntity:
    uid: str
    subject: str
    sender: str
    body: str = ""                          # 기본값
    received_at: datetime = field(default_factory=datetime.now)
    attachments: list[str] = field(default_factory=list)  # 가변 기본값은 반드시 이렇게

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
