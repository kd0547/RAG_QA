"""C2-P5: 답변 생성 실패(failed) 작업 다시 생성. 한도로 끝난 대화는 재시도 안내를 넣어 같은 결과가 반복되지 않게 한다."""
from datetime import datetime

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from conftest import tool_call
from entity.type import MailEntity, TaskStatus
from test_mail_list import mail_client, mail_data  # noqa: F401  (pytest 픽스처 재사용)


# ---------------------------------------------------------------- API

def test_retry_only_from_failed(mail_client):  # noqa: F811
    client, ids = mail_client
    from app.routers import mails

    mails.task_repo.update_status(ids["drafted"], TaskStatus.FAILED)
    response = client.post(f"/mails/{ids['drafted']}/retry")

    assert response.status_code == 200
    assert response.json() == {"task_id": ids["drafted"], "status": "pending"}
    assert mails.task_repo.get_task(ids["drafted"]).status == TaskStatus.PENDING
    with mails.task_repo.db.get_conn() as conn:
        actions = [tuple(r) for r in conn.execute(
            "SELECT action, reason, requeue FROM task_reviews WHERE task_id = ?", (ids["drafted"],))]
    assert actions == [("retry", None, 1)]
    assert mails.task_repo.latest_retry_id(ids["drafted"]) is not None
    # retry 기록은 반려 사유로 잡히지 않는다
    assert mails.task_repo.unapplied_reject_reasons(ids["drafted"]) == []

    assert client.post(f"/mails/{ids['in_review']}/retry").status_code == 409  # drafted·in_review 등은 불가
    assert client.post(f"/mails/{ids['drafted']}/retry").status_code == 409    # 이미 pending
    assert client.post("/mails/not-found/retry").status_code == 404


def test_migration_adds_retry_to_old_check(tmp_path):
    """A4 시점 제약 CHECK (action IN ('reject', 'mark_sent'))도 이력을 지키며 retry를 받게 된다."""
    import sqlite3

    from repository.repo_connect import Database

    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE tasks (task_id TEXT PRIMARY KEY, mail_uid TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                assignee TEXT, retry_count INTEGER NOT NULL DEFAULT 0, draft_answer TEXT DEFAULT '',
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE task_reviews (review_id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
                action TEXT NOT NULL CHECK (action IN ('reject', 'mark_sent')), reason TEXT,
                requeue INTEGER NOT NULL DEFAULT 1, reviewed_at TEXT NOT NULL);
            INSERT INTO tasks VALUES ('t1', 'm1', 'failed', NULL, 0, '', 'now', 'now');
            INSERT INTO task_reviews VALUES (4, 't1', 'mark_sent', '확인', 0, 'now');
        """)

    db = Database(str(path))
    with db.get_conn() as conn:
        conn.execute("INSERT INTO task_reviews (task_id, action, requeue, reviewed_at) VALUES ('t1', 'retry', 1, 'now')")
        rows = [tuple(r) for r in conn.execute("SELECT review_id, action FROM task_reviews ORDER BY review_id")]
    assert rows == [(4, "mark_sent"), (5, "retry")]


# ---------------------------------------------------------------- 재시도 실행 경로

@pytest.fixture
def limited(agent_env, tmp_path, monkeypatch):
    """모델 호출 한도를 2회로 줄이고 임시 checkpointer를 쓴다."""
    from agent import agent as agent_module
    from agent.agent import open_checkpointer

    monkeypatch.setattr(agent_module, "MODEL_CALLS_PER_RUN", 2)
    saver = open_checkpointer(tmp_path / "threads.db")
    yield saver
    saver.conn.close()


def _retry_humans(agent_module, thread_id) -> list[HumanMessage]:
    state = agent_module.get_agent("local").get_state({"configurable": {"thread_id": thread_id}})
    return [m for m in state.values["messages"] if isinstance(m, HumanMessage) and str(m.id).startswith("retry:")]


def test_limit_ended_task_is_retried_through_consumer(agent_env, limited, monkeypatch):
    from agent import agent as agent_module
    from mail import email_service
    from mail.email_send import SendOutcome, SendResult
    from test_email_consumer import OneShotStop, join_notify_threads

    mail = MailEntity(uid="m1", subject="무게", sender="c@example.com", body="N5800 무게", received_at=datetime.now())
    with agent_env.db.transaction() as conn:
        agent_env.email_repo.save_pending(mail, conn)
        task_id = agent_env.task_repo.create_task("m1", conn).task_id
    model = agent_env.install([
        tool_call("list_documents", {}, "c1"),
        tool_call("list_documents", {}, "c2"),
        # 여기서 모델 호출 한도(2회) → 1차 실행 실패
        AIMessage(content="문서에서 찾지 못했습니다.\n근거: 없음"),  # 재시도 실행의 답변
    ], checkpointer=limited)
    monkeypatch.setattr(email_service, "send_email", lambda *a, **k: SendResult(SendOutcome.SENT, "DATA 250"))

    email_service.email_consumer_loop(OneShotStop(), agent_env.email_repo, agent_env.task_repo)
    assert agent_env.task_repo.get_task(task_id).status == TaskStatus.FAILED
    assert agent_env.evidence_repo.latest_run("task", task_id)["status"] == "limit"

    assert agent_env.task_repo.retry(task_id)
    email_service.email_consumer_loop(OneShotStop(), agent_env.email_repo, agent_env.task_repo)
    join_notify_threads()

    task = agent_env.task_repo.get_task(task_id)
    assert task.status == TaskStatus.DRAFTED and task.draft_answer == "문서에서 찾지 못했습니다."
    retry_input = model.calls[-1]
    assert retry_input[-1].content == agent_module.RETRY_TEXT
    thread = f"task:{task_id}"
    retries = _retry_humans(agent_module, thread)
    assert [m.id for m in retries] == [f"retry:{thread}:{agent_env.task_repo.latest_retry_id(task_id)}"]
    runs = agent_env.evidence_repo.runs_for_owner("task", task_id)
    assert [r["status"] for r in runs] == ["limit", "ok"] and runs[1]["label"].startswith("메일 재시도")


def test_same_retry_twice_adds_one_message(agent_env, limited):
    from agent import agent as agent_module
    from agent.evidence_context import Owner

    owner, thread = Owner("task", "t1"), "task:t1"
    agent_env.install([
        tool_call("list_documents", {}, "c1"),
        tool_call("list_documents", {}, "c2"),
        AIMessage(content="다시 쓴 답\n근거: 없음"),
    ], checkpointer=limited)
    with pytest.raises(agent_module.AgentRunError):
        agent_module.run_agent_temp_attachments("질문", mode="local", owner=owner, thread_id=thread)

    first = agent_module.run_agent_temp_attachments("질문", mode="local", owner=owner, thread_id=thread, retry_id=9)
    # 같은 재시도를 한 번 더 처리: 대화가 정상 답변으로 끝나 있으므로 새 메시지 없이 그 답변을 돌려준다
    second = agent_module.run_agent_temp_attachments("질문", mode="local", owner=owner, thread_id=thread, retry_id=9)

    assert first["answer"] == second["answer"] == "다시 쓴 답"
    assert [m.id for m in _retry_humans(agent_module, thread)] == [f"retry:{thread}:9"]


def test_interrupted_thread_still_resumes_without_retry_message(agent_env, limited):
    """중간에 끊긴 대화(next 남음)는 재시도 메시지 없이 checkpoint에서 이어 간다 (C4 동작 유지)."""
    from agent import agent as agent_module
    from agent.evidence_context import Owner

    def dies(messages):
        raise ConnectionError("끊김")

    owner, thread = Owner("task", "t2"), "task:t2"
    agent_env.install([tool_call("list_documents", {}, "c1"), dies, AIMessage(content="이어서 답\n근거: 없음")],
                      checkpointer=limited)
    with pytest.raises(ConnectionError):
        agent_module.run_agent_temp_attachments("질문", mode="local", owner=owner, thread_id=thread)

    out = agent_module.run_agent_temp_attachments("질문", mode="local", owner=owner, thread_id=thread, retry_id=3)

    assert out["answer"] == "이어서 답"
    assert _retry_humans(agent_module, thread) == []
