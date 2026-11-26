"""질문 답변(에이전트 실행)이 도는 동안에도 서버가 다른 요청에 답한다.

/ask·/ask/attachments는 async 함수라 동기 에이전트 실행을 바로 부르면 이벤트 루프가 멈춰 서버 전체가 기다렸다.
에이전트 실행을 스레드풀로 넘겼는지, 느린 질문이 도는 중에 다른 요청이 먼저 끝나는지로 확인한다.
"""
import asyncio
import time

import httpx
from fastapi import FastAPI

from app.routers import questions

SLOW_SECONDS = 1.0


def _slow_answer(*args, **kwargs):
    time.sleep(SLOW_SECONDS)  # LLM 호출을 흉내 낸 동기 대기
    return {"answer": "답", "sources": [], "validation": {"ok": True, "errors": [], "warnings": [], "cited_ids": []}}


def _app(monkeypatch) -> FastAPI:
    monkeypatch.setattr(questions, "run_agent", _slow_answer)
    monkeypatch.setattr(questions, "run_agent_temp_attachments", _slow_answer)
    monkeypatch.setattr(questions.qa_log, "record_answer", lambda *a, **k: None)
    app = FastAPI()
    app.include_router(questions.router)

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    return app


async def _ping_finishes_first(app: FastAPI, slow_request) -> tuple[float, float]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        started = time.perf_counter()

        async def slow():
            response = await slow_request(client)
            assert response.status_code == 200, response.text
            return time.perf_counter() - started

        async def ping():
            await asyncio.sleep(0.1)  # 질문이 먼저 시작되게
            response = await client.get("/ping")
            assert response.status_code == 200
            return time.perf_counter() - started

        return tuple(await asyncio.gather(slow(), ping()))


def test_ask_does_not_block_other_requests(monkeypatch):
    app = _app(monkeypatch)
    slow_done, ping_done = asyncio.run(_ping_finishes_first(
        app, lambda c: c.post("/ask", json={"question": "N5800 무게"})))
    assert slow_done >= SLOW_SECONDS
    assert ping_done < SLOW_SECONDS / 2  # 이벤트 루프가 막혔다면 질문이 끝난 뒤에야 답한다


def test_ask_with_attachments_does_not_block_other_requests(monkeypatch):
    app = _app(monkeypatch)
    slow_done, ping_done = asyncio.run(_ping_finishes_first(
        app, lambda c: c.post("/ask/attachments", data={"question": "첨부 질문", "mode": "local"})))
    assert slow_done >= SLOW_SECONDS
    assert ping_done < SLOW_SECONDS / 2
