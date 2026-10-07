from dataclasses import dataclass


@dataclass(kw_only=True)
class Chunk:
    id: str
    source: str
    page: int
    chunk_index: int
    text: str
    chunk_type: str = "text"
    file_id: str | None



@dataclass(kw_only=True)
class EmbeddedChunk(Chunk):
    """임베딩 벡터가 채워진 Chunk. 필드는 Chunk를 그대로 상속하고 embedding만 추가한다."""
    embedding: list[float]
