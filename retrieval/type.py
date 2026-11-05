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
    group_id: str | None = None   # 문서 그룹(entity/group.py). 검색 범위 필터용으로 Chroma 메타데이터에 들어간다



@dataclass(kw_only=True)
class EmbeddedChunk(Chunk):
    """임베딩 벡터가 채워진 Chunk. 필드는 Chunk를 그대로 상속하고 embedding만 추가한다."""
    embedding: list[float]
