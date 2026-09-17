"""PDF -> 텍스트 추출 -> 청킹 파이프라인."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from rag.chunker import chunk_text
from rag.pdf_loader import load_pdf_text, pdf_pages, build_page_content
from rag.type import Chunk


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

def ingest_pdf_image(
        pdf_path:str | Path,
        chunk_size: int = 2000,
        chunk_overlap: int = 200,
) -> list[Chunk]:
    pdf_path = Path(pdf_path)
    doc = pdf_pages(pdf_path)

    chunks: list[Chunk] = []
    for page in doc.pages:
        content = build_page_content(page)
        page_chunks = chunk_text(content,chunk_size=chunk_size,chunk_overlap=chunk_overlap)
        for i,chunk in enumerate(page_chunks):
            chunks.append(
                Chunk(
                    id=f"{pdf_path.stem}-p{page.page_number}-c{i}",
                    source=pdf_path.name,
                    page=page.page_number,
                    chunk_index=i,
                    text=chunk,
                )
            )
    return chunks

def chunks_to_dicts(chunks: list[Chunk]) -> list[dict]:
    return [asdict(c) for c in chunks]
