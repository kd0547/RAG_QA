"""B7: 검색 설정값과 /ask 요청 (프롬프트 v2 본문은 2026-11-26에 지웠다)."""
import inspect


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
