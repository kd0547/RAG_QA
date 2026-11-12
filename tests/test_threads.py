"""C1: 대화 기록(checkpoint). 메일은 task:{task_id}, /ask는 호출마다 새 대화."""
import sqlite3

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from agent.evidence_context import Owner


@pytest.fixture
def saver(tmp_path):
    from agent.agent import open_checkpointer

    checkpointer = open_checkpointer(tmp_path / "threads.db")
    yield checkpointer
    checkpointer.conn.close()


def _threads(path) -> set[str]:
    with sqlite3.connect(path) as conn:
        return {row[0] for row in conn.execute("SELECT DISTINCT thread_id FROM checkpoints")}


def test_task_thread_is_saved_and_continued(agent_env, saver, tmp_path):
    from agent import agent as agent_module

    model = agent_env.install([
        AIMessage(content="첫 답변\n근거: 없음"),
        AIMessage(content="둘째 답변\n근거: 없음"),
    ], checkpointer=saver)
    thread = agent_module.task_thread_id("t1")

    agent_module.run_agent_temp_attachments("첫 질문", mode="local", owner=Owner("task", "t1"), thread_id=thread)
    agent_module.run_agent("이어서 묻기", mode="local", owner=Owner("task", "t1"), thread_id=thread)

    assert _threads(tmp_path / "threads.db") == {"task:t1"}
    second_input = [m for m in model.calls[1] if isinstance(m, (HumanMessage, AIMessage))]
    assert [m.content if isinstance(m.content, str) else m.content[0]["text"] for m in second_input] == [
        "첫 질문", "첫 답변\n근거: 없음", "이어서 묻기",
    ]
    assert agent_module.thread_message_count(thread) == 4


def test_ask_uses_new_thread_each_call(agent_env, saver, tmp_path):
    from agent import agent as agent_module

    agent_env.install([AIMessage(content="답1\n근거: 없음"), AIMessage(content="답2\n근거: 없음")], checkpointer=saver)

    agent_module.run_agent("질문", mode="local")
    agent_module.run_agent("질문", mode="local")

    threads = _threads(tmp_path / "threads.db")
    assert len(threads) == 2 and all(t.startswith("ask:") for t in threads)


def test_run_counts_only_this_runs_messages(agent_env, saver):
    """대화가 이어져도 실행 기록의 도구 호출·토큰은 이번 실행 것만 센다."""
    from agent import agent as agent_module

    first = AIMessage(content="첫 답\n근거: 없음", usage_metadata={"input_tokens": 100, "output_tokens": 10, "total_tokens": 110})
    second = AIMessage(content="둘째 답\n근거: 없음", usage_metadata={"input_tokens": 300, "output_tokens": 20, "total_tokens": 320})
    agent_env.install([first, second], checkpointer=saver)

    agent_module.run_agent("q1", mode="local", owner=Owner("task", "t1"), thread_id="task:t1")
    out = agent_module.run_agent("q2", mode="local", owner=Owner("task", "t1"), thread_id="task:t1")

    run = agent_env.evidence_repo.get_run(out["run_id"])
    assert (run["tokens_in"], run["tokens_out"]) == (300, 20)
    assert out["answer"] == "둘째 답"


def test_consumer_uses_task_thread(monkeypatch):
    from types import SimpleNamespace

    from entity.type import MailEntity, TaskEntity
    from mail import email_service
    from mail.email_send import SendOutcome, SendResult
    from test_email_consumer import FakeTaskRepo, OneShotStop

    seen = {}

    def fake_run(*args, **kwargs):
        seen.update(kwargs)
        return {"answer": "답", "sources": [], "validation": None}

    monkeypatch.setattr(email_service, "run_agent_temp_attachments", fake_run)
    monkeypatch.setattr(email_service, "send_email", lambda *a, **k: SendResult(SendOutcome.SENT, "DATA 250"))
    mail = MailEntity(uid="m1", subject="s", sender="a@b.c", body="질문")

    email_service.email_consumer_loop(OneShotStop(), SimpleNamespace(get_mail_by_id=lambda uid: mail),
                                      FakeTaskRepo(TaskEntity(task_id="t7", mail_uid="m1")))

    assert seen["thread_id"] == "task:t7" and seen["owner"] == Owner("task", "t7")
