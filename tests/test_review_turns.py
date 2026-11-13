"""C3: 담당자 반려를 같은 대화(thread)의 다음 턴으로 넣는다."""
import json
from datetime import datetime

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent.evidence_context import Owner
from conftest import tool_call
from entity.file import create_file
from entity.type import MailEntity, TaskStatus
from parser.pdf.type import PageText


@pytest.fixture
def saver(tmp_path):
    from agent.agent import open_checkpointer

    checkpointer = open_checkpointer(tmp_path / "threads.db")
    yield checkpointer
    checkpointer.conn.close()


@pytest.fixture
def mail_task(agent_env, tmp_path):
    """메일 1건과 task, 근거 문서 1개."""
    mail = MailEntity(uid="m1", subject="N5800 무게", sender="c@example.com", body="N5800 무게 알려주세요",
                      received_at=datetime.now())
    with agent_env.db.transaction() as conn:
        agent_env.email_repo.save_pending(mail, conn)
        task_id = agent_env.task_repo.create_task("m1", conn).task_id
    file = create_file(original_name="guide.pdf", stored_path=str(tmp_path / "g.pdf"))
    agent_env.file_repo.file_save(file)
    agent_env.page_repo.save_pages(file.file_id, [PageText(1, "N5800 무게 1.5kg")])
    return task_id, file.file_id


def _cite_last_read(messages) -> AIMessage:
    """대화에서 가장 최근 read_pages 결과의 근거를 인용해 답한다."""
    reads = [json.loads(m.content) for m in messages if isinstance(m, ToolMessage) and m.name == "read_pages"]
    evidence_id = reads[-1]["pages"][0]["evidence_id"]
    return AIMessage(content=f"무게는 1.5kg입니다.\n근거: {evidence_id}")


def _run_consumer(agent_env, monkeypatch):
    """메일 처리 루프를 한 주기 돌린다 (알림 발송은 대역)."""
    from mail import email_service
    from mail.email_send import SendOutcome, SendResult
    from test_email_consumer import OneShotStop

    monkeypatch.setattr(email_service, "send_email", lambda *a, **k: SendResult(SendOutcome.SENT, "DATA 250"))
    email_service.email_consumer_loop(OneShotStop(), agent_env.email_repo, agent_env.task_repo)


def _humans(saver, task_id) -> list[str]:
    from agent import agent as agent_module

    agent = agent_module.get_agent("local")
    state = agent.get_state({"configurable": {"thread_id": f"task:{task_id}"}})
    result = []
    for message in state.values["messages"]:
        if isinstance(message, HumanMessage):
            content = message.content
            result.append(content if isinstance(content, str) else content[0]["text"])
    return result


def test_rejection_continues_same_thread_without_new_search(agent_env, mail_task, saver, monkeypatch):
    task_id, file_id = mail_task
    model = agent_env.install([
        tool_call("read_pages", {"file_id": file_id, "pages": [1]}),
        _cite_last_read,
        _cite_last_read,  # 반려 후: 대화에 남아 있는 근거로 바로 다시 답한다
    ], checkpointer=saver)

    _run_consumer(agent_env, monkeypatch)
    assert agent_env.task_repo.get_task(task_id).status == TaskStatus.DRAFTED
    first_run = agent_env.evidence_repo.latest_run("task", task_id)

    agent_env.task_repo.reject(task_id, "존댓말로 다시 써 주세요", TaskStatus.PENDING, [TaskStatus.DRAFTED])
    [(review_id, _)] = agent_env.task_repo.unapplied_reject_reasons(task_id)
    _run_consumer(agent_env, monkeypatch)

    # 두 번째 실행의 모델 입력: 1차의 read_pages 결과와 반려 안내가 같은 대화에 있다
    second_input = model.calls[2]
    assert any(isinstance(m, ToolMessage) and m.name == "read_pages" for m in second_input)
    assert isinstance(second_input[-1], HumanMessage) and second_input[-1].content.startswith("[검토 담당자 반려]\n- 존댓말로")
    assert "<previous_draft>" not in second_input[-1].content  # 이전 초안을 다시 붙이지 않는다

    second_run = agent_env.evidence_repo.latest_run("task", task_id)
    assert second_run["run_id"] != first_run["run_id"]
    assert json.loads(second_run["tool_calls_json"]) == []  # 다시 검색·읽기 없음
    task = agent_env.task_repo.get_task(task_id)
    assert task.status == TaskStatus.DRAFTED
    validation = agent_env.task_repo.get_validation(task_id)
    assert validation["ok"] is True and validation["warnings"] == []
    assert [s["cited"] for s in agent_env.task_repo.get_sources(task_id)] == [1]
    assert agent_env.task_repo.unapplied_reject_reasons(task_id) == []
    with agent_env.db.get_conn() as conn:
        assert conn.execute("SELECT last_review_id FROM tasks WHERE task_id = ?", (task_id,)).fetchone()[0] == review_id
    assert len(_humans(saver, task_id)) == 2


def test_same_review_twice_adds_one_message(agent_env, mail_task, saver):
    from agent import agent as agent_module

    task_id, file_id = mail_task
    agent_env.install([
        tool_call("read_pages", {"file_id": file_id, "pages": [1]}),
        _cite_last_read, _cite_last_read, _cite_last_read,
    ], checkpointer=saver)
    owner, thread = Owner("task", task_id), f"task:{task_id}"
    agent_module.run_agent_temp_attachments("N5800 무게", mode="local", owner=owner, thread_id=thread)

    review = (7, "[검토 담당자 반려]\n- 표로 정리")
    agent_module.run_agent_temp_attachments("N5800 무게", mode="local", review=review, owner=owner, thread_id=thread)
    agent_module.run_agent_temp_attachments("N5800 무게", mode="local", review=review, owner=owner, thread_id=thread)

    assert _humans(saver, task_id) == ["N5800 무게", "[검토 담당자 반려]\n- 표로 정리"]


def test_rejection_without_checkpoint_starts_over_with_reasons(agent_env, mail_task, saver):
    """마이그레이션 전 task: 대화 기록이 없으면 질문과 반려 안내를 두 user 메시지로 함께 넣는다."""
    from agent import agent as agent_module

    task_id, _ = mail_task
    model = agent_env.install([AIMessage(content="다시 씁니다\n근거: 없음")], checkpointer=saver)

    agent_module.run_agent_temp_attachments(
        "N5800 무게", mode="local", review=(3, "[검토 담당자 반려]\n- 수치 확인"),
        owner=Owner("task", task_id), thread_id=f"task:{task_id}",
    )

    humans = [m for m in model.calls[0] if isinstance(m, HumanMessage)]
    assert len(humans) == 2
    assert humans[0].content[0]["text"] == "N5800 무게" and humans[1].content == "[검토 담당자 반려]\n- 수치 확인"


def test_unapplied_reasons_respect_last_review_id(agent_env, mail_task):
    task_id, _ = mail_task
    repo = agent_env.task_repo
    repo.save_draft(task_id, "초안")
    repo.reject(task_id, "첫 반려", TaskStatus.PENDING, [TaskStatus.DRAFTED])
    [(first, _)] = repo.unapplied_reject_reasons(task_id)
    repo.save_draft(task_id, "고친 초안", applied_review_id=first)
    repo.reject(task_id, "둘째 반려", TaskStatus.PENDING, [TaskStatus.DRAFTED])
    repo.save_draft(task_id, "초안3")
    repo.reject(task_id, "사람이 처리", TaskStatus.FAILED, [TaskStatus.DRAFTED])  # requeue 아님 → 대상 아님

    assert [reason for _, reason in repo.unapplied_reject_reasons(task_id)] == ["둘째 반려"]


def test_review_feedback_text():
    from mail.email_service import build_review_feedback

    assert build_review_feedback([]) is None
    text = build_review_feedback(["존댓말", "표로"])
    assert text.startswith("[검토 담당자 반려]\n- 존댓말\n- 표로\n\n")
