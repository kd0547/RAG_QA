"""메일 처리 루프(email_consumer_loop) 한 주기를 대역으로 돌려 상태 전이를 확인한다."""
from types import SimpleNamespace

import pytest

from entity.type import MailEntity, TaskEntity, TaskStatus
from mail import email_service
from mail.email_send import SendOutcome, SendResult

SENT = SendResult(SendOutcome.SENT, "DATA 250")


class OneShotStop:
    """루프를 한 주기만 돌게 하는 stop_event 대역."""

    def __init__(self):
        self.checked = 0

    def is_set(self):
        self.checked += 1
        return self.checked > 1

    def wait(self, timeout):
        return None


class FakeTaskRepo:
    def __init__(self, task: TaskEntity, fail_save: bool = False):
        self.task = task
        self.fail_save = fail_save
        self.calls: list[tuple] = []
        self.statuses: list[TaskStatus] = []

    def get_pending_tasks(self):
        return [self.task]

    def update_status(self, task_id, status):
        self.calls.append(("update_status", status))
        self.statuses.append(status)

    def unapplied_reject_reasons(self, task_id):
        return []

    def assign_task(self, task_id, assignee):
        self.calls.append(("assign_task", assignee))

    def save_draft(self, task_id, answer, sources=None, validation=None, applied_review_id=None):
        self.calls.append(("save_draft", answer))
        if self.fail_save:
            raise RuntimeError("DB 잠김")
        self.statuses.append(TaskStatus.DRAFTED)


@pytest.fixture
def consumer(monkeypatch):
    mail = MailEntity(uid="m1", subject="제목", sender="customer@example.com", body="N5800 무게?")
    email_repo = SimpleNamespace(get_mail_by_id=lambda uid: mail)
    monkeypatch.setattr(email_service, "run_agent_temp_attachments",
                        lambda *a, **k: {"answer": "1.5kg입니다.", "sources": []})

    def run(task_repo, send_email):
        monkeypatch.setattr(email_service, "send_email", send_email)
        email_service.email_consumer_loop(OneShotStop(), email_repo, task_repo)

    return run


def test_draft_is_saved_before_reviewer_notification(consumer):
    run = consumer
    repo = FakeTaskRepo(TaskEntity(task_id="t1", mail_uid="m1"))
    order: list[str] = []

    def send_email(*args, **kwargs):
        order.append("send_email")
        assert ("save_draft", "1.5kg입니다.") in repo.calls, "알림 전에 초안이 저장돼 있어야 한다"
        return SENT

    run(repo, send_email)

    assert order == ["send_email"]
    # 생성 시작 시 processing으로 표시하고, 저장 후 drafted
    assert repo.statuses == [TaskStatus.PROCESSING, TaskStatus.DRAFTED]


def test_notification_not_sent_when_draft_save_fails(consumer):
    run = consumer
    repo = FakeTaskRepo(TaskEntity(task_id="t1", mail_uid="m1"), fail_save=True)
    sent = []

    run(repo, lambda *a, **k: sent.append(a) or SENT)

    assert sent == []
    assert repo.statuses[-1] == TaskStatus.FAILED


def test_notification_failure_keeps_drafted(consumer):
    run = consumer
    repo = FakeTaskRepo(TaskEntity(task_id="t1", mail_uid="m1"))

    def send_email(*args, **kwargs):
        raise ConnectionError("SMTP 연결 실패")

    run(repo, send_email)

    assert TaskStatus.FAILED not in repo.statuses
    assert repo.statuses[-1] == TaskStatus.DRAFTED


def test_notification_rejected_by_server_keeps_drafted(consumer):
    """알림이 예외 없이 send_failed로 돌아와도 초안 상태는 그대로다."""
    run = consumer
    repo = FakeTaskRepo(TaskEntity(task_id="t1", mail_uid="m1"))

    run(repo, lambda *a, **k: SendResult(SendOutcome.FAILED, "RCPT 550"))

    assert repo.statuses == [TaskStatus.PROCESSING, TaskStatus.DRAFTED]
