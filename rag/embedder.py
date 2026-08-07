"""임베딩 인터페이스.

실제 모델 로딩(models/ 에서 로드)은 이 모듈이 아니라 서버 부트스트랩 단계에서
`set_embedding_model()`을 통해 주입한다. 이 파일은 청크 -> 임베딩 벡터 변환의
얇은 뼈대만 제공한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from rag.ingest import Chunk


class EmbeddingModel(Protocol):


    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


_embedding_model: EmbeddingModel | None = None


def set_embedding_model(model: EmbeddingModel) -> None:
    """서버 시작 시 로드한 임베딩 모델을 주입한다."""
    global _embedding_model
    _embedding_model = model


def get_embedding_model() -> EmbeddingModel:
    if _embedding_model is None:
        raise RuntimeError(
            "임베딩 모델이 아직 로드되지 않았습니다. "
            "서버 시작 시 set_embedding_model()로 모델을 주입해주세요."
        )
    return _embedding_model


@dataclass
class EmbeddedChunk:
    id: str
    source: str
    page: int
    chunk_index: int
    text: str
    embedding: list[float]


def embed_chunks(chunks: list[Chunk]) -> list[EmbeddedChunk]:
    """청크 리스트를 임베딩 벡터와 함께 EmbeddedChunk 리스트로 변환한다."""
    if not chunks:
        return []

    model = get_embedding_model()
    vectors = model.embed_documents([c.text for c in chunks])

    return [
        EmbeddedChunk(
            id=c.id,
            source=c.source,
            page=c.page,
            chunk_index=c.chunk_index,
            text=c.text,
            embedding=vector,
        )
        for c, vector in zip(chunks, vectors)
    ]


def embed_query(text: str) -> list[float]:
    """검색어 한 문장을 임베딩 벡터로 변환한다."""
    model = get_embedding_model()
    return model.embed_query(text)
