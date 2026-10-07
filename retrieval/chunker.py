"""텍스트 청킹 (마크다운 헤더 기준 + 고정 간격) + 페이지 텍스트 -> Chunk 변환."""
from __future__ import annotations

import re
from pathlib import Path

from config import DEFAULT_CHUNK_OVERLAP, DEFAULT_CHUNK_SIZE
from parser.pdf.type import PageText
from retrieval.type import Chunk

HEADER_PATTERN = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)


def _split_fixed_interval(text: str, size: int = DEFAULT_CHUNK_SIZE, overlap: int = DEFAULT_CHUNK_OVERLAP) -> list[str]:
    """텍스트를 일정한 간격(size 글자)으로 자르되, 앞 청크의 끝 overlap 글자를 다음 청크에 겹친다."""
    text = text.strip()
    if not text:
        return []
    # overlap이 size 이상이면 앞으로 나아갈 수 없으므로, 에러 대신 size의 절반으로 줄여서 자른다.
    if overlap >= size:
        overlap = size // 2

    step = max(size - overlap, 1)
    chunks = []
    for start in range(0, len(text), step):
        chunk = text[start:start + size].strip()
        if chunk:
            chunks.append(chunk)
        if start + size >= len(text):
            break
    return chunks


def _split_by_headers(text: str, size: int = DEFAULT_CHUNK_SIZE, overlap: int = DEFAULT_CHUNK_OVERLAP) -> list[str]:
    """#, ##, ### 헤더 기준으로 구간을 나누고, 각 청크 앞에 상위 헤더 경로를 붙인다.
    구간이 size보다 길면 고정 간격으로 한 번 더 나눈다."""
    matches = list(HEADER_PATTERN.finditer(text))
    sections = []

    # 첫 헤더 이전 내용(서문)
    intro = text[:matches[0].start()].strip() if matches else ""
    if intro:
        sections.extend(_split_fixed_interval(intro, size, overlap))

    path: dict[int, str] = {}  # level -> title
    for i, m in enumerate(matches):
        level = len(m.group(1))
        path[level] = m.group(2).strip()
        for lv in [lv for lv in path if lv > level]:
            del path[lv]

        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[start:end].strip()
        if not content:  # 제목만 있는 구간은 건너뜀
            continue

        header_path = " > ".join(path[lv] for lv in sorted(path))
        for piece in _split_fixed_interval(content, size, overlap):
            sections.append(f"{header_path}\n{piece}")

    return sections


def split_chunks(text: str, size: int = DEFAULT_CHUNK_SIZE, overlap: int = DEFAULT_CHUNK_OVERLAP) -> list[str]:
    """헤더가 있으면 헤더 기준으로, 없으면 고정 간격으로 자른다."""
    if HEADER_PATTERN.search(text):
        return _split_by_headers(text, size, overlap)
    return _split_fixed_interval(text, size, overlap)


def chunk_pages(
    file_path: str | Path,
    pages: list[PageText],
    file_id: str | None = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[Chunk]:
    """파서가 만든 페이지별 텍스트를 청킹해 Chunk 리스트로 변환한다."""
    file_path = Path(file_path)

    chunks: list[Chunk] = []
    for page in pages:
        for i, chunk in enumerate(split_chunks(page.text, size=chunk_size, overlap=chunk_overlap)):
            chunks.append(
                Chunk(
                    id=f"{file_path.stem}-p{page.page}-c{i}",
                    source=str(file_path),
                    page=page.page,
                    chunk_index=i,
                    text=chunk,
                    file_id=file_id,
                )
            )
    return chunks


def dump_chunks_markdown(file_path: str | Path, chunks: list[Chunk]) -> None:
    # 디버깅용: 생성된 청크를 페이지 및 순서와 함께 Markdown으로 보관한다.
    markdown_dir = Path(__file__).resolve().parent.parent / "markdown"
    markdown_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = markdown_dir / f"{Path(file_path).stem}.md"
    markdown_content = "\n\n---\n\n".join(
        f"## Page {chunk.page} · Chunk {chunk.chunk_index + 1}\n\n{chunk.text}"
        for chunk in chunks
    )
    markdown_path.write_text(markdown_content + ("\n" if chunks else ""), encoding="utf-8")
