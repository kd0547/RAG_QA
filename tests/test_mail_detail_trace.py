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


# ---------------------------------------------------------------- C2-P3 실행 이력 전체

def test_detail_runs_keep_first_run_tools_after_rejection(agent_env, tmp_path, monkeypatch):
    from agent.agent import open_checkpointer
    from app.routers import mails
    from entity.type import TaskStatus
    from mail import email_service
    from mail.email_send import SendOutcome, SendResult
    from test_email_consumer import OneShotStop

    mail = MailEntity(uid="m3", subject="무게", sender="c@example.com", body="N5800 무게", received_at=datetime.now())
    with agent_env.db.transaction() as conn:
        agent_env.email_repo.save_pending(mail, conn)
        task_id = agent_env.task_repo.create_task("m3", conn).task_id
    file = create_file(original_name="guide.pdf", stored_path=str(tmp_path / "g.pdf"))
    agent_env.file_repo.file_save(file)
    agent_env.page_repo.save_pages(file.file_id, [PageText(1, "표지"), PageText(2, "무게 1.5kg")])

    def cite(messages):
        read = json.loads([m for m in messages if isinstance(m, ToolMessage) and m.name == "read_pages"][-1].content)
        return AIMessage(content=f"1.5kg입니다.\n근거: {read['pages'][0]['evidence_id']}")

    saver = open_checkpointer(tmp_path / "threads.db")
    agent_env.install([
        tool_call("list_documents", {}, "a"),
        tool_call("grep_documents", {"pattern": "무게"}, "b"),
        tool_call("read_pages", {"file_id": file.file_id, "pages": [2]}, "c"),
        cite,
        cite,
    ], checkpointer=saver)
    monkeypatch.setattr(email_service, "send_email", lambda *a, **k: SendResult(SendOutcome.SENT, "DATA 250"))
    email_service.email_consumer_loop(OneShotStop(), agent_env.email_repo, agent_env.task_repo)
    agent_env.task_repo.reject(task_id, "존댓말로", TaskStatus.PENDING, [TaskStatus.DRAFTED])
    email_service.email_consumer_loop(OneShotStop(), agent_env.email_repo, agent_env.task_repo)
    saver.conn.close()

    monkeypatch.setattr(mails, "task_repo", agent_env.task_repo)
    monkeypatch.setattr(mails, "evidence_repo", agent_env.evidence_repo)
    runs = mails.view_mail_detail(task_id)["runs"]

    assert [len(r["tool_calls"]) for r in runs] == [3, 0]
    assert [t["tool"] for t in runs[0]["tool_calls"]] == ["list_documents", "grep_documents", "read_pages"]
    assert runs[0]["label"].startswith("메일(첨부 0건") and runs[1]["label"].startswith("메일 반려 반영(review_id=")
    assert all(r["status"] == "ok" and r["seconds"] is not None for r in runs)
    assert set(runs[0]) == {"run_id", "label", "status", "started_at", "seconds", "tokens_in", "tokens_out", "tool_calls", "skills"}


def test_runs_for_owner_handles_legacy_rows(agent_env):
    """label 컬럼이 생기기 전 실행(label NULL)·끝나지 않은 실행도 깨지지 않는다."""
    repo = agent_env.evidence_repo
    old = repo.start_run("task", "t9", "qwen", None)
    repo.finish_run(old, "ok", [{"tool": "search_documents", "args_summary": "{}", "at": "2026-11-12T10:00:00"}], 10, 1)
    running = repo.start_run("task", "t9", "qwen", None, label="메일(첨부 0건, 반려 없음)")

    runs = repo.runs_for_owner("task", "t9")

    assert [(r["run_id"], r["label"]) for r in runs] == [(old, None), (running, "메일(첨부 0건, 반려 없음)")]
    assert [len(r["tool_calls"]) for r in runs] == [1, 0]
    assert runs[1]["seconds"] is None and runs[1]["status"] == "running"


def test_migration_adds_run_label(tmp_path):
    import sqlite3

    from repository.repo_connect import Database

    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.execute("""CREATE TABLE run (
            run_id TEXT PRIMARY KEY, owner_type TEXT NOT NULL, owner_id TEXT NOT NULL,
            model TEXT, prompt_id INTEGER, started_at TEXT NOT NULL, ended_at TEXT,
            status TEXT NOT NULL, tool_calls_json TEXT, tokens_in INTEGER, tokens_out INTEGER, error TEXT)""")
        conn.execute("INSERT INTO run (run_id, owner_type, owner_id, started_at, status) VALUES ('r1', 'task', 't', 'x', 'ok')")

    db = Database(str(path))

    with db.get_conn() as conn:
        assert "label" in {row["name"] for row in conn.execute("PRAGMA table_info(run)")}
        assert conn.execute("SELECT label FROM run WHERE run_id = 'r1'").fetchone()[0] is None
