"""GET /mails: 실제 SQLite 조회와 상태 필터를 확인한다."""

from datetime import datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def mail_client(tmp_path, monkeypatch):
    # 라우터 임포트 시 생성되는 DB와 SMTP 설정을 테스트 경로로 격리한다.
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]))
    (tmp_path / "storage").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MAIL_ID", "sender@example.com")
    monkeypatch.setenv("MAIL_PW", "test-only")

    from app.controller import mail_controller
    from entity.type import TaskStatus
    from repository.repo_connect import Database
    from repository.task_repository import TaskRepository

    db = Database(str(tmp_path / "mail-test.db"))
    task_repo = TaskRepository(db)
    monkeypatch.setattr(mail_controller, "task_repo", task_repo)

    now = datetime.now().isoformat()
    ids = {}
    with db.transaction() as conn:
        for status in (TaskStatus.DRAFTED, TaskStatus.IN_REVIEW, TaskStatus.SENT):
            uid = f"mail-{status.value}"
            conn.execute(
                """INSERT INTO mails
                   (uid, subject, sender, body, received_at, attachments, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (uid, status.value, "sender@example.com", "질문", now, "", now, now),
            )
            ids[status.value] = task_repo.create_task(uid, conn).task_id

    for status in (TaskStatus.DRAFTED, TaskStatus.IN_REVIEW, TaskStatus.SENT):
        task_repo.update_status(ids[status.value], status)
    task_repo.save_draft(ids["drafted"], "초안 답변")

    app = FastAPI()
    app.include_router(mail_controller.router)
    with TestClient(app) as client:
        yield client, ids


def test_mails_default_statuses(mail_client):
    client, ids = mail_client

    response = client.get("/mails")

    assert response.status_code == 200
    body = response.json()
    assert {item["task_id"] for item in body["items"]} == {
        ids["drafted"], ids["in_review"],
    }
    assert body["total"] == 2
    assert body["limit"] == 50
    assert body["offset"] == 0


def test_mails_explicit_status_filter(mail_client):
    client, ids = mail_client

    response = client.get("/mails", params={"status": "sent"})

    assert response.status_code == 200
    assert [item["task_id"] for item in response.json()["items"]] == [ids["sent"]]


def test_mails_rejects_unknown_status(mail_client):
    client, _ = mail_client

    response = client.get("/mails", params={"status": "unknown"})

    assert response.status_code == 400
    assert "status" in response.json()["detail"]


def test_mail_detail_returns_mail_and_task_fields(mail_client):
    client, ids = mail_client

    response = client.get(f"/mails/{ids['drafted']}")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "task_id", "subject", "sender", "received_at", "status", "assignee",
        "body", "draft", "created_at", "updated_at", "recipient",
        "model", "retrieval", "sources",
    }
    assert body["task_id"] == ids["drafted"]
    assert body["subject"] == "drafted"
    assert body["sender"] == "sender@example.com"
    assert body["status"] == "drafted"
    assert body["assignee"] is None
    assert body["body"] == "질문"
    assert body["draft"] == "초안 답변"
    assert body["recipient"] == "sender@example.com"
    assert body["model"] is None
    assert body["retrieval"] is None
    assert body["sources"] == []
    for field in ("received_at", "created_at", "updated_at"):
        datetime.fromisoformat(body[field])


def test_mail_detail_returns_404_for_unknown_task_id(mail_client):
    client, _ = mail_client

    response = client.get("/mails/not-found")

    assert response.status_code == 404


def test_mail_uid_is_not_a_detail_identifier(mail_client):
    client, _ = mail_client

    assert client.get("/mails/mail-drafted").status_code == 404


def test_approve_uses_task_id(mail_client, monkeypatch):
    client, ids = mail_client
    from app.controller import mail_controller

    sent = []
    monkeypatch.setattr(mail_controller, "send_email", lambda **kwargs: sent.append(kwargs))

    response = client.post(f"/mails/{ids['drafted']}/approve")

    assert response.status_code == 200
    assert response.json()["task_id"] == ids["drafted"]
    assert sent == [{
        "to_addr": "sender@example.com",
        "subject": "[응답] drafted",
        "body": "초안 답변",
    }]
