"""B4: 첨부 본문은 메시지에 넣지 않고 read_attachment로 필요한 페이지만 읽는다."""
import json
from datetime import datetime

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent.evidence_context import Owner
from conftest import tool_call
from entity.type import Attachment, MailEntity
from parser.pdf.type import PageText
from tools import tool as tools

FIFTY_PAGES = [PageText(page=i, text=f"{i}페이지 본문 " + "사양 " * 200) for i in range(1, 51)]


@pytest.fixture
def parse_calls(monkeypatch):
    """파서 대역: 50페이지 PDF. 호출 경로를 기록한다."""
    calls = []
    monkeypatch.setattr(tools, "parse_file", lambda path: calls.append(str(path)) or FIFTY_PAGES)
    return calls


def _mail_with_attachments(agent_env, tmp_path, uid, attachments):
    """메일·첨부·task를 임시 DB에 넣고 (task_id, 첨부 목록)을 돌려준다."""
    mail = MailEntity(uid=uid, subject="입찰", sender="c@example.com", body="규격 확인", received_at=datetime.now(),
                      attachments=attachments)
    with agent_env.db.transaction() as conn:
        agent_env.email_repo.save_pending(mail, conn)
        task_id = agent_env.task_repo.create_task(uid, conn).task_id
    return task_id, agent_env.email_repo.get_mail_by_id(uid).attachments


def _user_text(messages) -> str:
    human = next(m for m in messages if isinstance(m, HumanMessage))
    return "".join(b.get("text", "") for b in human.content if isinstance(b, dict))


def test_fifty_page_pdf_is_read_by_page(agent_env, tmp_path, parse_calls):
    from agent import agent as agent_module

    pdf = tmp_path / "규격서.pdf"
    pdf.write_bytes(b"%PDF")
    task_id, attachments = _mail_with_attachments(agent_env, tmp_path, "m1", [
        Attachment(type="pdf", filename="규격서.pdf", content_type="application/pdf", image=None, path=str(pdf)),
    ])
    attachment_id = attachments[0].attachment_id
    seen = {}

    def first(messages):
        seen["user"] = _user_text(messages)
        return tool_call("read_attachment", {"attachment_id": attachment_id, "pages": [25]})

    def answer(messages):
        seen["tool"] = json.loads(messages[-1].content)
        return AIMessage(content="25페이지에 있습니다.")

    agent_env.install([first, answer])
    agent_module.run_agent_temp_attachments("규격 확인", mode="local", attachments=attachments,
                                            owner=Owner("task", task_id))

    assert len(seen["user"]) < 500
    assert f"attachment_id={attachment_id}, 50페이지" in seen["user"]
    assert "사양 사양" not in seen["user"]
    page = seen["tool"]["pages"][0]
    assert page["page"] == 25 and page["text"].startswith("25페이지 본문")
    assert len(parse_calls) == 1  # 메시지를 만들 때 한 번만 파싱하고 저장해 둔 페이지를 읽는다
    assert len(agent_env.email_repo.attachment_pages(attachment_id)) == 50


def test_saved_attachment_pages_are_not_parsed_again(agent_env, tmp_path, parse_calls):
    from agent.evidence_context import owner_scope, run_scope

    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF")
    task_id, attachments = _mail_with_attachments(agent_env, tmp_path, "m2", [
        Attachment(type="pdf", filename="a.pdf", content_type="application/pdf", image=None, path=str(pdf)),
    ])
    run_id = agent_env.evidence_repo.start_run("task", task_id, "test", None)
    with owner_scope(Owner("task", task_id)), run_scope(run_id):
        first = tools.read_attachment.invoke({"attachment_id": attachments[0].attachment_id, "pages": [1]})
        again = tools.read_attachment.invoke({"attachment_id": attachments[0].attachment_id, "pages": [1]})

    assert len(parse_calls) == 1
    assert first["pages"][0]["evidence_id"] == again["pages"][0]["evidence_id"]
    evidence = agent_env.evidence_repo.get(first["pages"][0]["evidence_id"])
    assert (evidence["origin_type"], evidence["attachment_id"], evidence["revision"]) == (
        "attachment", attachments[0].attachment_id, tools.ATTACHMENT_PARSER_VERSION)


def test_other_mails_attachment_is_refused(agent_env, tmp_path, parse_calls):
    from agent.evidence_context import owner_scope, run_scope

    pdf = tmp_path / "b.pdf"
    pdf.write_bytes(b"%PDF")
    _, theirs = _mail_with_attachments(agent_env, tmp_path, "m3", [
        Attachment(type="pdf", filename="b.pdf", content_type="application/pdf", image=None, path=str(pdf)),
    ])
    my_task, _ = _mail_with_attachments(agent_env, tmp_path, "m4", [])
    run_id = agent_env.evidence_repo.start_run("task", my_task, "test", None)

    with owner_scope(Owner("task", my_task)), run_scope(run_id):
        result = tools.read_attachment.invoke({"attachment_id": theirs[0].attachment_id})

    assert "이 질문의 첨부가 아닙니다" in result["error"]
    assert parse_calls == []


def test_temp_attachment_for_ask_session(agent_env, tmp_path, parse_calls):
    """/ask/attachments 임시 첨부: DB에 저장하지 않고 세션 안 음수 번호로 읽는다. 이미지는 그대로 보인다."""
    from agent import agent as agent_module

    doc = tmp_path / "spec.pdf"
    doc.write_bytes(b"%PDF")
    attachments = [
        Attachment(type="pdf", filename="spec.pdf", content_type="application/pdf", image=None, path=str(doc)),
        Attachment(type="image", filename="photo.png", content_type="image/png",
                   image="data:image/png;base64,AAAA", path=None),
    ]
    seen = {}

    def first(messages):
        human = next(m for m in messages if isinstance(m, HumanMessage))
        seen["blocks"] = human.content
        return tool_call("read_attachment", {"attachment_id": -1, "pages": [2], "max_chars": 50})

    def answer(messages):
        seen["tool"] = json.loads(messages[-1].content)
        return AIMessage(content="2페이지 확인")

    agent_env.install([first, answer])
    agent_module.run_agent_temp_attachments("확인", mode="local", attachments=attachments)

    texts = [b["text"] for b in seen["blocks"] if b["type"] == "text"]
    assert any("attachment_id=-1, 50페이지" in t for t in texts)
    assert any(t.startswith("[첨부 2] photo.png (이미지, evidence_id=e") for t in texts)
    assert [b["type"] for b in seen["blocks"]].count("image_url") == 1
    assert seen["tool"]["pages"][0]["page"] == 2 and seen["tool"]["truncated"] is True
    assert len(parse_calls) == 1
    with agent_env.db.get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM attachment_page").fetchone()[0] == 0
        # 이미지와 읽은 페이지가 이번 실행의 읽음으로 남는다
        reads = conn.execute("SELECT COUNT(*) FROM evidence_use WHERE action = 'read'").fetchone()[0]
    assert reads == 2


def test_unreadable_attachment_keeps_a_note(agent_env, tmp_path, monkeypatch):
    from agent import agent as agent_module
    from agent.evidence_context import owner_scope

    def broken(path):
        raise ValueError("깨진 파일")

    monkeypatch.setattr(tools, "parse_file", broken)
    attachment = Attachment(type="hwp", filename="x.hwp", content_type="application/x-hwp", image=None,
                            path=str(tmp_path / "x.hwp"))
    with owner_scope(Owner("session", "s1")):
        blocks = agent_module._attachment_to_blocks(attachment, 1, [])

    assert blocks == [{"type": "text", "text": "[첨부 1] x.hwp (hwp) — 파일을 읽지 못했습니다"}]


def test_tool_message_has_no_full_attachment_text(agent_env, tmp_path, parse_calls):
    """첨부 전문은 어떤 메시지에도 통째로 들어가지 않는다 (read_attachment 분량 제한)."""
    from agent import agent as agent_module

    pdf = tmp_path / "c.pdf"
    pdf.write_bytes(b"%PDF")
    task_id, attachments = _mail_with_attachments(agent_env, tmp_path, "m5", [
        Attachment(type="pdf", filename="c.pdf", content_type="application/pdf", image=None, path=str(pdf)),
    ])
    captured = {}

    def answer(messages):
        captured["messages"] = messages
        return AIMessage(content="끝")

    agent_env.install([tool_call("read_attachment", {"attachment_id": attachments[0].attachment_id}), answer])
    agent_module.run_agent_temp_attachments("확인", mode="local", attachments=attachments, owner=Owner("task", task_id))

    tool_message = next(m for m in captured["messages"] if isinstance(m, ToolMessage))
    body = json.loads(tool_message.content)
    assert sum(len(p["text"]) for p in body["pages"]) == 6000
    assert body["truncated"] is True and body["next_pages"]
