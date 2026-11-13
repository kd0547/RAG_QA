"""B1: 근거 저장소와 실행 기록, 에이전트 실행 중 owner/run 전달."""
from langchain_core.messages import AIMessage

from agent.evidence_context import Owner, current_owner, current_run, owner_scope, run_scope


def test_same_page_same_revision_returns_same_id(agent_env):
    repo = agent_env.evidence_repo

    first = repo.register("task", "t1", "file_page", "본문", file_id="f1", page_id=3, page=2, revision="2026-11-12 10:00:00")
    again = repo.register("task", "t1", "file_page", "본문", file_id="f1", page_id=3, page=2, revision="2026-11-12 10:00:00")
    edited = repo.register("task", "t1", "file_page", "고친 본문", file_id="f1", page_id=3, page=2, revision="2026-11-12 10:05:00")
    other_owner = repo.register("task", "t2", "file_page", "본문", file_id="f1", page_id=3, page=2, revision="2026-11-12 10:00:00")

    assert first == again
    assert first.startswith("e") and len(first) == 9
    assert len({first, edited, other_owner}) == 3


def test_get_respects_owner(agent_env):
    repo = agent_env.evidence_repo
    eid = repo.register("task", "t1", "chunk", "청크", file_id="f1", page=1)

    assert repo.get(eid)["text"] == "청크"
    assert repo.get(eid, "task", "t1")["owner_id"] == "t1"
    assert repo.get(eid, "task", "t2") is None
    assert repo.get(eid, "session", "t1") is None
    assert repo.get_many([eid, "e00000000", eid], "task", "t1") == [repo.get(eid)]
    row = repo.get(eid)
    assert {"owner_id", "origin_type", "file_id", "page_id", "revision", "content_hash", "text"} <= set(row)


def test_list_for_owner_and_uses(agent_env):
    repo = agent_env.evidence_repo
    a = repo.register("session", "s1", "chunk", "가", file_id="f1", page=1)
    b = repo.register("session", "s1", "chunk", "나", file_id="f1", page=1)
    repo.register("session", "s2", "chunk", "다", file_id="f1", page=1)
    run = repo.start_run("session", "s1", "qwen", None)
    repo.record_use(run, b, "read")
    repo.record_use(run, a, "read")
    repo.record_use(run, b, "read")
    repo.record_use(run, a, "cite")

    assert [e["evidence_id"] for e in repo.list_for_owner("session", "s1")] == [a, b]
    assert [u["evidence_id"] for u in repo.uses_for_run(run, "read")] == [b, a]
    assert [u["evidence_id"] for u in repo.uses_for_run(run, "cite")] == [a]
    assert [(u["evidence_id"], u["action"]) for u in repo.uses_for_run(run)] == [(b, "read"), (a, "read")]


def test_run_lifecycle(agent_env):
    repo = agent_env.evidence_repo
    run = repo.start_run("task", "t1", "qwen", 2)
    assert repo.get_run(run)["status"] == "running"

    repo.finish_run(run, "limit", [{"tool": "read_pages"}], 100, 20, "recursion")

    row = repo.get_run(run)
    assert (row["status"], row["tokens_in"], row["tokens_out"], row["error"]) == ("limit", 100, 20, "recursion")
    assert repo.latest_run("task", "t1")["run_id"] == run


def test_context_scopes_reset():
    assert current_owner() is None and current_run() is None
    with owner_scope(Owner("task", "t1")):
        with run_scope("r1"):
            assert current_owner() == Owner("task", "t1") and current_run() == "r1"
        assert current_run() is None
    assert current_owner() is None


def test_run_agent_records_run_for_task_owner(agent_env):
    from agent import agent as agent_module

    agent_env.install([AIMessage(content="답변입니다")])

    out = agent_module.run_agent_temp_attachments("질문", mode="local", owner=Owner("task", "t9"))

    assert out["answer"] == "답변입니다"
    run = agent_env.evidence_repo.latest_run("task", "t9")
    assert run["status"] == "ok" and run["model"]
    assert current_owner() is None  # 끝나면 해제


def test_run_agent_without_owner_uses_new_session(agent_env):
    from agent import agent as agent_module

    agent_env.install([AIMessage(content="첫 답")])
    agent_module.run_agent("질문", mode="local")

    with agent_env.db.get_conn() as conn:
        rows = conn.execute("SELECT owner_type, status FROM run").fetchall()
    assert [tuple(r) for r in rows] == [("session", "ok")]


# ---------------------------------------------------------------- C2-P6 웹 질문 기록 정리

def test_purge_sessions_removes_only_old_session_rows(agent_env):
    from datetime import datetime, timedelta

    repo = agent_env.evidence_repo
    old_ev = repo.register("session", "s-old", "chunk", "옛 근거", file_id="f", page=1)
    old_run = repo.start_run("session", "s-old", "qwen", None)
    repo.record_use(old_run, old_ev, "read")
    new_ev = repo.register("session", "s-new", "chunk", "어제 근거", file_id="f", page=1)
    new_run = repo.start_run("session", "s-new", "qwen", None)
    repo.record_use(new_run, new_ev, "read")
    task_ev = repo.register("task", "t1", "chunk", "메일 근거", file_id="f", page=1)
    task_run = repo.start_run("task", "t1", "qwen", None)
    repo.record_use(task_run, task_ev, "read")
    month_ago = (datetime.now() - timedelta(days=30)).isoformat()
    yesterday = (datetime.now() - timedelta(days=1)).isoformat()
    with agent_env.db.get_conn() as conn:
        conn.execute("UPDATE evidence SET created_at = ? WHERE evidence_id IN (?, ?)", (month_ago, old_ev, task_ev))
        conn.execute("UPDATE run SET started_at = ? WHERE run_id IN (?, ?)", (month_ago, old_run, task_run))
        conn.execute("UPDATE evidence SET created_at = ? WHERE evidence_id = ?", (yesterday, new_ev))
        conn.execute("UPDATE run SET started_at = ? WHERE run_id = ?", (yesterday, new_run))

    assert repo.purge_sessions(14) == {"evidence": 1, "evidence_use": 1, "run": 1}

    assert repo.get(old_ev) is None and repo.get_run(old_run) is None
    assert repo.get(new_ev) is not None and repo.get_run(new_run) is not None
    assert repo.get(task_ev) is not None and repo.get_run(task_run) is not None  # 30일 지난 메일 기록도 남는다
    assert [u["evidence_id"] for u in repo.uses_for_run(task_run)] == [task_ev]


def test_lifespan_purges_sessions_with_configured_days():
    from pathlib import Path

    import config

    source = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
    assert "evidence_repo.purge_sessions(config.SESSION_EVIDENCE_RETENTION_DAYS)" in source
    assert config.SESSION_EVIDENCE_RETENTION_DAYS == 14
