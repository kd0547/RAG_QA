"""사용자 질문 -> LangGraph RAG 에이전트 컨트롤러."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agent.rag_agent import get_graph
from typing import Literal

router = APIRouter()


class QuestionRequest(BaseModel):
    question: str
    mode: Literal['claude', 'local'] = 'claude'
    rerank_top_n:int
    query_top_n:int

@router.post("/ask")
async def ask_question(payload: QuestionRequest) -> dict:
    question = payload.question.strip()
    mode = payload.mode
    query_top_n =  payload.query_top_n
    rerank_top_n = payload.rerank_top_n
    if not question:
        raise HTTPException(status_code=400, detail="질문을 입력해주세요.")

    try:
        graph = get_graph()
        state = await graph.ainvoke(
            {
                "query_top_n":query_top_n,
                "rerank_top_n":rerank_top_n,
                "mode": mode,
                "content": question,
                "search_results": [],
                "is_relevant": False,
                "final_answer": "",
                "retry_count": 0,
            }
        )
    except RuntimeError as exc:  # 임베딩/LLM 모델이 아직 주입되지 않은 경우
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    sources = [
        {"source": doc["source"], "page": doc["page"], "text": doc["text"]}
        for doc in state.get("search_results", [])
    ]

    return {
        "question": question,
        "answer": state.get("final_answer", ""),
        "sources": sources,
    }
