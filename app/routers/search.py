"""쿼리 -> 임베딩 -> 저장소 유사도 검색 라우터."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from retrieval.embedder import embed_query
from repository.embedding_repository import search

router = APIRouter()


@router.get("/search")
def search_chunks(
    q: str = Query(..., min_length=1, description="검색어"),
    top_k: int = Query(5, ge=1, le=50, description="반환할 청크 수"),
    file_id: str | None = Query(None, description="특정 파일로만 검색 범위 제한"),
    group_id: str | None = Query(None, description="문서 그룹(GET /groups의 id)으로만 검색 범위 제한"),
) -> dict:
    try:
        query_embedding = embed_query(q)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    results = search(query_embedding, top_k=top_k, file_id=file_id, group_id=group_id)
    # 임베딩 벡터는 응답에 넣지 않는다 (청크당 1024개 float라 응답만 키운다)
    return {"query": q, "results": [{k: v for k, v in doc.items() if k != "embedding"} for doc in results]}
