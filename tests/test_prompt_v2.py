"""B7: 프롬프트 v2(근거 ID)와 설정값."""
import inspect

from agent.prompt import PROMPT_V2_NAME, PROMPT_V2_TEMPLATE, render_prompt


def test_v2_template_content():
    text = PROMPT_V2_TEMPLATE.template
    for tool_name in ("graph_search", "list_documents", "grep_documents", "search_documents",
                      "rerank_documents", "read_pages", "read_attachment", "list_evidence"):
        assert tool_name in text
    assert "근거: 없음" in text and "`근거: e" in text
    # 절차 번호·횟수 제한·없어진 도구는 쓰지 않는다
    for removed in ("check_answerability", "read_source_document", "start=0", "최대 2회", "\n1. "):
        assert removed not in text
    rendered = render_prompt(text)
    # 옛 본문의 별칭 줄·상위 개념 문장은 렌더링 때 지운다 (GR1). DB에 저장된 본문은 그대로다
    assert "$aliases" in text and "용어 별칭" in text
    for removed in ("$aliases", "용어 별칭", "상위 개념"):
        assert removed not in rendered
    assert "인증 묶음 이름(예: KC 인증)은 시스템이 속한 종류로 펼쳐 주지 않는다" in rendered


def test_ensure_v2_inserts_once_and_keeps_existing(agent_env):
    repo = agent_env.prompt_repo
    default = repo.ensure_default()
    old_content = repo.get(default.id).content

    created = repo.ensure_v2()

    assert created is not None and created.name == PROMPT_V2_NAME and created.is_selected
    assert repo.get(default.id).content == old_content  # 기본 프롬프트는 덮어쓰지 않는다
    assert repo.get_system_prompt() == PROMPT_V2_TEMPLATE.template

    # 담당자가 다른 프롬프트를 고르면 서버를 다시 켜도(ensure_* 재호출) 그 선택이 유지된다
    repo.select(default.id)
    repo.ensure_default()
    assert repo.ensure_v2() is None
    assert repo.get_selected().id == default.id
    assert [p.name for p in repo.list_all()].count(PROMPT_V2_NAME) == 1


def test_tool_defaults_come_from_config():
    import config
    from tools import tool as tools

    search_default = inspect.signature(tools.search_documents.func).parameters["top_k"].default
    rerank_default = inspect.signature(tools.rerank_documents.func).parameters["top_n"].default
    assert (config.SEARCH_TOP_K, config.RERANK_TOP_N) == (5, 3)
    assert (search_default, rerank_default) == (config.SEARCH_TOP_K, config.RERANK_TOP_N)


def test_ask_accepts_request_without_top_n(monkeypatch):
    """화면이 query_top_n·rerank_top_n을 안 보내도(또는 보내도) 받는다. 값은 쓰지 않는다."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.routers import questions

    calls = []
    monkeypatch.setattr(questions, "run_agent", lambda message, mode: calls.append(message) or {
        "answer": "답", "sources": [], "validation": {"ok": True, "errors": [], "warnings": [], "cited_ids": []},
    })
    app = FastAPI()
    app.include_router(questions.router)
    client = TestClient(app)

    plain = client.post("/ask", json={"question": "N5800 무게"})
    legacy = client.post("/ask", json={"question": "N5800 무게", "query_top_n": 9, "rerank_top_n": 7})

    assert plain.status_code == legacy.status_code == 200
    assert calls == ["N5800 무게", "N5800 무게"]
    assert plain.json()["validation"]["ok"] is True
