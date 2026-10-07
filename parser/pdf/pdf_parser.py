import json as _json
import os
import re
from pathlib import Path

from pymupdf4llm import to_json,to_markdown
from pypdf import PdfReader

from ocr.llm_ocr import ocr_image
from parser.pdf.type import Document, Page, PageText

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def parser_pdf_md(
        pdf_path:Path
):

    return to_markdown(pdf_path)


def parser_pdf_pages(pdf_path: str | Path) -> list[PageText]:
    """레이아웃 분석 + 이미지 LLM OCR로 PDF를 페이지별 마크다운 텍스트로 변환한다."""
    document = _load_layout(Path(pdf_path))

    pages: list[PageText] = []
    for page in document.pages:
        _describe_images(page)  # box.image_description 채워짐
        pages.append(PageText(page=page.page_number, text=_render_page(page)))
    return pages


def parser_pdf_plain_pages(pdf_path: str | Path) -> list[PageText]:
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


def _load_layout(pdf_path: Path) -> Document:
    """pymupdf4llm으로 PDF 레이아웃(박스)을 분석하고, 이미지는 data/images/<파일명>/ 에 저장한다."""
    image_dir_name = re.sub(r"[^\w\-가-힣]", "_", pdf_path.stem)
    image_dir_abs = PROJECT_ROOT / "data" / "images" / image_dir_name
    image_dir_abs.mkdir(parents=True, exist_ok=True)

    image_dir_rel = os.path.relpath(image_dir_abs, Path.cwd())

    print(image_dir_abs)
    raw = to_json(
        pdf_path,
        write_images=True,
        image_path=str(image_dir_rel),
        image_format="png",
        dpi=200,
    )
    return Document.model_validate(_json.loads(raw))


def _describe_images(page: Page) -> None:
    """페이지의 picture 박스 이미지 파일을 읽어 LLM OCR 결과를 box.image_description에 채운다."""
    for box in page.boxes:
        if box.boxclass != "picture" or box.image is None:
            continue

        if not os.path.isfile(box.image):
            print(f"{box.image}파일이 존재하지 않습니다.")
            continue

        with open(box.image, "rb") as f:
            image_bytes = f.read()
        box.image_description = ocr_image(image_bytes)


def _render_page(page: Page) -> str:
    """페이지 내 박스를 순서대로 병합해 최종 텍스트를 만든다.

    picture 박스는 _describe_images()로 채워진 image_description이 있을 때만 포함된다.
    """
    parts: list[str] = []
    for box in page.boxes:
        if box.boxclass == "text":
            parts.append(_join_textlines(box.textlines))
        elif box.boxclass == "list-item":
            parts.append(f"- {_join_textlines(box.textlines)}")
        elif box.boxclass == "title":
            parts.append(f"# {_join_textlines(box.textlines)}")
        elif box.boxclass == "section-header":
            parts.append(f"## {_join_textlines(box.textlines)}")
        elif box.boxclass == "picture" and box.image_description:
            parts.append(box.image_description)
        elif box.boxclass == "table":
            if box.table is not None:
                parts.append(box.table["markdown"])
            else:
                parts.append(_join_textlines(box.textlines))
        elif box.boxclass == "caption":
            # 직전에 추가된 picture/table 설명 뒤에 캡션을 붙여 문맥 연결
            caption_text = _join_textlines(box.textlines)
            if parts:
                parts[-1] += f"\n(설명: {caption_text})"
            else:
                parts.append(caption_text)
        elif box.boxclass == "formula":
            parts.append(_join_textlines(box.textlines))
        elif box.boxclass == "footnote":
            parts.append(f"[각주] {_join_textlines(box.textlines)}")
        elif box.boxclass in ("page-header", "page-footer"):
            pass  # 반복 요소, RAG 컨텍스트에서 노이즈이므로 제외
        else:
            print(box.boxclass)

    return "\n\n".join(parts)


def _join_textlines(textlines: list) -> str:
    """text 박스의 textlines에서 순수 텍스트만 이어붙인다."""
    lines = []
    for tl in textlines:
        line_text = "".join(span.text for span in tl.spans)
        lines.append(line_text)
    return "\n".join(lines)
