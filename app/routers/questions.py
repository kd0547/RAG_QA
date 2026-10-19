"""사용자 질문 -> LangGraph RAG 에이전트 라우터."""
from __future__ import annotations

import logging
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agent.agent import get_agent
from typing import Literal

logger = logging.getLogger(__name__)

router = APIRouter()


class QuestionRequest(BaseModel):
    question: str
    mode: Literal['claude', 'local'] = 'local'
    rerank_top_n:int
    query_top_n:int

from agent.agent import run_agent

@router.post("/ask")
async def ask_question(payload: QuestionRequest) -> dict:
    question = payload.question.strip()
    mode = payload.mode
    query_top_n = payload.query_top_n
    rerank_top_n = payload.rerank_top_n
    if not question:
        raise HTTPException(status_code=400, detail="질문을 입력해주세요.")

    user_message = question
    #if query_top_n or rerank_top_n:
    #    user_message += (
    #        f"\n\n(참고: 검색 시 top_k는 {query_top_n or 5}, "
    #        f"리랭킹 시 top_n은 {rerank_top_n or 3}을 기본값으로 사용하세요.)"
    #    )

    started = time.perf_counter()
    logger.debug("질문 수신: mode=%s, question=%s", mode, question[:200])
    try:
        result = run_agent(user_message, mode)
    except RuntimeError as exc:
        # 모델 미로드 등. 클라이언트에는 503만 가므로 원인을 남긴다
        logger.warning("질문 처리 불가(503): mode=%s, %s", mode, exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    sources = [
        {"source": doc["source"], "page": doc["page"], "text": doc["text"]}
        for doc in result["sources"]
    ]

    logger.info(
        "질문 응답 완료: mode=%s, question_len=%d, answer_len=%d, sources=%d, %.1f초",
        mode, len(question), len(str(result["answer"])), len(sources), time.perf_counter() - started,
    )

    return {
        "question": question,
        "answer": result["answer"],
        "sources": sources,
    }