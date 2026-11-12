"""A2: 에이전트 출처 수집. 검색·리랭크에 같은 청크가 나와도 한 번만, 그래프 결과는 페이지마다 한 건."""
import json

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent import agent as agent_module

CHUNK = {
    "id": "f1-p3-c0", "file_id": "f1", "group_id": None, "source": "/data/uploads/guide.pdf",
    "page": 3, "chunk_index": 0, "text": "N5800 무게 1.5kg", "score": 0.8,
}


def _tool(name: str, content) -> ToolMessage:
    return ToolMessage(content=json.dumps(content, ensure_ascii=False), name=name, tool_call_id=f"call-{name}")


def test_search_and_rerank_same_chunk_counted_once():
    messages = [
        HumanMessage("N5800 무게"),
        _tool("search_documents", [CHUNK]),
        _tool("rerank_documents", [CHUNK]),
        AIMessage("1.5kg입니다."),
    ]

    sources = agent_module._collect_sources(messages)

    assert sources == [CHUNK]


def test_single_search_result_gives_one_source():
    assert len(agent_module._collect_sources([_tool("search_documents", [CHUNK])])) == 1


def test_graph_documents_become_one_source_per_page():
    graph = {
        "matched": [{"id": 1, "type": "product", "name": "N5800"}],
        "documents": [
            {"file_id": "f9", "source": "/data/uploads/kc.pdf", "original_name": "kc.pdf",
             "pages": [1, 2], "entities": ["N5800", "적합성 등록"]},
        ],
    }

    sources = agent_module._collect_sources([_tool("graph_search", graph), _tool("graph_search", graph)])

    assert sources == [
        {"id": "graph:f9:1", "file_id": "f9", "source": "kc.pdf", "page": 1,
         "text": "개체: N5800, 적합성 등록", "score": None},
        {"id": "graph:f9:2", "file_id": "f9", "source": "kc.pdf", "page": 2,
         "text": "개체: N5800, 적합성 등록", "score": None},
    ]


def test_graph_without_match_adds_nothing():
    no_match = {"matched": [], "documents": [], "message": "그래프에서 찾지 못했습니다"}
    assert agent_module._collect_sources([_tool("graph_search", no_match)]) == []


def test_run_agent_uses_collect_sources(monkeypatch):
    """run_agent도 같은 수집 함수를 쓴다 (예전 인라인 수집은 같은 청크를 두 번 넣었다)."""
    result = {"messages": [
        HumanMessage("질문"),
        _tool("search_documents", [CHUNK]),
        AIMessage("답변"),
    ]}
    monkeypatch.setattr(agent_module, "get_agent", lambda mode: object())
    monkeypatch.setattr(agent_module, "_invoke_logged", lambda agent, messages, mode, label: result)

    out = agent_module.run_agent("질문", mode="local")

    assert out == {"answer": "답변", "sources": [CHUNK]}
