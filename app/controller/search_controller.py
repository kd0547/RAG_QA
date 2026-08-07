"""쿼리 -> 임베딩 -> 저장소 유사도 검색 컨트롤러."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from rag.embedder import embed_query
from repository.embedding_repository import search

router = APIRouter()


@router.get("/search")
def search_chunks(
    q: str = Query(..., min_length=1, description="검색어"),
    top_k: int = Query(5, ge=1, le=50, description="반환할 청크 수"),
    doc_id: str | None = Query(None, description="특정 문서로만 검색 범위 제한"),

) -> dict:
    try:
        query_embedding = embed_query(q)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    results = search(query_embedding, top_k=top_k, doc_id=doc_id)
    return {"query": q, "results": results}
