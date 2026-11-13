"""D1: 실행별 초안 본문(run.answer)과 적용 절차 컬럼(run.skills_json)."""
import json
import sqlite3
from datetime import datetime

from langchain_core.messages import AIMessage, ToolMessage

from conftest import tool_call
from entity.file import create_file
from entity.type import MailEntity
from parser.pdf.type import PageText


def _cite(text):
    def reply(messages):
        read = json.loads([m for m in messages if isinstance(m, ToolMessage) and m.name == "read_pages"][-1].content)
        return AIMessage(content=f"{text}\n근거: {read['pages'][0]['evidence_id']}")
    return reply


def test_first_and_rejected_drafts_both_kept(agent_env, tmp_path, monkeypatch):
    from agent.agent import open_checkpointer
    from entity.type import TaskStatus
    from mail import email_service
    from mail.email_send import SendOutcome, SendResult
    from test_email_consumer import OneShotStop

    mail = MailEntity(uid="m1", subject="무게", sender="c@example.com", body="N5800 무게", received_at=datetime.now())
    with agent_env.db.transaction() as conn:
        agent_env.email_repo.save_pending(mail, conn)
        task_id = agent_env.task_repo.create_task("m1", conn).task_id
    file = create_file(original_name="guide.pdf", stored_path=str(tmp_path / "g.pdf"))
    agent_env.file_repo.file_save(file)
    agent_env.page_repo.save_pages(file.file_id, [PageText(1, "무게 1.5kg")])

    saver = open_checkpointer(tmp_path / "threads.db")
    agent_env.install([
        tool_call("read_pages", {"file_id": file.file_id, "pages": [1]}, "a"),
        _cite("| 항목 | 값 |\n| 무게 | 1.5kg |"),
        _cite("무게는 1.5kg입니다."),
    ], checkpointer=saver)
    monkeypatch.setattr(email_service, "send_email", lambda *a, **k: SendResult(SendOutcome.SENT, "DATA 250"))
    email_service.email_consumer_loop(OneShotStop(), agent_env.email_repo, agent_env.task_repo)
    agent_env.task_repo.reject(task_id, "표를 빼고 문장으로", TaskStatus.PENDING, [TaskStatus.DRAFTED])
    email_service.email_consumer_loop(OneShotStop(), agent_env.email_repo, agent_env.task_repo)
    saver.conn.close()

    runs = agent_env.evidence_repo.runs_for_owner("task", task_id)

    assert [r["answer"] for r in runs] == ["| 항목 | 값 |\n| 무게 | 1.5kg |", "무게는 1.5kg입니다."]
    assert all("근거:" not in r["answer"] for r in runs)
    assert runs[1]["answer"] == agent_env.task_repo.get_task(task_id).draft_answer
    # D4: 서버가 적용한 절차 (1차는 답장 문체, 반려 반영 실행은 반려 절차까지)
    assert [[s["name"] for s in r["skills"]] for r in runs] == [
        ["mail-reply-style"], ["mail-reply-style", "revise-after-reject"],
    ]


def test_session_run_has_no_answer(agent_env):
    from agent import agent as agent_module

    agent_env.install([AIMessage(content="첫 답")])
    agent_module.run_agent("질문", mode="local")

    with agent_env.db.get_conn() as conn:
        rows = conn.execute("SELECT owner_type, status, answer FROM run").fetchall()
    assert [tuple(r) for r in rows] == [("session", "ok", None)]


def test_failed_run_has_no_answer(agent_env):
    import pytest

    from agent import agent as agent_module
    from agent.evidence_context import Owner

    agent_env.install([AIMessage(content="")])
    with pytest.raises(agent_module.AgentRunError):
        agent_module.run_agent_temp_attachments("질문", mode="local", owner=Owner("task", "t1"))

    run = agent_env.evidence_repo.latest_run("task", "t1")
    assert run["status"] == "error" and run["answer"] is None


def test_runs_for_owner_reads_skills_json(agent_env):
    repo = agent_env.evidence_repo
    ok = repo.start_run("task", "t2", "qwen", None)
    broken = repo.start_run("task", "t2", "qwen", None)
    with agent_env.db.transaction() as conn:
        conn.execute("UPDATE run SET skills_json = ? WHERE run_id = ?",
                     (json.dumps([{"name": "mail-reply-style", "digest": "abcd1234"}]), ok))
        conn.execute("UPDATE run SET skills_json = '{깨짐' WHERE run_id = ?", (broken,))

    runs = {r["run_id"]: r for r in repo.runs_for_owner("task", "t2")}

    assert runs[ok]["skills"] == [{"name": "mail-reply-style", "digest": "abcd1234"}]
    assert runs[broken]["skills"] == []
    assert "skills_json" not in runs[ok]


def test_migration_adds_answer_and_skills_once(tmp_path):
    from repository.repo_connect import Database

    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.execute("""CREATE TABLE run (
            run_id TEXT PRIMARY KEY, owner_type TEXT NOT NULL, owner_id TEXT NOT NULL,
            model TEXT, prompt_id INTEGER, started_at TEXT NOT NULL, ended_at TEXT,
            status TEXT NOT NULL, tool_calls_json TEXT, tokens_in INTEGER, tokens_out INTEGER, error TEXT,
            label TEXT)""")
        conn.execute("INSERT INTO run (run_id, owner_type, owner_id, started_at, status) VALUES ('r1', 'task', 't', 'x', 'ok')")

    Database(str(path))
    Database(str(path))  # 두 번째 열기에서 같은 컬럼을 다시 더하지 않는다 (duplicate column 오류 없음)

    with sqlite3.connect(path) as conn:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(run)")]
        assert columns.count("answer") == 1 and columns.count("skills_json") == 1
        assert conn.execute("SELECT answer, skills_json FROM run WHERE run_id = 'r1'").fetchone() == (None, None)
