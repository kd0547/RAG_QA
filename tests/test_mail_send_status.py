"""A4: 승인 API의 발송 선점·결과 분기, 발송 확인(mark-sent), 생성 중 작업 복구, task_reviews 마이그레이션."""
import sqlite3
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from test_mail_list import _sent_ok, mail_client, mail_data  # noqa: F401  (pytest 픽스처 재사용)


def _set_status(task_id: str, status):
    from app.routers import mails

    mails.task_repo.update_status(task_id, status)


def test_approve_concurrent_requests_send_once(mail_data, monkeypatch):  # noqa: F811
    """같은 메일을 두 요청이 동시에 승인하면 발송은 한 번, 다른 쪽은 409."""
    from app.routers import mails

    ids = mail_data
    sent = []

    def slow_send(**kwargs):
        time.sleep(0.5)
        return _sent_ok(sent, kwargs)

    monkeypatch.setattr(mails, "send_email", slow_send)
    results = []
    barrier = threading.Barrier(2)

    def approve():
        barrier.wait()
        try:
            results.append(mails.mail_approve(ids["drafted"], SimpleNamespace(client=None), None)["status"])
        except HTTPException as exc:
            results.append(exc.status_code)

    threads = [threading.Thread(target=approve) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(sent) == 1
    assert sorted(results, key=str) == [409, "sent"]
    sends = mails.task_repo.get_sends(ids["drafted"])
    assert [(s["outcome"], s["recipient"], s["body"]) for s in sends] == [("sent", "sender@example.com", "초안 답변")]


@pytest.mark.parametrize("outcome", ["send_failed", "send_unknown"])
def test_approve_records_failed_and_unknown(mail_client, monkeypatch, outcome):  # noqa: F811
    client, ids = mail_client
    from app.routers import mails
    from mail.email_send import SendOutcome, SendResult

    monkeypatch.setattr(mails, "send_email", lambda **kwargs: SendResult(SendOutcome(outcome), "SMTPServerDisconnected"))

    response = client.post(f"/mails/{ids['drafted']}/approve")

    assert response.status_code == 502
    assert outcome in response.json()["detail"]
    assert client.get(f"/mails/{ids['drafted']}").json()["status"] == outcome
    sends = mails.task_repo.get_sends(ids["drafted"])
    assert [(s["outcome"], s["detail"]) for s in sends] == [(outcome, "SMTPServerDisconnected")]


def test_approve_unexpected_exception_is_unknown_not_resent(mail_client, monkeypatch):  # noqa: F811
    """send_email이 예상 밖 예외를 던지면 나갔는지 모르므로 send_unknown. 다시 보내지 않는다."""
    client, ids = mail_client
    from app.routers import mails

    calls = []

    def boom(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("예상 밖 오류")

    monkeypatch.setattr(mails, "send_email", boom)

    assert client.post(f"/mails/{ids['drafted']}/approve").status_code == 502
    assert len(calls) == 1
    assert client.get(f"/mails/{ids['drafted']}").json()["status"] == "send_unknown"


def test_approve_quit_warning_keeps_sent(mail_client, monkeypatch, caplog):  # noqa: F811
    client, ids = mail_client
    from app.routers import mails
    from mail.email_send import SendOutcome, SendResult

    monkeypatch.setattr(mails, "send_email", lambda **kwargs: SendResult(
        SendOutcome.SENT, "DATA 250", cleanup_warning="quit 실패: SMTPServerDisconnected"))

    with caplog.at_level("WARNING", logger="app.routers.mails"):
        response = client.post(f"/mails/{ids['drafted']}/approve")

    assert response.status_code == 200
    assert client.get(f"/mails/{ids['drafted']}").json()["status"] == "sent"
    assert "연결 정리 실패" in caplog.text
    assert mails.task_repo.get_sends(ids["drafted"])[0]["cleanup_warning"] == "quit 실패: SMTPServerDisconnected"


@pytest.mark.parametrize("status_value", ["send_failed", "send_unknown"])
def test_reapprove_after_failure_sends_again(mail_client, monkeypatch, status_value):  # noqa: F811
    """실패·불명 건은 담당자가 다시 승인할 때만 다시 보낸다."""
    client, ids = mail_client
    from app.routers import mails
    from entity.type import TaskStatus

    _set_status(ids["drafted"], TaskStatus(status_value))
    sent = []
    monkeypatch.setattr(mails, "send_email", lambda **kwargs: _sent_ok(sent, kwargs))

    response = client.post(f"/mails/{ids['drafted']}/approve")

    assert response.status_code == 200
    assert len(sent) == 1


@pytest.mark.parametrize("status_value", ["sending", "sent", "pending", "processing", "failed", "in_review"])
def test_approve_refuses_other_statuses(mail_client, monkeypatch, status_value):  # noqa: F811
    client, ids = mail_client
    from app.routers import mails
    from entity.type import TaskStatus

    _set_status(ids["drafted"], TaskStatus(status_value))
    sent = []
    monkeypatch.setattr(mails, "send_email", lambda **kwargs: _sent_ok(sent, kwargs))

    assert client.post(f"/mails/{ids['drafted']}/approve").status_code == 409
    assert sent == []


def test_mark_sent_only_from_send_unknown(mail_client):  # noqa: F811
    client, ids = mail_client
    from app.routers import mails
    from entity.type import TaskStatus

    for status in TaskStatus:
        if status == TaskStatus.SEND_UNKNOWN:
            continue
        _set_status(ids["drafted"], status)
        response = client.post(f"/mails/{ids['drafted']}/mark-sent", json={"reason": "보낸편지함 확인"})
        assert response.status_code == 409, status

    _set_status(ids["drafted"], TaskStatus.SEND_UNKNOWN)
    assert client.post(f"/mails/{ids['drafted']}/mark-sent", json={"reason": "  "}).status_code == 400
    response = client.post(f"/mails/{ids['drafted']}/mark-sent", json={"reason": "보낸편지함 확인"})

    assert response.status_code == 200
    assert response.json() == {"task_id": ids["drafted"], "status": "sent"}
    with mails.task_repo.db.get_conn() as conn:
        reviews = conn.execute(
            "SELECT action, reason, requeue FROM task_reviews WHERE task_id = ?", (ids["drafted"],),
        ).fetchall()
    assert [tuple(r) for r in reviews] == [("mark_sent", "보낸편지함 확인", 0)]
    assert client.post("/mails/not-found/mark-sent", json={"reason": "x"}).status_code == 404


def test_reset_processing_restores_pending_but_not_sending(mail_data):  # noqa: F811
    from app.routers import mails
    from entity.type import TaskStatus

    ids = mail_data
    repo = mails.task_repo
    _set_status(ids["drafted"], TaskStatus.PROCESSING)
    _set_status(ids["in_review"], TaskStatus.SENDING)

    assert repo.reset_processing() == 1

    assert repo.get_task(ids["drafted"]).status == TaskStatus.PENDING
    assert repo.get_task(ids["in_review"]).status == TaskStatus.SENDING
    with repo.db.get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM tasks WHERE status = 'processing'").fetchone()[0] == 0


OLD_SCHEMA = """
CREATE TABLE tasks (task_id TEXT PRIMARY KEY, mail_uid TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
    assignee TEXT, retry_count INTEGER NOT NULL DEFAULT 0, draft_answer TEXT DEFAULT '',
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE task_reviews (review_id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('reject')), reason TEXT, requeue INTEGER NOT NULL DEFAULT 1,
    reviewed_at TEXT NOT NULL, FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE);
INSERT INTO tasks VALUES ('t1', 'm1', 'drafted', NULL, 0, '', 'now', 'now');
INSERT INTO task_reviews (review_id, task_id, action, reason, requeue, reviewed_at)
    VALUES (7, 't1', 'reject', '문체', 1, 'now');
"""


def test_migration_allows_mark_sent_on_old_task_reviews(tmp_path):
    """예전 CHECK (action IN ('reject')) 테이블도 기존 이력을 지키며 mark_sent를 받게 된다."""
    from repository.repo_connect import Database

    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(OLD_SCHEMA)
    conn.close()

    db = Database(str(path))

    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO task_reviews (task_id, action, reason, requeue, reviewed_at) "
            "VALUES ('t1', 'mark_sent', '확인', 0, 'now')"
        )
        rows = conn.execute("SELECT review_id, action, reason FROM task_reviews ORDER BY review_id").fetchall()
        index = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND name = 'idx_task_reviews_task_id'"
        ).fetchone()
    assert [tuple(r) for r in rows] == [(7, "reject", "문체"), (8, "mark_sent", "확인")]
    assert index is not None
    Database(str(path))  # 두 번째 적용은 아무것도 하지 않는다
