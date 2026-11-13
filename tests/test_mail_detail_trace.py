"""C5: 메일 상세 응답의 trace(에이전트가 한 일)·validation·인용/읽기 근거 구분."""
import json
from datetime import datetime

from langchain_core.messages import AIMessage, ToolMessage

from conftest import tool_call
from entity.file import create_file
from entity.type import MailEntity
from parser.pdf.type import PageText


def test_detail_has_trace_validation_and_read_sources(agent_env, tmp_path, monkeypatch):
    from app.routers import mails
    from mail import email_service
    from mail.email_send import SendOutcome, SendResult
    from test_email_consumer import OneShotStop

    mail = MailEntity(uid="m1", subject="무게", sender="c@example.com", body="N5800 무게", received_at=datetime.now())
    with agent_env.db.transaction() as conn:
        agent_env.email_repo.save_pending(mail, conn)
        task_id = agent_env.task_repo.create_task("m1", conn).task_id
    file = create_file(original_name="guide.pdf", stored_path=str(tmp_path / "g.pdf"))
    agent_env.file_repo.file_save(file)
    agent_env.page_repo.save_pages(file.file_id, [PageText(1, "표지"), PageText(2, "무게 1.5kg")])

    def cite_page_two(messages):
        read = json.loads(next(m for m in messages if isinstance(m, ToolMessage)).content)
        page2 = next(p for p in read["pages"] if p["page"] == 2)
        return AIMessage(content=f"1.5kg입니다.\n근거: {page2['evidence_id']}")

    agent_env.install([tool_call("read_pages", {"file_id": file.file_id, "pages": [1, 2]}), cite_page_two])
    monkeypatch.setattr(email_service, "send_email", lambda *a, **k: SendResult(SendOutcome.SENT, "DATA 250"))
    email_service.email_consumer_loop(OneShotStop(), agent_env.email_repo, agent_env.task_repo)

    monkeypatch.setattr(mails, "task_repo", agent_env.task_repo)
    monkeypatch.setattr(mails, "evidence_repo", agent_env.evidence_repo)
    detail = mails.view_mail_detail(task_id)

    assert detail["draft"] == "1.5kg입니다."
    assert [(s["page"], s["cited"]) for s in detail["sources"]] == [(2, True)]
    assert [(s["page"], s["cited"], s["source"]) for s in detail["read_sources"]] == [(1, False, "guide.pdf")]
    assert detail["validation"]["ok"] is True
    assert [t["tool"] for t in detail["trace"]] == ["read_pages"]
    assert file.file_id in detail["trace"][0]["args_summary"] and detail["trace"][0]["at"]


def test_detail_without_runs_has_empty_trace(agent_env, monkeypatch):
    from app.routers import mails

    mail = MailEntity(uid="m2", subject="s", sender="a@b.c", body="q", received_at=datetime.now())
    with agent_env.db.transaction() as conn:
        agent_env.email_repo.save_pending(mail, conn)
        task_id = agent_env.task_repo.create_task("m2", conn).task_id
    monkeypatch.setattr(mails, "task_repo", agent_env.task_repo)
    monkeypatch.setattr(mails, "evidence_repo", agent_env.evidence_repo)

    detail = mails.view_mail_detail(task_id)

    assert detail["trace"] == [] and detail["read_sources"] == [] and detail["validation"] is None
