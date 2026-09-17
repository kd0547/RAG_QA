from __future__ import annotations
from pathlib import Path
from pypdf import PdfReader
import json as _json
from rag.type import PageText, PageImage, Document
import os
import re

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



def pdf_pages(pdf_path: str | Path) -> Document:
    import pymupdf4llm

    pdf_path = Path(pdf_path)
    project_root = Path(__file__).resolve().parent.parent

    image_dir_name = re.sub(r"[^\w\-가-힣]", "_", pdf_path.stem)
    image_dir_abs = project_root / "data" / "images" / image_dir_name
    image_dir_abs.mkdir(parents=True, exist_ok=True)

    image_dir_rel = os.path.relpath(image_dir_abs, Path.cwd())

    print(image_dir_abs)
    raw = pymupdf4llm.to_json(
        pdf_path,
        write_images=True,
        image_path=str(image_dir_rel),
        image_format="png",
        dpi=200,
    )
    return Document.model_validate(_json.loads(raw))

def build_page_content(page) -> str:
    """페이지 내 박스를 순서대로 병합해 최종 텍스트를 만든다."""
    from rag.image_to_text import image_to_text_from_pdf

    image_to_text_from_pdf(page)  # box.image_description 채워짐

    parts: list[str] = []
    for box in page.boxes:
        if box.boxclass == "text":
            parts.append(extract_from_textlines(box.textlines))
        elif box.boxclass == "list-item":
            parts.append(f"- {extract_from_textlines(box.textlines)}")
        elif box.boxclass == "title":
            parts.append(f"# {extract_from_textlines(box.textlines)}")
        elif box.boxclass == "section-header":
            parts.append(f"## {extract_from_textlines(box.textlines)}")
        elif box.boxclass == "picture" and box.image_description:
            parts.append(box.image_description)
        elif box.boxclass == "table":
            if box.table is not None:
                parts.append(box.table["markdown"])
            else:
                parts.append(extract_from_textlines(box.textlines))
        elif box.boxclass == "caption":
            # 직전에 추가된 picture/table 설명 뒤에 캡션을 붙여 문맥 연결
            caption_text = extract_from_textlines(box.textlines)
            if parts:
                parts[-1] += f"\n(설명: {caption_text})"
            else:
                parts.append(caption_text)
        elif box.boxclass == "formula":
            parts.append(extract_from_textlines(box.textlines))
        elif box.boxclass == "footnote":
            parts.append(f"[각주] {extract_from_textlines(box.textlines)}")
        elif box.boxclass in ("page-header", "page-footer"):
            pass  # 반복 요소, RAG 컨텍스트에서 노이즈이므로 제외
        else:
            print(box.boxclass)

    return "\n\n".join(parts)


def extract_from_textlines(textlines: list) -> str:
    """text 박스의 textlines에서 순수 텍스트만 이어붙인다."""
    lines = []
    for tl in textlines:
        line_text = "".join(span.text for span in tl.spans)
        lines.append(line_text)
    return "\n".join(lines)

if __name__ == "__main__":
    from langchain_ollama import ChatOllama
    from agent.llm_provider import set_llm_model

    llm = ChatOllama(model="qwen3.8:27b", num_ctx=65536)
    set_llm_model(model=llm)

    pdf_path = r"C:\Users\김동욱\Downloads\TG_AI_Powered_Station_with_코난LLM_사용자가이드_3.0.pdf"
    doc = pdf_pages(pdf_path)

    for page in doc.pages:
        content = build_page_content(page)
        print(f"[Page {page.page_number}]\n{content}\n")
