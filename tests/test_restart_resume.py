"""C4: 서버 재시작 뒤에도 같은 thread로 이어진다 (storage/agent_threads.db에 checkpoint가 남는다)."""
from datetime import datetime

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent.evidence_context import Owner
from conftest import tool_call
from entity.file import create_file
from entity.type import MailEntity, TaskStatus
from parser.pdf.type import PageText


def _restart(tmp_path, previous=None):
    """서버 재시작 흉내: 이전 연결을 닫고 같은 파일로 checkpointer를 새로 연다."""
    from agent.agent import open_checkpointer

    if previous is not None:
        previous.conn.close()
    return open_checkpointer(tmp_path / "agent_threads.db")


@pytest.fixture
def mail_task(agent_env, tmp_path):
    mail = MailEntity(uid="m1", subject="무게", sender="c@example.com", body="N5800 무게", received_at=datetime.now())
    with agent_env.db.transaction() as conn:
        agent_env.email_repo.save_pending(mail, conn)
        task_id = agent_env.task_repo.create_task("m1", conn).task_id
    file = create_file(original_name="guide.pdf", stored_path=str(tmp_path / "g.pdf"))
    agent_env.file_repo.file_save(file)
    agent_env.page_repo.save_pages(file.file_id, [PageText(1, "N5800 무게 1.5kg")])
    return task_id, file.file_id


def test_new_agent_on_same_db_sees_previous_messages(agent_env, tmp_path):
    from agent import agent as agent_module

    saver = _restart(tmp_path)
    agent_env.install([AIMessage(content="첫 답\n근거: 없음")], checkpointer=saver)
    agent_module.run_agent("첫 질문", mode="local", owner=Owner("task", "t1"), thread_id="task:t1")

    saver = _restart(tmp_path, saver)
    model = agent_env.install([AIMessage(content="이어서\n근거: 없음")], checkpointer=saver)
    agent_module.run_agent("다음 질문", mode="local", owner=Owner("task", "t1"), thread_id="task:t1")
    saver.conn.close()

    contents = [m.content for m in model.calls[0] if isinstance(m, (HumanMessage, AIMessage))]
    assert contents == ["첫 질문", "첫 답\n근거: 없음", "다음 질문"]
    assert (tmp_path / "agent_threads.db").exists()


def test_task_interrupted_while_processing_resumes_same_thread(agent_env, mail_task, tmp_path, monkeypatch):
    """생성 중(processing)에 서버가 꺼진 task: 재시작 시 pending으로 돌아오고, 다음 주기에 checkpoint에서 이어 간다."""
    from agent import agent as agent_module
    from mail import email_service
    from mail.email_send import SendOutcome, SendResult
    from test_email_consumer import OneShotStop

    task_id, file_id = mail_task

    def server_dies(messages):
        raise ConnectionError("서버 종료로 모델 호출이 끊김")

    saver = _restart(tmp_path)
    agent_env.install([tool_call("read_pages", {"file_id": file_id, "pages": [1]}), server_dies], checkpointer=saver)
    agent_env.task_repo.update_status(task_id, TaskStatus.PROCESSING)
    with pytest.raises(ConnectionError):
        agent_module.run_agent_temp_attachments("N5800 무게", mode="local", owner=Owner("task", task_id),
                                                thread_id=f"task:{task_id}")

    # 재시작: lifespan이 processing → pending, 같은 파일로 checkpointer를 다시 연다
    assert agent_env.task_repo.reset_processing() == 1
    saver = _restart(tmp_path, saver)

    def answer(messages):
        read = next(m for m in messages if isinstance(m, ToolMessage) and m.name == "read_pages")
        import json
        return AIMessage(content=f"1.5kg입니다.\n근거: {json.loads(read.content)['pages'][0]['evidence_id']}")

    model = agent_env.install([answer], checkpointer=saver)
    monkeypatch.setattr(email_service, "send_email", lambda *a, **k: SendResult(SendOutcome.SENT, "DATA 250"))
    email_service.email_consumer_loop(OneShotStop(), agent_env.email_repo, agent_env.task_repo)
    saver.conn.close()

    # 질문을 다시 넣지 않고 1차의 읽기 결과에서 이어 간다
    humans = [m for m in model.calls[0] if isinstance(m, HumanMessage)]
    assert len(humans) == 1
    assert any(isinstance(m, ToolMessage) and m.name == "read_pages" for m in model.calls[0])
    task = agent_env.task_repo.get_task(task_id)
    assert task.status == TaskStatus.DRAFTED and task.draft_answer == "1.5kg입니다."
    assert agent_env.task_repo.get_validation(task_id)["ok"] is True


def test_lifespan_resets_processing_before_opening_checkpointer():
    """main.py: reset_processing()이 checkpointer 열기보다 먼저 온다."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
    assert source.index("task_repo.reset_processing()") < source.index("open_checkpointer()")
    assert "checkpointer.conn.close()" in source
