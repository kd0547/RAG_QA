"""GET /mails: 실제 SQLite 조회와 상태 필터를 확인한다."""

from datetime import datetime
from pathlib import Path
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def mail_data(tmp_path, monkeypatch):
    # 라우터 임포트 시 생성되는 DB와 SMTP 설정을 테스트 경로로 격리한다.
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]))
    (tmp_path / "storage").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MAIL_ID", "sender@example.com")
    monkeypatch.setenv("MAIL_PW", "test-only")

    # repository의 전역 DB도 운영 데이터 대신 임시 DB를 사용하게 한다.
    production_db = Path(__file__).resolve().parents[1] / "storage" / "mail.db"
    original_connect = sqlite3.connect

    def isolated_connect(database, *args, **kwargs):
        if Path(database).resolve() == production_db:
            database = str(tmp_path / "mail-global.db")
        return original_connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", isolated_connect)

    from app.routers import mail_links, mails
    from entity.type import TaskStatus
    from repository.repo_connect import Database
    from repository.task_repository import TaskRepository

    db = Database(str(tmp_path / "mail-test.db"))
    task_repo = TaskRepository(db)
    monkeypatch.setattr(mails, "task_repo", task_repo)
    monkeypatch.setattr(mail_links, "task_repo", task_repo)

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

    return ids


@pytest.fixture
def mail_client(mail_data):
    from app.routers import mail_links, mails

    app = FastAPI()
    app.include_router(mails.router)
    app.include_router(mail_links.router)
    with TestClient(app) as client:
        yield client, mail_data


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
        "model", "retrieval", "sources", "attachments",
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
    assert body["attachments"] == []
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
    from app.routers import mails
    from mail.templates import render_answer_email

    sent = []
    monkeypatch.setattr(mails, "send_email", lambda **kwargs: sent.append(kwargs))

    response = client.post(f"/mails/{ids['drafted']}/approve")

    assert response.status_code == 200
    assert response.json()["task_id"] == ids["drafted"]
    assert response.json()["status"] == "sent"
    # 저장된 초안(마크다운)을 HTML 메일로 렌더링해서 보낸다
    assert sent == [{
        "to_addr": "sender@example.com",
        "subject": "[응답] drafted",
        "body": render_answer_email("초안 답변"),
        "html": True,
        "attachments": [],
    }]
    assert client.get(f"/mails/{ids['drafted']}").json()["status"] == "sent"


def test_approve_with_edited_body_sends_and_saves_it(mail_client, monkeypatch):
    client, ids = mail_client
    from app.routers import mails
    from mail.templates import render_answer_email

    sent = []
    monkeypatch.setattr(mails, "send_email", lambda **kwargs: sent.append(kwargs))

    response = client.post(
        f"/mails/{ids['drafted']}/approve",
        json={"body": "수정한 **답변**", "edited": True},
    )

    assert response.status_code == 200
    # 검토자가 고친 본문이 저장된 초안 대신 전송되고, task 의 초안도 수정본으로 바뀐다
    assert [m["body"] for m in sent] == [render_answer_email("수정한 **답변**")]
    assert client.get(f"/mails/{ids['drafted']}").json()["draft"] == "수정한 **답변**"


def test_send_link_page_does_not_send_by_itself(mail_client, monkeypatch):
    """메일의 '답변 전송' 링크(GET)는 페이지만 돌려주고, 전송은 페이지 스크립트의 POST 로만 한다."""
    client, ids = mail_client
    from app.routers import mails

    sent = []
    monkeypatch.setattr(mails, "send_email", lambda **kwargs: sent.append(kwargs))

    response = client.get(f"/mails/{ids['drafted']}/send")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert f"/mails/{ids['drafted']}/approve" in response.text
    assert sent == []
    assert client.get(f"/mails/{ids['drafted']}").json()["status"] == "drafted"


def test_send_link_page_for_already_sent_mail(mail_client):
    client, ids = mail_client

    response = client.get(f"/mails/{ids['sent']}/send")

    assert response.status_code == 200
    assert "이미 처리된 메일입니다" in response.text


def test_send_link_page_for_unknown_task(mail_client):
    client, _ = mail_client

    assert client.get("/mails/not-found/send").status_code == 404


def test_review_email_send_button_points_to_send_page():
    from entity.type import MailEntity
    from mail.templates import render_mail_review_email

    mail = MailEntity(uid="u1", subject="제목", sender="a@example.com", body="질문", received_at="", attachments=[])
    html = render_mail_review_email(mail, "초안", task_id="task 1", base_url="http://host:9092/")

    assert 'href="http://host:9092/mails/task%201/send"' in html
    assert 'href="http://host:9092/mail?task_id=task%201"' in html
    assert "action=send" not in html


def test_attachments_sorted_by_average_similarity(mail_data, tmp_path):
    ids = mail_data
    from app.routers import mails

    repo = mails.task_repo
    scores_by_file = {
        "low": [0.95, 0.15],
        "high": [0.8, None],
        "zero": [0.0],
        "negative": [-0.2],
        "unknown": [None],
    }
    sources = []
    with repo.db.transaction() as conn:
        for file_id, scores in scores_by_file.items():
            path = tmp_path / f"{file_id}.pdf"
            path.write_bytes(b"test attachment")
            conn.execute(
                "INSERT INTO file (file_id, original_name, stored_path) VALUES (?, ?, ?)",
                (file_id, path.name, str(path)),
            )
            sources.extend(
                {"id": f"{file_id}-{i}", "file_id": file_id,
                 "source": path.name, "text": f"chunk {i}", "score": score}
                for i, score in enumerate(scores)
            )
    # 검색과 리랭킹에 같은 청크가 나와도 평균에 두 번 포함하지 않는다.
    sources.append(dict(sources[0]))
    repo.save_draft(ids["drafted"], "초안", sources)
    # 다른 메일의 점수가 이 메일의 평균에 포함되면 안 된다.
    repo.save_draft(ids["sent"], "다른 초안", [
        {"id": "other-task", "file_id": "low", "source": "low.pdf", "text": "other", "score": 1.0},
    ])
    (tmp_path / "unknown.pdf").unlink()

    attachments = mails.view_mail_detail(ids["drafted"])["attachments"]
    assert [a["file_id"] for a in attachments] == ["high", "low", "zero", "negative", "unknown"]
    assert [a["average_score"] for a in attachments[:-1]] == pytest.approx([0.8, 0.55, 0.0, -0.2])
    assert attachments[-1]["average_score"] is None
    assert attachments[-1]["available"] is False
    assert all("path" not in a and "stored_path" not in a for a in attachments)


def test_attachment_similarity_groups_same_path_and_keeps_tie_order(mail_data, tmp_path):
    ids = mail_data
    from app.routers import mails

    repo = mails.task_repo
    shared_path = tmp_path / "shared.pdf"
    shared_path.write_bytes(b"shared")
    with repo.db.transaction() as conn:
        for file_id in ("first", "alias", "tied"):
            path = shared_path if file_id != "tied" else tmp_path / "tied.pdf"
            conn.execute(
                "INSERT INTO file (file_id, original_name, stored_path) VALUES (?, ?, ?)",
                (file_id, path.name, str(path)),
            )
    repo.save_draft(ids["drafted"], "초안", [
        {"id": "one", "file_id": "first", "source": "shared.pdf", "text": "one", "score": 0.25},
        {"id": "two", "file_id": "alias", "source": "shared.pdf", "text": "two", "score": 0.75},
        {"id": "three", "file_id": "tied", "source": "tied.pdf", "text": "three", "score": 0.5},
    ])

    attachments = mails.view_mail_detail(ids["drafted"])["attachments"]

    assert [a["file_id"] for a in attachments] == ["first", "tied"]
    assert [a["average_score"] for a in attachments] == pytest.approx([0.5, 0.5])
