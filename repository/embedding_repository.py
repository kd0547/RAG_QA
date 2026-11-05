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
                {
                    "file_id": c.file_id,
                    "source": c.source,
                    "page": c.page,
                    "chunk_index": c.chunk_index,
                    # Chroma는 메타데이터 값으로 None을 받지 않는다. 미분류는 빈 문자열이다.
                    "group_id": c.group_id or "",
                }
                for c in chunks
            ],
        )
    return DATA_DIR

def delete_embeddings(file_id: str) -> None:
    """파일 하나의 임베딩 청크를 모두 삭제한다. 없으면 아무것도 하지 않는다."""
    _collection.delete(where={"file_id": file_id})


def update_group_metadata(file_id: str, group_id: str | None) -> int:
    """파일의 모든 청크에 group_id 메타데이터를 다시 쓴다. 바꾼 청크 수를 돌려준다.

    Chroma update는 넘긴 키만 덮어쓰고 나머지 메타데이터는 유지한다.
    그룹 변경은 SQLite(file.group_id)와 여기 둘 다 바꿔야 검색 필터가 맞는다.
    """
    ids = _collection.get(where={"file_id": file_id}, include=[])["ids"]
    if not ids:
        return 0
    _collection.update(ids=ids, metadatas=[{"group_id": group_id or ""}] * len(ids))
    return len(ids)


def replace_page_embeddings(file_id: str, page: int, chunks: list[EmbeddedChunk]) -> int:
    """파일의 한 페이지 청크를 새 청크로 갈아끼운다. 지운 옛 청크 수를 돌려준다.

    파일 검수에서 페이지 텍스트를 고친 뒤 부른다. 임베딩은 호출 전에 다 만들어 두어야
    임베딩 실패로 페이지 청크만 사라지는 일이 없다.
    """
    where = {"$and": [{"file_id": file_id}, {"page": page}]}
    old_ids = _collection.get(where=where, include=[])["ids"]
    if old_ids:
        _collection.delete(ids=old_ids)
    save_embeddings(chunks)
    return len(old_ids)


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
        candidate_k: int = 10,
        group_id: str | None = None,
) -> list[dict]:
    """쿼리 임베딩과 가장 유사한 청크를 top_k개 반환한다 (거리 오름차순).

    group_id를 주면 그 문서 그룹(entity/group.py)의 청크만 본다. 그룹 지정 전에 올린 청크는
    메타데이터에 group_id가 없어서 필터에 걸리지 않는다. 그룹을 바꾸면 update_group_metadata()가 채운다.
    """

    # metadata 검색 조건
    conditions = []

    if file_id:
        conditions.append({"file_id": file_id})

    if group_id:
        conditions.append({"group_id": group_id})

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
            "group_id": metadata.get("group_id") or None,
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
