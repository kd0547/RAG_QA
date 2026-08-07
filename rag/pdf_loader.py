"""PDF 텍스트 추출 (이미지는 무시하고 텍스트만 처리)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader


@dataclass
class PageText:
    page: int  # 1-based 페이지 번호
    text: str


def load_pdf_text(pdf_path: str | Path) -> list[PageText]:
    """PDF 파일에서 페이지별 텍스트를 추출한다.

    이미지, 표 레이아웃 등은 고려하지 않고 pypdf가 추출하는 텍스트만 사용한다.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF 파일을 찾을 수 없습니다: {pdf_path}")

    reader = PdfReader(str(pdf_path))
    pages: list[PageText] = []
    for i, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        pages.append(PageText(page=i, text=text))
    return pages
