"""임베딩 저장소 (Chroma 기반).

storage/chroma 를 persist 디렉터리로 쓰는 단일 컬렉션에 청크를 저장한다.
문서 구분은 메타데이터의 source(doc_id) 필드로 한다.
"""
from __future__ import annotations

import logging
from pathlib import Path

import chromadb

from retrieval.type import EmbeddedChunk

DATA_DIR = Path(__file__).resolve().parent.parent / "storage" / "chroma"
DATA_DIR.mkdir(parents=True, exist_ok=True)

COLLECTION_NAME = "rag_chunks"

logger = logging.getLogger(__name__)

_client = chromadb.PersistentClient(path=str(DATA_DIR))
_collection = _client.get_or_create_collection(
    name=COLLECTION_NAME,
    configuration={"hnsw": {"space": "cosine"}},
)


def save_embeddings(chunks: list[EmbeddedChunk]) -> Path:
    """문서 하나의 임베딩 청크를 저장한다. 같은 doc_id가 있으면 갈아끼운다."""
    if chunks:
        _collection.add(
            ids=[c.id for c in chunks],
            embeddings=[c.embedding for c in chunks],
            documents=[c.text for c in chunks],
            metadatas=[
                {"file_id": c.file_id, "source": c.source, "page": c.page, "chunk_index": c.chunk_index}
                for c in chunks
            ],
        )
    return DATA_DIR

def delete_embeddings(file_id: str) -> None:
    """파일 하나의 임베딩 청크를 모두 삭제한다. 없으면 아무것도 하지 않는다."""
    _collection.delete(where={"file_id": file_id})


def load_embeddings(doc_id: str) -> list[dict]:
    """문서 하나의 임베딩 청크를 불러온다. 없으면 빈 리스트."""
    result = _collection.get(
        where={"source": doc_id},
        include=["embeddings", "documents", "metadatas"],
    )
    return [
        {
            "id": chunk_id,
            "source": metadata["source"],
            "page": metadata["page"],
            "chunk_index": metadata["chunk_index"],
            "text": document,
            "embedding": list(embedding),
        }
        for chunk_id, embedding, document, metadata in zip(
            result["ids"], result["embeddings"], result["documents"], result["metadatas"]
        )
    ]


def list_documents() -> list[str]:
    """저장된 문서 id(doc_id) 목록을 반환한다."""
    result = _collection.get(include=["metadatas"])
    return sorted({m["source"] for m in result["metadatas"]})


def search(
        query_embedding: list[float],
        top_k: int = 5,
        score_threshold:float = 0.4, #유사도가 너무 낮은 청크 제거
        page = -1,
        file_id: str | None = None,
        candidate_k: int = 30,
) -> list[dict]:
    """쿼리 임베딩과 가장 유사한 청크를 top_k개 반환한다 (거리 오름차순)."""

    # metadata 검색 조건
    conditions = []

    if file_id:
        conditions.append({"file_id": file_id})

    if page >= 0:
        conditions.append({"page": page})

    # Chroma where 생성
    if len(conditions) == 0:
        where = None
    elif len(conditions) == 1:
        where = conditions[0]
    else:
        where = {
            "$and": conditions
        }

    result = _collection.query(
        query_embeddings=[query_embedding],
        n_results=max(top_k, candidate_k),
        where=where,
        include=[
            "embeddings",
            "documents",
            "metadatas",
            "distances",
        ],
    )
    docs = []
    filtered = 0

    for (chunk_id, embedding, document, metadata, distance, ) in zip(
        result["ids"][0],
        result["embeddings"][0],
        result["documents"][0],
        result["metadatas"][0],
        result["distances"][0],
    ):

        score = 1 - distance

        if score < score_threshold:
            # 검색 한 번에 후보가 최대 candidate_k개라 청크별 로그는 DEBUG로만 남긴다
            logger.debug(
                "[FILTERED] id=%s, source=%s, page=%s, distance=%.4f, score=%.4f, threshold=%.4f",
                chunk_id, metadata.get("source"), metadata.get("page"), distance, score, score_threshold,
            )
            filtered += 1
            continue

        docs.append({
            "id": chunk_id,
            "file_id": metadata.get("file_id"),
            "source": metadata.get("source"),
            "page": metadata.get("page"),
            "chunk_index": metadata.get("chunk_index"),
            "text": document,
            "embedding": list(embedding),
            "distance": distance,
            "score": score,
        })

    logger.debug(
        "벡터 검색: 후보 %d건 중 threshold(%.2f) 미만 %d건 제외 -> %d건",
        len(result["ids"][0]), score_threshold, filtered, len(docs),
    )
    return docs
