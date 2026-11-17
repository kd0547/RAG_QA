"""질의응답 로그(qa_log): 질문마다 한 줄, 평가 붙이기, CSV·JSON 내려받기. 로그 실패가 답변을 막지 않는다."""
import csv
import io

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from repository.evidence_repository import EvidenceRepository
from repository.qa_log_repository import QaLogRepository
from repository.repo_connect import Database


@pytest.fixture
def repos(tmp_path, monkeypatch):
    db = Database(str(tmp_path / "qa.db"))
    qa_repo, evidence = QaLogRepository(db), EvidenceRepository(db)
    from app import qa_log
    from app.routers import questions
    monkeypatch.setattr(qa_log, "qa_log_repo", qa_repo)
    monkeypatch.setattr(qa_log, "evidence_repo", evidence)
    monkeypatch.setattr(questions, "qa_log_repo", qa_repo)
    return qa_repo, evidence


@pytest.fixture
def client():
    from app.routers import questions
    app = FastAPI()
    app.include_router(questions.router)
    return TestClient(app)


def _fake_run(evidence: EvidenceRepository):
    """에이전트 대신: run 행을 하나 만들고(그래프 도구 1번, 문서 검색 2번) 답을 돌려준다."""
    def run(message, mode):
        run_id = evidence.start_run("session", "s1", "local-model", None, label="질문")
        calls = [{"tool": "graph_search"}, {"tool": "search_documents"}, {"tool": "search_documents"}]
        evidence.finish_run(run_id, "ok", calls, 120, 30)
        return {
            "answer": f"{message}의 답", "run_id": run_id,
            "sources": [{"source": "a.pdf", "page": 1, "text": "본문", "evidence_id": "e1", "cited": True},
                        {"source": "b.pdf", "page": 2, "text": "본문2", "evidence_id": "e2", "cited": False}],
            "validation": {"ok": True, "errors": [], "warnings": [], "cited_ids": ["e1"]},
        }
    return run


def test_ask_saves_log_with_run_snapshot(repos, client, monkeypatch):
    qa_repo, evidence = repos
    from app.routers import questions
    monkeypatch.setattr(questions, "run_agent", _fake_run(evidence))

    res = client.post("/ask", json={"question": "N5800 무게", "mode": "local"})

    assert res.status_code == 200
    log_id = res.json()["log_id"]
    log = qa_repo.get(log_id)
    assert log["status"] == "ok" and log["endpoint"] == "ask"
    assert log["question"] == "N5800 무게" and log["answer"] == "N5800 무게의 답"
    assert log["model"] == "local-model" and (log["tokens_in"], log["tokens_out"]) == (120, 30)
    assert [c["tool"] for c in log["tool_calls"]] == ["graph_search", "search_documents", "search_documents"]
    assert len(log["sources"]) == 2 and log["rating"] is None
    assert log["duration_ms"] >= 0


def test_failed_answer_is_logged_and_still_503(repos, client, monkeypatch):
    qa_repo, _ = repos
    from app.routers import questions

    def boom(message, mode):
        raise RuntimeError("모델이 아직 로드되지 않았습니다")
    monkeypatch.setattr(questions, "run_agent", boom)

    res = client.post("/ask", json={"question": "아무 질문"})

    assert res.status_code == 503
    [log] = qa_repo.list_logs()
    assert log["status"] == "error" and "모델이 아직" in log["error"] and log["answer"] is None


def test_log_failure_does_not_block_answer(repos, client, monkeypatch):
    qa_repo, evidence = repos
    from app.routers import questions
    monkeypatch.setattr(questions, "run_agent", _fake_run(evidence))

    def broken(**kwargs):
        raise OSError("디스크 가득")
    monkeypatch.setattr(qa_repo, "insert", broken)

    res = client.post("/ask", json={"question": "질문"})

    assert res.status_code == 200
    assert res.json()["answer"] == "질문의 답" and res.json()["log_id"] is None


def test_feedback_set_change_clear(repos, client, monkeypatch):
    qa_repo, evidence = repos
    from app.routers import questions
    monkeypatch.setattr(questions, "run_agent", _fake_run(evidence))
    log_id = client.post("/ask", json={"question": "질문"}).json()["log_id"]

    assert client.post("/ask/feedback", json={"log_id": log_id, "rating": "bad", "comment": " 값이 틀림 "}).status_code == 200
    log = qa_repo.get(log_id)
    assert (log["rating"], log["comment"]) == ("bad", "값이 틀림") and log["rated_at"]

    client.post("/ask/feedback", json={"log_id": log_id, "rating": "good", "comment": ""})
    assert (qa_repo.get(log_id)["rating"], qa_repo.get(log_id)["comment"]) == ("good", None)

    client.post("/ask/feedback", json={"log_id": log_id, "rating": None, "comment": ""})
    log = qa_repo.get(log_id)
    assert log["rating"] is None and log["rated_at"] is None

    assert client.post("/ask/feedback", json={"log_id": "q없음", "rating": "good"}).status_code == 404
    assert client.post("/ask/feedback", json={"log_id": log_id, "rating": "meh"}).status_code == 422


def test_logs_filter_and_csv(repos, client, monkeypatch):
    qa_repo, evidence = repos
    from app.routers import questions
    monkeypatch.setattr(questions, "run_agent", _fake_run(evidence))
    first = client.post("/ask", json={"question": "첫 질문"}).json()["log_id"]
    client.post("/ask", json={"question": "둘째 질문"})
    client.post("/ask/feedback", json={"log_id": first, "rating": "bad", "comment": "근거 빠짐"})

    rated = client.get("/ask/logs", params={"rating": "rated"}).json()
    assert rated["count"] == 1 and rated["logs"][0]["log_id"] == first
    assert client.get("/ask/logs").json()["count"] == 2

    res = client.get("/ask/logs", params={"format": "csv"})
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/csv")
    assert "attachment" in res.headers["content-disposition"]
    text = res.content.decode("utf-8")
    assert text.startswith("﻿")
    rows = list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))
    assert [r["질문"] for r in rows] == ["첫 질문", "둘째 질문"]
    assert rows[0]["평가"] == "아쉬움" and rows[0]["의견"] == "근거 빠짐"
    assert (rows[0]["도구 호출 수"], rows[0]["그래프 도구 호출 수"]) == ("3", "1")
    assert (rows[0]["인용 출처 수"], rows[0]["읽은 출처 수"]) == ("1", "2")
    assert rows[0]["도구 호출"] == "search_documents×2, graph_search×1"


def test_attachment_question_logs_attachment_names(repos, client, monkeypatch):
    qa_repo, evidence = repos
    from app.routers import questions
    fake = _fake_run(evidence)
    monkeypatch.setattr(questions, "run_agent_temp_attachments", lambda q, mode, attachments: fake(q, mode))

    res = client.post(
        "/ask/attachments", data={"question": "이 사양서 확인", "mode": "local"},
        files=[("files", ("spec.png", b"\x89PNG\r\n\x1a\nfake", "image/png"))],
    )

    assert res.status_code == 200
    log = qa_repo.get(res.json()["log_id"])
    assert log["endpoint"] == "ask_attachments"
    assert log["attachments"] == [{"filename": "spec.png", "type": "image"}]
