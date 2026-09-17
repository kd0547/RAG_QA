"""텍스트 기본 청킹 (문자 수 기준 슬라이딩 윈도우)."""
from __future__ import annotations


def chunk_text(
    text: str,
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
) -> list[str]:
    """문자 수 기준으로 텍스트를 청크로 나눈다.

    가능하면 공백/줄바꿈 경계에서 자르되, 경계를 못 찾으면 chunk_size 위치에서 그대로 자른다.
    """
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap은 chunk_size보다 작아야 합니다")

    text = text.strip()
    if not text:
        return []

    chunks: list[str] = []
    start = 0
    text_len = len(text)
    min_advance = max(chunk_size // 4, 1)

    while start < text_len:
        end = min(start + chunk_size, text_len)

        if end < text_len:
            boundary = text.rfind("\n\n", start, end)

            if boundary == -1:
                boundary = text.rfind("\n", start, end)
            if boundary == -1:
                boundary = text.rfind(" ", start, end)
            if boundary != -1 and boundary > start:
                end = boundary

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        if end >= text_len:
            break
        next_start = max(end - chunk_overlap, start + min_advance)

        # 겹침을 적용하되, 항상 앞으로 진행하도록 보장한다 (무한 루프 방지)
        start = next_start

    return chunks
