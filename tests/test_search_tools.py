"""B3: search_documents는 스니펫과 근거 ID만, rerank_documents·check_answerability는 근거 ID를 받는다."""
import logging
from types import SimpleNamespace

import pytest

from agent import reranker
from agent.evidence_context import Owner, owner_scope, run_scope
from tools import tool as tools

LONG = "N5800 사양 " + "가" * 400


@pytest.fixture
def in_run(agent_env):
    run_id = agent_env.evidence_repo.start_run("task", "t1", "test", None)
    with owner_scope(Owner("task", "t1")), run_scope(run_id):
        yield run_id


@pytest.fixture
def vector_hits(monkeypatch):
    """임베딩·벡터DB 대역: 정해 둔 청크를 돌려준다."""
    hits = [
        {"id": "f1-p2-c0", "file_id": "f1", "group_id": None, "source": "C:\\data\\uploads\\guide.pdf",
         "page": 2, "chunk_index": 0, "text": LONG, "score": 0.8},
        {"id": "f1-p3-c0", "file_id": "f1", "group_id": None, "source": "/app/data/uploads/guide.pdf",
         "page": 3, "chunk_index": 0, "text": "KC 인증", "score": 0.5},
    ]
    monkeypatch.setattr(tools, "get_embedding_model", lambda: SimpleNamespace(embed_query=lambda q: [0.0]))
    monkeypatch.setattr(tools, "search", lambda **kwargs: hits)
    return hits


def test_search_returns_snippet_and_evidence_id(agent_env, vector_hits, in_run):
    results = tools.search_documents.invoke({"query": "N5800"})

    assert [r["source"] for r in results] == ["guide.pdf", "guide.pdf"]
    assert all("text" not in r for r in results)
    assert len(results[0]["snippet"]) == 300
    stored = agent_env.evidence_repo.get(results[0]["evidence_id"], "task", "t1")
    assert stored["text"] == LONG and stored["origin_type"] == "chunk" and stored["page"] == 2
    # 같은 검색을 다시 해도 같은 근거 ID
    assert tools.search_documents.invoke({"query": "N5800"})[0]["evidence_id"] == results[0]["evidence_id"]


def test_rerank_without_model_keeps_input_order(agent_env, vector_hits, in_run, monkeypatch):
    monkeypatch.setattr(reranker, "model", None)
    ids = [r["evidence_id"] for r in tools.search_documents.invoke({"query": "N5800"})]

    ranked = tools.rerank_documents.invoke({"query": "KC", "evidence_ids": list(reversed(ids)), "top_n": 5})

    assert ranked == list(reversed(ids))
    assert [u["evidence_id"] for u in agent_env.evidence_repo.uses_for_run(in_run, "rerank")] == ranked


def test_rerank_with_model_sorts_by_score(agent_env, vector_hits, in_run, monkeypatch):
    class CrossEncoder:
        def predict(self, pairs):
            return [1.0 if "KC" in text else 0.1 for _, text in pairs]

    monkeypatch.setattr(reranker, "model", CrossEncoder())
    ids = [r["evidence_id"] for r in tools.search_documents.invoke({"query": "N5800"})]

    assert tools.rerank_documents.invoke({"query": "KC", "evidence_ids": ids, "top_n": 1}) == [ids[1]]


def test_other_owner_ids_are_ignored_with_warning(agent_env, vector_hits, in_run, monkeypatch, caplog):
    monkeypatch.setattr(reranker, "model", None)
    mine = tools.search_documents.invoke({"query": "N5800"})[0]["evidence_id"]
    theirs = agent_env.evidence_repo.register("task", "t2", "chunk", "남의 근거", file_id="f9", page=1)

    with caplog.at_level(logging.WARNING, logger="tools.tool"):
        ranked = tools.rerank_documents.invoke({"query": "x", "evidence_ids": [theirs, mine, "e-unknown"]})

    assert ranked == [mine]
    assert theirs in caplog.text and "무시" in caplog.text


def test_check_answerability_reads_text_by_id(agent_env, vector_hits, in_run, monkeypatch):
    seen = []

    class Judge:
        def with_structured_output(self, schema):
            return self

        def invoke(self, input):
            seen.append(input[1]["content"])
            return SimpleNamespace(is_answerable=True, reason="있음")

    monkeypatch.setattr(tools, "get_llm_model", lambda mode: Judge())
    mine = tools.search_documents.invoke({"query": "N5800"})[1]["evidence_id"]
    theirs = agent_env.evidence_repo.register("task", "t2", "chunk", "남의 비밀", file_id="f9", page=1)

    result = tools.check_answerability.invoke({"question": "KC?", "evidence_ids": [mine, theirs]})

    assert result["is_answerable"] is True
    assert "KC 인증" in seen[0] and "남의 비밀" not in seen[0]
    assert tools.check_answerability.invoke({"question": "KC?", "evidence_ids": [theirs]})["is_answerable"] is False
