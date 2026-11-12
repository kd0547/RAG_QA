"""B5: 출처는 실행 기록의 근거(인용 > 읽음)에서 만들고, list_evidence로 근거 ID를 다시 볼 수 있다."""
import json

import pytest
from langchain_core.messages import AIMessage

from agent.evidence_context import Owner, owner_scope, run_scope
from conftest import tool_call
from entity.file import create_file
from parser.pdf.type import PageText
from tools import tool as tools


@pytest.fixture
def guide(agent_env, tmp_path):
    file = create_file(original_name="N5800_Guide.pdf", stored_path=str(tmp_path / "g.pdf"))
    agent_env.file_repo.file_save(file)
    agent_env.page_repo.save_pages(file.file_id, [PageText(1, "표지"), PageText(2, "무게 1.5kg " + "가" * 600)])
    return file.file_id


def test_sources_are_pages_read_in_run(agent_env, guide):
    from agent import agent as agent_module

    agent_env.install([
        tool_call("read_pages", {"file_id": guide, "pages": [2]}),
        AIMessage(content="1.5kg입니다."),
    ])

    out = agent_module.run_agent("무게?", mode="local")

    assert len(out["sources"]) == 1
    source = out["sources"][0]
    assert (source["source"], source["page"], source["origin_type"], source["cited"]) == ("N5800_Guide.pdf", 2, "file_page", False)
    assert len(source["text"]) == 500
    assert source["evidence_id"].startswith("e") and out["run_id"].startswith("r")


def test_search_hits_alone_are_not_sources(agent_env, monkeypatch):
    """검색 결과(청크)는 읽은 근거가 아니다. 그래프 결과도 출처에 넣지 않는다."""
    from types import SimpleNamespace

    from agent import agent as agent_module

    monkeypatch.setattr(tools, "get_embedding_model", lambda: SimpleNamespace(embed_query=lambda q: [0.0]))
    monkeypatch.setattr(tools, "search", lambda **kw: [
        {"id": "c", "file_id": "f", "group_id": None, "source": "a.pdf", "page": 1, "chunk_index": 0, "text": "t", "score": 0.9},
    ])
    agent_env.install([tool_call("search_documents", {"query": "x"}), AIMessage(content="답")])

    assert agent_module.run_agent("x", mode="local")["sources"] == []


def test_cited_evidence_takes_priority(agent_env, guide):
    from agent import agent as agent_module

    agent_env.install([tool_call("read_pages", {"file_id": guide, "pages": [1, 2]}), AIMessage(content="답")])
    out = agent_module.run_agent("무게?", mode="local")
    run_id = out["run_id"]
    page2 = next(s["evidence_id"] for s in out["sources"] if s["page"] == 2)
    agent_env.evidence_repo.record_use(run_id, page2, "cite")

    cited = agent_module.evidence_sources(run_id)

    assert [(s["evidence_id"], s["cited"]) for s in cited] == [(page2, True)]


def test_list_evidence_shows_owner_rows_only(agent_env, guide):
    agent_env.evidence_repo.register("task", "t2", "chunk", "남의 근거", file_id="x", page=1)
    run_id = agent_env.evidence_repo.start_run("task", "t1", "test", None)
    with owner_scope(Owner("task", "t1")), run_scope(run_id):
        read = tools.read_pages.invoke({"file_id": guide, "pages": [2]})
        listing = tools.list_evidence.invoke({})

    lines = listing.splitlines()
    assert len(lines) == 1
    assert lines[0].startswith(f"{read['pages'][0]['evidence_id']} | N5800_Guide.pdf p2 | file_page | rev ")
    assert lines[0].endswith("| 무게 1.5kg " + "가" * 51)  # 앞 60자


def test_mail_draft_keeps_evidence_id_and_cited(agent_env):
    """save_draft는 evidence_id를 chunk_id 자리에 넣고 cited를 저장한다."""
    from datetime import datetime

    from entity.type import MailEntity

    mail = MailEntity(uid="m1", subject="s", sender="a@b.c", body="q", received_at=datetime.now())
    with agent_env.db.transaction() as conn:
        agent_env.email_repo.save_pending(mail, conn)
        task_id = agent_env.task_repo.create_task("m1", conn).task_id

    agent_env.task_repo.save_draft(task_id, "답", [
        {"evidence_id": "e1", "file_id": "f", "source": "a.pdf", "page": 2, "text": "본문", "cited": True},
        {"evidence_id": "e1", "file_id": "f", "source": "a.pdf", "page": 2, "text": "본문", "cited": True},
    ])

    assert [(s["chunk_id"], s["cited"]) for s in agent_env.task_repo.get_sources(task_id)] == [("e1", 1)]


def test_tool_list_exposes_evidence_tools():
    from agent import agent as agent_module

    names = [t.name for t in agent_module.TOOLS]
    assert {"read_pages", "read_attachment", "list_evidence", "grep_documents", "list_documents"} <= set(names)
    assert "read_source_document" not in names
    assert json.dumps(names)  # 직렬화 가능한 이름 목록
