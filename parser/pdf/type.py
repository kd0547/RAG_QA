from dataclasses import dataclass
from pydantic import BaseModel, field_validator
from typing import Any
from PIL import Image
from typing import Optional

@dataclass
class PageText:
    page: int  # 1-based 페이지 번호
    text: str

@dataclass
class PageImage:
    page:int
    img: Image.Image

class Span(BaseModel):
    size: float
    flags: int
    char_flags: int = 0
    bidi: int = 0
    font: str
    color: int
    alpha: int = 255
    ascender: float | None = None
    descender: float | None = None
    text: str
    origin: list[float]          # [x, y]
    bbox: list[float]            # [x0, y0, x1, y1]
    # 공백 전용 span 등에는 아래가 없을 수 있어 Optional
    line: int | None = None
    block: int | None = None
    dir: list[float] | None = None


class TextLine(BaseModel):
    bbox: list[float]
    spans: list[Span] = []


class Box(BaseModel):
    """레이아웃 탐지 박스 (헤더/본문/그림/푸터 등)."""
    image_description: Optional[str] = None  #이미지 저장용

    x0: float
    y0: float
    x1: float
    y1: float
    boxclass: str               # 'page-header' | 'text' | 'picture' | 'page-footer' | 'table' ...
    image: Any | None = None
    table: Any | None = None
    max_fontsize: float | None = None
    header_level: int = 0
    textlines: Optional[list[TextLine]] = None

    @field_validator("textlines",mode='before')
    @classmethod
    def default_textlines(cls,v):
        return v if v is not None else []



class FullTextLine(BaseModel):
    spans: list[Span] = []
    wmode: int = 0
    dir: list[float] | None = None
    bbox: list[float]


class FullTextBlock(BaseModel):
    """PyMuPDF page.get_text('dict')의 block 하나."""
    type: int                   # 0=text, 1=image
    number: int
    flags: int = 0
    bbox: list[float]
    lines: list[FullTextLine] = []


class Page(BaseModel):
    page_number: int
    width: float
    height: float
    boxes: list[Box] = []
    full_ocred: bool = False
    fulltext: list[FullTextBlock] = []
    words: list[Any] = []
    links: list[Any] = []


class PdfMetadata(BaseModel):
    """PDF 문서 메타데이터 (pymupdf 기준)."""
    format: str | None = None
    title: str | None = None
    author: str | None = None
    subject: str | None = None
    keywords: str | None = None
    creator: str | None = None
    producer: str | None = None
    creationDate: str | None = None
    modDate: str | None = None
    trapped: str | None = None
    encryption: Any | None = None


class Document(BaseModel):
    """pymupdf4llm.to_json() 결과 전체를 감싸는 최상위 객체."""
    filename: str
    page_count: int
    toc: list[Any] = []          # 목차 (bookmark)
    pages: list[Page] = []
    metadata: PdfMetadata | None = None

    # 렌더링/처리 옵션 (원본 그대로 보존)
    from_bytes: bool = False
    image_dpi: int | None = None
    image_format: str | None = None
    image_path: str = ""
    use_ocr: int = 0
    form_fields: dict[str, Any] = {}
    force_text: bool = True
    embed_images: bool = False
    write_images: bool = False
