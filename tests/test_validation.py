"""B6: 답변 근거 줄 검증과 실행 기록 (실패·한도 초과·빈 답변은 답변으로 쓰지 않는다)."""
import json

import pytest
from langchain_core.messages import AIMessage

from agent.evidence_context import Owner
from agent.validation import split_evidence_line, validate_answer
from conftest import tool_call
from entity.file import create_file
from parser.pdf.type import PageText

OWNER = Owner("task", "t1")


@pytest.fixture
def run_with_read(agent_env):
    """t1의 실행 하나와 그 실행에서 읽은 근거 하나."""
    repo = agent_env.evidence_repo
    run_id = repo.start_run("task", "t1", "test", None)
    mine = repo.register("task", "t1", "file_page", "무게 1.5kg", file_id="f1", page=2, revision="r")
    repo.record_use(run_id, mine, "read")
    return run_id, mine


def test_split_evidence_line():
    assert split_evidence_line("답입니다.\n\n근거: e1234abcd, e5678ef01\n") == ("답입니다.", "e1234abcd, e5678ef01")
    assert split_evidence_line("**근거**: 없음") == ("", "없음")
    assert split_evidence_line("근거 없이 끝난 답") == ("근거 없이 끝난 답", None)


def test_other_owners_id_is_error(agent_env, run_with_read):
    run_id, _ = run_with_read
    theirs = agent_env.evidence_repo.register("task", "t2", "chunk", "남의 근거", file_id="f9", page=1)

    result = validate_answer(run_id, OWNER, f"답입니다.\n근거: {theirs}")

    assert result.errors == [f"이 질문의 근거가 아닌 ID 인용: {theirs}"]
    assert result.ok is False and result.cited_ids == []
    assert result.answer == "답입니다."
    assert agent_env.evidence_repo.uses_for_run(run_id, "cite") == []


def test_fact_answer_without_reading_is_error(agent_env):
    run_id = agent_env.evidence_repo.start_run("task", "t1", "test", None)

    result = validate_answer(run_id, OWNER, "N5800 무게는 1.5kg입니다.")

    assert "근거를 읽지 않고 답변" in result.errors
    assert "근거 줄 없음" in result.warnings
    assert result.answer == "N5800 무게는 1.5kg입니다."


def test_declared_none_without_reading_is_ok(agent_env):
    run_id = agent_env.evidence_repo.start_run("task", "t1", "test", None)

    result = validate_answer(run_id, OWNER, "문서에서 관련 정보를 찾지 못했습니다.\n근거: 없음")

    assert result.ok is True and result.errors == [] and result.warnings == []
    assert result.answer == "문서에서 관련 정보를 찾지 못했습니다."


def test_valid_citation_is_recorded(agent_env, run_with_read):
    run_id, mine = run_with_read
    unread = agent_env.evidence_repo.register("task", "t1", "chunk", "검색만 됨", file_id="f1", page=3)

    result = validate_answer(run_id, OWNER, f"1.5kg\n근거: {mine}, {unread}, 3페이지")

    assert result.ok is True
    assert result.cited_ids == [mine, unread]
    assert result.warnings == ["근거 ID 형식이 아님: 3페이지", f"이 질문에서 읽지 않은 근거 인용: {unread}"]
    assert [u["evidence_id"] for u in agent_env.evidence_repo.uses_for_run(run_id, "cite")] == [mine, unread]


@pytest.fixture
def guide(agent_env, tmp_path):
    file = create_file(original_name="guide.pdf", stored_path=str(tmp_path / "g.pdf"))
    agent_env.file_repo.file_save(file)
    agent_env.page_repo.save_pages(file.file_id, [PageText(1, "무게 1.5kg")])
    return file.file_id


def test_end_to_end_answer_is_stripped_and_cited(agent_env, guide):
    from agent import agent as agent_module

    def cite(messages):
        evidence_id = json.loads(messages[-1].content)["pages"][0]["evidence_id"]
        return AIMessage(content=f"1.5kg입니다.\n\n근거: {evidence_id}")

    agent_env.install([tool_call("read_pages", {"file_id": guide, "pages": [1]}), cite])

    out = agent_module.run_agent_temp_attachments("무게?", mode="local", owner=OWNER)

    assert out["answer"] == "1.5kg입니다."
    assert out["validation"]["ok"] is True and len(out["validation"]["cited_ids"]) == 1
    assert [(s["page"], s["cited"]) for s in out["sources"]] == [(1, True)]
    run = agent_env.evidence_repo.get_run(out["run_id"])
    trace = json.loads(run["tool_calls_json"])
    assert run["status"] == "ok" and [t["tool"] for t in trace] == ["read_pages"]
    assert trace[0]["at"] and guide in trace[0]["args_summary"]


def test_empty_answer_raises_and_records_error(agent_env):
    from agent import agent as agent_module

    agent_env.install([AIMessage(content="   ")])

    with pytest.raises(agent_module.AgentRunError):
        agent_module.run_agent_temp_attachments("질문", mode="local", owner=OWNER)

    run = agent_env.evidence_repo.latest_run("task", "t1")
    assert (run["status"], run["error"]) == ("error", "빈 답변")


def test_recursion_limit_is_recorded_as_limit(agent_env, monkeypatch):
    from langgraph.errors import GraphRecursionError

    from agent import agent as agent_module

    monkeypatch.setattr(agent_module, "RECURSION_LIMIT", 10)
    agent_env.install([tool_call("list_documents", {}, f"c{i}") for i in range(40)])

    with pytest.raises(GraphRecursionError):
        agent_module.run_agent_temp_attachments("질문", mode="local", owner=OWNER)

    assert agent_env.evidence_repo.latest_run("task", "t1")["status"] == "limit"


def test_model_call_limit_is_recorded_as_limit(agent_env):
    """모델 호출 20회 한도로 끝나면 마지막 메시지는 답변이 아니다 → limit + 예외 (drafted 저장 없음)."""
    from agent import agent as agent_module

    agent_env.install([tool_call("list_documents", {}, f"c{i}") for i in range(40)])

    with pytest.raises(agent_module.AgentRunError):
        agent_module.run_agent_temp_attachments("질문", mode="local", owner=OWNER)

    run = agent_env.evidence_repo.latest_run("task", "t1")
    assert run["status"] == "limit" and run["error"].startswith("Model call limits exceeded")


def test_consumer_marks_failed_not_drafted_when_run_fails(monkeypatch):
    """실행 실패(빈 답변 등)는 예외로 올라와 소비자 루프가 failed로 둔다. drafted 저장은 없다."""
    from types import SimpleNamespace

    from agent.agent import AgentRunError
    from entity.type import MailEntity, TaskEntity, TaskStatus
    from mail import email_service
    from test_email_consumer import FakeTaskRepo, OneShotStop

    def fail(*args, **kwargs):
        raise AgentRunError("빈 답변")

    monkeypatch.setattr(email_service, "run_agent_temp_attachments", fail)
    repo = FakeTaskRepo(TaskEntity(task_id="t1", mail_uid="m1"))
    mail = MailEntity(uid="m1", subject="s", sender="a@b.c", body="질문")

    email_service.email_consumer_loop(OneShotStop(), SimpleNamespace(get_mail_by_id=lambda uid: mail), repo)

    assert repo.statuses == [TaskStatus.PROCESSING, TaskStatus.FAILED]
    assert not any(call[0] == "save_draft" for call in repo.calls)


def test_validation_is_saved_and_shown_in_mail_detail(agent_env):
    from datetime import datetime

    from entity.type import MailEntity

    mail = MailEntity(uid="m1", subject="s", sender="a@b.c", body="q", received_at=datetime.now())
    with agent_env.db.transaction() as conn:
        agent_env.email_repo.save_pending(mail, conn)
        task_id = agent_env.task_repo.create_task("m1", conn).task_id
    validation = {"ok": False, "errors": ["근거를 읽지 않고 답변"], "warnings": [], "cited_ids": []}

    agent_env.task_repo.save_draft(task_id, "답", [], validation=validation)

    assert agent_env.task_repo.get_validation(task_id) == validation
    assert agent_env.task_repo.get_task(task_id).status.value == "drafted"
