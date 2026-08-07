"""PDF -> 텍스트 추출 -> 청킹 파이프라인."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path

from rag.chunker import chunk_text
from rag.pdf_loader import load_pdf_text


@dataclass
class Chunk:
    id: str
    source: str
    page: int
    chunk_index: int
    text: str


def ingest_pdf(
    pdf_path: str | Path,
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
) -> list[Chunk]:
    """PDF를 읽어 페이지별 텍스트를 추출하고 청크 리스트로 변환한다."""
    pdf_path = Path(pdf_path)
    pages = load_pdf_text(pdf_path)

    chunks: list[Chunk] = []
    for page in pages:
        page_chunks = chunk_text(page.text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        for i, chunk in enumerate(page_chunks):
            chunks.append(
                Chunk(
                    id=f"{pdf_path.stem}-p{page.page}-c{i}",
                    source=pdf_path.name,
                    page=page.page,
                    chunk_index=i,
                    text=chunk,
                )
            )
    return chunks


def chunks_to_dicts(chunks: list[Chunk]) -> list[dict]:
    return [asdict(c) for c in chunks]
