"""메일 처리 루프(email_consumer_loop) 한 주기를 대역으로 돌려 상태 전이를 확인한다."""
from types import SimpleNamespace

import pytest

from entity.type import MailEntity, TaskEntity, TaskStatus
from mail import email_service
from mail.email_send import SendOutcome, SendResult

SENT = SendResult(SendOutcome.SENT, "DATA 250")


def join_notify_threads(timeout: float = 5) -> None:
    """검토 알림은 별도 스레드(mail-notify)로 나간다. 테스트에서 결과를 보려면 끝날 때까지 기다린다."""
    import threading

    for thread in threading.enumerate():
        if thread.name == "mail-notify":
            thread.join(timeout)


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

    def latest_retry_id(self, task_id):
        return None

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
        join_notify_threads()

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


class TwoTaskRepo(FakeTaskRepo):
    """대기 작업 2건. 초안 저장 시각을 남긴다."""

    def __init__(self):
        super().__init__(TaskEntity(task_id="t1", mail_uid="m1"))
        self.tasks = [TaskEntity(task_id="t1", mail_uid="m1"), TaskEntity(task_id="t2", mail_uid="m1")]
        self.events: list[str] = []

    def get_pending_tasks(self):
        return list(self.tasks)

    def save_draft(self, task_id, answer, sources=None, validation=None, applied_review_id=None):
        self.events.append(f"save:{task_id}")
        self.statuses.append(TaskStatus.DRAFTED)


def test_slow_notification_does_not_delay_next_draft(consumer, monkeypatch):
    """알림 발송이 멈춰도(대역 5초) 다음 작업의 초안 저장이 먼저 일어난다. 알림이 실패해도 두 작업 모두 drafted."""
    import threading
    import time

    from mail import email_service

    release = threading.Event()
    calls: list[dict] = []
    repo = TwoTaskRepo()

    def hanging_send(*args, **kwargs):
        calls.append(kwargs)
        release.wait(5)
        repo.events.append("notify-done")
        return SendResult(SendOutcome.FAILED, "TLS 핸드셰이크 시간 초과")

    monkeypatch.setattr(email_service, "send_email", hanging_send)
    started = time.monotonic()
    email_service.email_consumer_loop(OneShotStop(), SimpleNamespace(get_mail_by_id=lambda uid: MailEntity(
        uid="m1", subject="제목", sender="c@example.com", body="질문")), repo)
    loop_seconds = time.monotonic() - started

    assert repo.events == ["save:t1", "save:t2"]  # 두 초안 모두 알림이 끝나기 전에 저장됐다
    assert loop_seconds < 2  # 알림을 기다리지 않는다
    release.set()
    join_notify_threads()
    assert repo.events == ["save:t1", "save:t2", "notify-done", "notify-done"]
    assert all(kwargs["timeout"] == email_service.config.NOTIFY_SMTP_TIMEOUT_SECONDS for kwargs in calls)
    assert repo.statuses.count(TaskStatus.DRAFTED) == 2 and TaskStatus.FAILED not in repo.statuses


def test_notify_thread_is_daemon_named_mail_notify(monkeypatch):
    from mail import email_service

    monkeypatch.setattr(email_service, "send_email", lambda *a, **k: SENT)
    thread = email_service.notify_reviewer_async(
        "r@example.com", MailEntity(uid="m1", subject="s", sender="c@example.com", body="q"), "답", "t1")
    thread.join(5)

    assert thread.daemon is True and thread.name == "mail-notify"
