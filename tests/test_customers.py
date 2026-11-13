"""D2: 고객방 API (조회 전용). 임시 DB에 메일·작업·실행·검토·발송을 직접 넣어 확인한다."""
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException

from repository.customer_repository import CustomerRepository
from repository.repo_connect import Database

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def store(tmp_path, monkeypatch):
    from app.routers import customers

    db = Database(str(tmp_path / "customers.db"))
    repo = CustomerRepository(db)
    monkeypatch.setattr(customers, "customer_repo", repo)
    return db


def add_mail(db, uid, sender, received_at, *, subject="문의", body="본문", status="drafted", draft="", updated_at=None):
    now = datetime.now().isoformat()
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO mails (uid, subject, sender, body, received_at, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
            (uid, subject, sender, body, received_at, now, now),
        )
        conn.execute(
            "INSERT INTO tasks (task_id, mail_uid, status, draft_answer, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (f"t-{uid}", uid, status, draft, now, updated_at or now),
        )
    return f"t-{uid}"


def add_run(db, task_id, run_id, ended_at, *, status="ok", answer=None, label="메일", error=None, skills=None):
    with db.transaction() as conn:
        conn.execute(
            """INSERT INTO run (run_id, owner_type, owner_id, started_at, ended_at, status, label, answer, error,
                                tool_calls_json, skills_json)
               VALUES (?, 'task', ?, ?, ?, ?, ?, ?, ?, '[{"tool": "read_pages"}]', ?)""",
            (run_id, task_id, ended_at, ended_at, status, label, answer, error, skills and json.dumps(skills)),
        )


def add_review(db, task_id, action, at, reason=None):
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO task_reviews (task_id, action, reason, requeue, reviewed_at) VALUES (?,?,?,1,?)",
            (task_id, action, reason, at),
        )


def add_send(db, task_id, at, outcome="sent", body="보낸 본문", attachments=None):
    with db.transaction() as conn:
        conn.execute(
            """INSERT INTO task_send (task_id, body, recipient, attachments_json, attempted_at, outcome, detail)
               VALUES (?, ?, 'a@example.com', ?, ?, ?, 'DATA 250')""",
            (task_id, body, json.dumps(attachments or [], ensure_ascii=False), at, outcome),
        )


def timeline(sender, **kwargs):
    from app.routers import customers
    return customers.customer_timeline(sender, limit=kwargs.get("limit", 20), before=kwargs.get("before"))


def customers_list(**kwargs):
    from app.routers import customers
    return customers.list_customers(q=kwargs.get("q"), limit=kwargs.get("limit", 50), offset=kwargs.get("offset", 0))


# ---------------------------------------------------------------- 목록

def test_senders_listed_separately_and_case_merged(store):
    add_mail(store, "m1", "A@Example.com", "2026-11-01T10:00:00", status="sent")
    add_mail(store, "m2", " a@example.com ", "2026-11-05T10:00:00", subject="KC 인증", status="drafted")
    add_mail(store, "m3", "b@example.com", "2026-11-03T10:00:00", status="failed")

    out = customers_list()

    assert out["total"] == 2
    a, b = out["items"]
    assert a["sender"] == "a@example.com" and a["mail_count"] == 2
    assert a["first_received_at"] == "2026-11-01T10:00:00" and a["last_received_at"] == "2026-11-05T10:00:00"
    assert a["last_subject"] == "KC 인증" and a["last_task_id"] == "t-m2"
    assert a["status_counts"] == {"sent": 1, "drafted": 1} and a["needs_review"] == 1
    assert b["sender"] == "b@example.com" and b["needs_review"] == 1
    # 같은 고객의 타임라인도 대소문자와 관계없이 한 묶음
    assert timeline("A@EXAMPLE.COM")["total"] == 2


def test_list_search_and_paging(store):
    add_mail(store, "m1", "a@example.com", "2026-11-01T10:00:00", subject="N5800 무게")
    add_mail(store, "m2", "b@other.com", "2026-11-02T10:00:00", subject="KC 인증")
    add_mail(store, "m3", "c@example.com", "2026-11-03T10:00:00", subject="견적")

    assert [c["sender"] for c in customers_list(q="kc")["items"]] == ["b@other.com"]
    assert [c["sender"] for c in customers_list(q="EXAMPLE")["items"]] == ["c@example.com", "a@example.com"]
    page = customers_list(limit=1, offset=1)
    assert page["total"] == 3 and [c["sender"] for c in page["items"]] == ["b@other.com"]


# ---------------------------------------------------------------- 타임라인

def test_event_order_received_draft_reject_draft_send(store):
    task = add_mail(store, "m1", "a@example.com", "2026-11-10T10:00:00", status="sent", draft="2차")
    add_run(store, task, "r1", "2026-11-10T10:01:00", answer="1차 초안", skills=[{"name": "mail-reply-style", "digest": "abcd1234"}])
    add_review(store, task, "reject", "2026-11-10T10:02:00", reason="표를 빼고")
    add_run(store, task, "r2", "2026-11-10T10:03:00", answer="2차 초안")
    add_send(store, task, "2026-11-10T10:04:00", attachments=[{"filename": "KC.pdf", "path": "C:/docs/KC.pdf"}])

    item = timeline("a@example.com")["items"][0]
    events = item["events"]

    assert [e["type"] for e in events] == ["received", "draft", "reject", "draft", "send"]
    first, second = events[1], events[3]
    assert (first["answer"], first["current"], first["text_source"]) == ("1차 초안", False, "run")
    assert (second["answer"], second["current"]) == ("2차 초안", True)
    assert first["skills"] == [{"name": "mail-reply-style", "digest": "abcd1234"}]
    assert events[2]["reason"] == "표를 빼고" and events[2]["requeue"] is True
    assert events[4]["outcome"] == "sent" and events[4]["attachments"] == ["KC.pdf"] and events[4]["inferred"] is False
    assert item["task_id"] == task and item["status"] == "sent"


def test_same_time_tie_order_and_failed_and_retry(store):
    task = add_mail(store, "m1", "a@example.com", "2026-11-10T10:00:00", status="drafted", draft="최종")
    add_run(store, task, "r1", "2026-11-10T10:01:00", status="limit", error="모델 호출 한도" + "x" * 500)
    add_review(store, task, "retry", "2026-11-10T10:02:00")
    add_review(store, task, "mark_sent", "2026-11-10T10:05:00", reason="전화로 확인")
    add_run(store, task, "r2", "2026-11-10T10:05:00")  # answer 컬럼 없음(D1 이전) → 마지막 ok라 draft_answer
    add_review(store, task, "reject", "2026-11-10T10:05:00", reason="다시")

    events = timeline("a@example.com")["items"][0]["events"]

    assert [e["type"] for e in events] == ["received", "run_failed", "retry", "draft", "reject", "mark_sent"]
    assert events[1]["status"] == "limit" and len(events[1]["error"]) == 200
    assert (events[3]["answer"], events[3]["text_source"], events[3]["current"]) == ("최종", "task", True)


def test_old_ok_run_without_answer_has_no_text(store):
    task = add_mail(store, "m1", "a@example.com", "2026-11-10T10:00:00", draft="최신")
    add_run(store, task, "r1", "2026-11-10T10:01:00")
    add_run(store, task, "r2", "2026-11-10T10:03:00")

    drafts = [e for e in timeline("a@example.com")["items"][0]["events"] if e["type"] == "draft"]

    assert [(d["answer"], d["text_source"], d["current"]) for d in drafts] == [(None, None, False), ("최신", "task", True)]


def test_legacy_task_gets_inferred_draft_and_send(store):
    add_mail(store, "m1", "a@example.com", "2026-10-01T09:00:00", status="sent", draft="옛 초안",
             updated_at="2026-10-01T11:00:00")

    events = timeline("a@example.com")["items"][0]["events"]

    assert [e["type"] for e in events] == ["received", "draft", "send"]
    draft, send = events[1], events[2]
    assert draft["inferred"] is True and draft["at"] is None and draft["text_source"] == "task"
    assert draft["current"] is True and draft["answer"] == "옛 초안"
    assert send["inferred"] is True and send["at"] == "2026-10-01T11:00:00" and send["outcome"] == "sent"
    assert send["body"] is None


def test_two_inquiries_are_separate_groups_oldest_first(store):
    a = add_mail(store, "m1", "a@example.com", "2026-11-01T10:00:00", subject="무게")
    b = add_mail(store, "m2", "a@example.com", "2026-11-02T10:00:00", subject="인증")
    add_run(store, a, "ra", "2026-11-03T10:00:00", answer="A 초안")  # A의 실행이 B 수신보다 늦어도 A 묶음 안에
    add_run(store, b, "rb", "2026-11-02T10:01:00", answer="B 초안")

    items = timeline("a@example.com")["items"]

    assert [i["task_id"] for i in items] == [a, b]
    assert [e.get("answer") for e in items[0]["events"] if e["type"] == "draft"] == ["A 초안"]
    assert [e.get("answer") for e in items[1]["events"] if e["type"] == "draft"] == ["B 초안"]


def test_mixed_timezone_received_at_order(store):
    aware = "2026-11-03T23:00:00-10:00"
    one_hour_before = (datetime.fromisoformat(aware).astimezone() - timedelta(hours=1)).replace(tzinfo=None)
    naive = one_hour_before.isoformat()
    add_mail(store, "late", "a@example.com", aware)
    add_mail(store, "early", "a@example.com", naive)

    items = timeline("a@example.com")["items"]

    assert [i["received_at"] for i in items] == [naive, aware]  # 저장 문자열 그대로, 실제 시각 순
    assert customers_list()["items"][0]["last_received_at"] == aware


def test_before_pages_older_inquiries_without_overlap(store):
    for day in range(1, 6):
        add_mail(store, f"m{day}", "a@example.com", f"2026-11-0{day}T10:00:00")

    first = timeline("a@example.com", limit=2)
    second = timeline("a@example.com", limit=2, before=first["next_before"])
    third = timeline("a@example.com", limit=2, before=second["next_before"])

    assert [i["task_id"] for i in first["items"]] == ["t-m4", "t-m5"]
    assert first["next_before"] == "2026-11-04T10:00:00"
    assert [i["task_id"] for i in second["items"]] == ["t-m2", "t-m3"]
    assert [i["task_id"] for i in third["items"]] == ["t-m1"] and third["next_before"] is None
    assert first["total"] == 5


def test_no_disk_path_or_image_data(store):
    task = add_mail(store, "m1", "a@example.com", "2026-11-10T10:00:00", status="sent", body="본문")
    with store.transaction() as conn:
        conn.execute(
            "INSERT INTO mail_attachments (mail_uid, type, filename, content_type, image_data) VALUES (?,?,?,?,?)",
            ("m1", "image", "캡처.png", "image/png", "data:image/png;base64,AAAA"),
        )
        conn.execute(
            "INSERT INTO mail_attachments (mail_uid, type, filename, content_type, stored_path) VALUES (?,?,?,?,?)",
            ("m1", "pdf", "사양서.pdf", "application/pdf", "C:/secret/storage/mail_attachments/사양서.pdf"),
        )
    add_run(store, task, "r1", "2026-11-10T10:01:00", answer="초안")
    add_send(store, task, "2026-11-10T10:02:00", attachments=[{"filename": "KC.pdf", "path": "C:/secret/files/KC.pdf"}])

    out = timeline("a@example.com")
    text = json.dumps(out, ensure_ascii=False) + json.dumps(customers_list(), ensure_ascii=False)

    assert "secret" not in text and "data:" not in text and "tool_calls" not in text and "read_pages" not in text
    received = out["items"][0]["events"][0]
    assert received["attachments"] == [{"filename": "캡처.png", "type": "image"}, {"filename": "사양서.pdf", "type": "pdf"}]


def test_long_text_truncated(store):
    task = add_mail(store, "m1", "a@example.com", "2026-11-10T10:00:00", body="가" * 9000)
    add_run(store, task, "r1", "2026-11-10T10:01:00", answer="나" * 8000)

    events = timeline("a@example.com")["items"][0]["events"]

    assert len(events[0]["body"]) == 8000 and events[0]["truncated"] is True
    assert len(events[1]["answer"]) == 8000 and events[1]["truncated"] is False


def test_unknown_sender_404_and_bad_before_400(store):
    add_mail(store, "m1", "a@example.com", "2026-11-10T10:00:00")

    with pytest.raises(HTTPException) as missing:
        timeline("nobody@example.com")
    with pytest.raises(HTTPException) as bad:
        timeline("a@example.com", before="어제")

    assert missing.value.status_code == 404 and bad.value.status_code == 400


# ---------------------------------------------------------------- 모델 입력과 분리

def test_model_side_code_does_not_import_customer_repository():
    targets = [*(PROJECT_ROOT / "agent").rglob("*.py"), *(PROJECT_ROOT / "tools").rglob("*.py"),
               PROJECT_ROOT / "mail" / "email_service.py"]
    offenders = [str(p) for p in targets if "customer_repo" in p.read_text(encoding="utf-8")
                 or "customer_repository" in p.read_text(encoding="utf-8")]
    assert offenders == []


def test_other_inquiry_not_in_model_input(agent_env, monkeypatch):
    from langchain_core.messages import AIMessage

    from entity.type import MailEntity
    from mail import email_service
    from mail.email_send import SendOutcome, SendResult
    from test_email_consumer import OneShotStop

    first = MailEntity(uid="mA", subject="무게 문의", sender="a@example.com", body="A본문-N5800무게",
                       received_at=datetime.now())
    with agent_env.db.transaction() as conn:
        agent_env.email_repo.save_pending(first, conn)
        agent_env.task_repo.create_task("mA", conn)
    model = agent_env.install([AIMessage(content="A초안-1.5kg"), AIMessage(content="B초안-KC")])
    monkeypatch.setattr(email_service, "send_email", lambda *a, **k: SendResult(SendOutcome.SENT, "DATA 250"))
    email_service.email_consumer_loop(OneShotStop(), agent_env.email_repo, agent_env.task_repo)

    second = MailEntity(uid="mB", subject="인증 문의", sender="A@example.com", body="B본문-KC인증",
                        received_at=datetime.now())
    with agent_env.db.transaction() as conn:
        agent_env.email_repo.save_pending(second, conn)
        agent_env.task_repo.create_task("mB", conn)
    email_service.email_consumer_loop(OneShotStop(), agent_env.email_repo, agent_env.task_repo)

    assert len(model.calls) == 2
    b_input = "\n".join(str(m.content) for m in model.calls[1])
    assert "B본문-KC인증" in b_input
    assert "A본문-N5800무게" not in b_input and "A초안-1.5kg" not in b_input and "무게 문의" not in b_input
