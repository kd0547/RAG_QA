"""사용자 질문 -> LangGraph RAG 에이전트 컨트롤러."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agent.rag_agent import get_agent
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
    query_top_n = payload.query_top_n
    rerank_top_n = payload.rerank_top_n
    if not question:
        raise HTTPException(status_code=400, detail="질문을 입력해주세요.")

    user_message = question
    if query_top_n or rerank_top_n:
        user_message += (
            f"\n\n(참고: 검색 시 top_k는 {query_top_n or 5}, "
            f"리랭킹 시 top_n은 {rerank_top_n or 3}을 기본값으로 사용하세요.)"
        )

    try:
        agent = get_agent(mode)
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": user_message}]},
            config={"recursion_limit": 15},
        )
    except RuntimeError as exc:  # 임베딩/LLM 모델이 아직 주입되지 않은 경우
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    final_message = result["messages"][-1]

    docs = []
    for msg in result["messages"]:
        if getattr(msg, "name", None) in ("search_documents", "rerank_documents"):
            if isinstance(msg.content, list):
                docs.extend(msg.content)

    sources = [
        {"source": doc["source"], "page": doc["page"], "text": doc["text"]}
        for doc in docs
    ]

    return {
        "question": question,
        "answer": final_message.content,
        "sources": sources,
    }