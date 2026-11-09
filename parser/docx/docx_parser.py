import logging
import re
from pathlib import Path

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from parser.pdf.type import PageText

logger = logging.getLogger(__name__)

_INDENT = "  "

_NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS_V = "urn:schemas-microsoft-com:vml"
# OCR 모델에 보낼 수 있는 형식. EMF/WMF 같은 벡터 그림은 건너뛴다.
_OCR_CONTENT_TYPES = frozenset({"image/png", "image/jpeg", "image/gif", "image/bmp", "image/webp"})


def parser_docx_md(
        docx_path: Path, ocr_images: bool = True) -> str:
    """docx를 마크다운 텍스트로 변환한다. 본문 순서(문단/표/이미지)를 유지한다.

    ocr_images가 True면 본문 문단에 들어 있는 이미지를 OCR해 그 위치에 넣는다.
    """
    docx = Document(docx_path)

    blocks: list[str] = []
    # 레벨별 번호 카운터. 리스트가 아닌 블록을 만나면 초기화한다.
    counters: dict[int, int] = {}
    # 같은 이미지가 여러 번 쓰여도 OCR은 한 번만 한다. (part 이름 -> OCR 결과)
    ocr_cache: dict[str, str | None] = {}

    for child in docx.element.body.iterchildren():
        if child.tag.endswith("}p"):
            para = Paragraph(child, docx)
            text = _paragraph_to_text(para, counters)
            images = _paragraph_images(para, ocr_cache) if ocr_images else []
            if text is None and not images:  # 빈 문단
                continue
            if not _is_list(para.style.name) or images:
                counters.clear()
            if text is not None:
                blocks.append(text)
            blocks.extend(images)
        elif child.tag.endswith("}tbl"):
            counters.clear()
            blocks.append(_table_to_text(Table(child, docx)))

    return _join_blocks(blocks)


# -------------------------------------------------------------------- image

def _paragraph_images(para: Paragraph, cache: dict[str, str | None]) -> list[str]:
    """문단 안의 이미지를 순서대로 OCR한 결과 목록. 실패하거나 결과가 비면 뺀다."""
    results: list[str] = []
    for rid in _image_rids(para):
        part = para.part.related_parts.get(rid)
        if part is None:
            continue
        key = str(part.partname)
        if key not in cache:
            cache[key] = _ocr_part(part)
        if cache[key]:
            results.append(cache[key])
    return results


def _image_rids(para: Paragraph) -> list[str]:
    """문단에 들어 있는 이미지의 관계 ID. 새 형식(a:blip)과 옛 VML 형식(v:imagedata)을 모두 찾는다."""
    rids: list[str] = []
    for el in para._p.iter(f"{{{_NS_A}}}blip", f"{{{_NS_V}}}imagedata"):
        rid = el.get(f"{{{_NS_R}}}embed") or el.get(f"{{{_NS_R}}}id")
        # mc:AlternateContent는 같은 그림을 두 번 담기도 하므로 중복을 뺀다.
        if rid and rid not in rids:
            rids.append(rid)
    return rids


def _ocr_part(part) -> str | None:
    content_type = getattr(part, "content_type", "")
    if content_type not in _OCR_CONTENT_TYPES:
        logger.info("OCR할 수 없는 이미지 형식이라 건너뜀: %s (%s)", part.partname, content_type)
        return None

    from ocr.provider import ocr_image  # OCR 의존성은 이미지가 있을 때만 불러온다

    try:
        text = ocr_image(part.blob).strip()
    except Exception:
        # OCR이 안 돼도 문서 본문 변환은 계속한다.
        logger.warning("docx 이미지 OCR 실패, 건너뜀: %s", part.partname, exc_info=True)
        return None
    return text or None




def _join_blocks(blocks: list[str]) -> str:
    """연속된 리스트 항목은 한 줄 간격으로, 그 외 블록은 빈 줄로 구분한다."""
    out: list[str] = []
    prev_is_list = False
    for block in blocks:
        cur_is_list = bool(re.match(r"\s*(?:- |\d+\. )", block)) and "\n" not in block
        if out:
            out.append("\n" if prev_is_list and cur_is_list else "\n\n")
        out.append(block)
        prev_is_list = cur_is_list
    return "".join(out).strip() + "\n"


# ---------------------------------------------------------------- paragraph

def _paragraph_to_text(para: Paragraph, counters: dict[int, int] | None = None) -> str | None:
    style = para.style.name if para.style is not None else "Normal"
    text = para.text.strip()

    if not text:
        return None

    if _is_headings(style):
        return _headings(style, text)
    if style == "Title":
        return f"# {text}"
    if style == "Subtitle":
        return f"_{text}_"
    if style == "TOC Heading":
        return f"## {text}"
    if style in ("Quote", "Intense Quote"):
        return "\n".join(f"> {line}" for line in text.splitlines())
    if style == "Caption":
        return f"*{text}*"
    if style == "macro":
        return f"```\n{para.text}\n```"
    if _is_list(style):
        return _list(style, text, counters if counters is not None else {})

    # Normal, Body Text*, Header, Footer, 그 외 알 수 없는 스타일은 텍스트 그대로.
    # 스타일 없이 numPr(자동 번호)만 걸린 문단도 리스트로 처리한다.
    if _has_numbering(para):
        return _list("List Bullet", text, counters if counters is not None else {}, _numbering_level(para))
    return text


def _has_numbering(para: Paragraph) -> bool:
    pPr = para._p.pPr
    return pPr is not None and pPr.numPr is not None


def _numbering_level(para: Paragraph) -> int:
    numPr = para._p.pPr.numPr
    ilvl = numPr.ilvl.val if numPr.ilvl is not None else 0
    return int(ilvl) + 1


# --------------------------------------------------------------------- list

def _get_list_level(prefix: str, style: str) -> int:
    """'List Bullet 2' -> 2, 'List Bullet' -> 1."""
    suffix = style.removeprefix(prefix).strip()
    return int(suffix) if suffix.isdigit() else 1


def _list(style: str, text: str, counters: dict[int, int], level: int | None = None) -> str:
    # 긴 접두사부터 검사해야 "List Bullet"이 "List"에 먹히지 않는다.
    if style.startswith("List Bullet"):
        level = _get_list_level("List Bullet", style)
        return f"{_INDENT * (level - 1)}- {text}"

    if style.startswith("List Number"):
        level = _get_list_level("List Number", style)
        counters[level] = counters.get(level, 0) + 1
        for deeper in [k for k in counters if k > level]:
            del counters[deeper]  # 상위 번호가 올라가면 하위 번호는 다시 1부터
        return f"{_INDENT * (level - 1)}{counters[level]}. {text}"

    if style.startswith("List Continue"):
        # 앞 항목에 이어지는 문단: 들여쓰기만 한다.
        level = _get_list_level("List Continue", style)
        return f"{_INDENT * level}{text}"

    if style.startswith("List Paragraph"):
        return f"{_INDENT * ((level or 1) - 1)}- {text}"

    # "List", "List 2", "List 3"
    level = _get_list_level("List", style)
    return f"{_INDENT * (level - 1)}- {text}"


def _is_list(style: str) -> bool:
    return style.startswith("List")


# ------------------------------------------------------------------ heading

def _is_headings(style: str) -> bool:
    return _get_heading_level(style) is not None


def _get_heading_level(style_name: str) -> int | None:
    """'Heading 1'~'Heading 9'면 레벨(int) 반환, 아니면 None."""
    if style_name.startswith("Heading "):
        suffix = style_name.removeprefix("Heading ")
        if suffix.isdigit():
            return int(suffix)
    return None


def _headings(style: str, text: str) -> str | None:
    heading_level = _get_heading_level(style)
    if heading_level is None:
        return None

    # 마크다운 헤딩은 6단계까지만 의미가 있다.
    prefix = "#" * min(heading_level, 6)
    return f"{prefix} {text}"


# -------------------------------------------------------------------- table

def _table_to_text(table: Table) -> str:
    rows: list[list[str]] = []
    for row in table.rows:
        cells: list[str] = []
        seen: set[int] = set()
        for cell in row.cells:
            # 가로 병합된 셀은 같은 _tc를 여러 번 돌려주므로 한 번만 쓴다.
            if id(cell._tc) in seen:
                continue
            seen.add(id(cell._tc))
            cells.append(_cell_to_text(cell.text))
        rows.append(cells)

    if not rows:
        return ""

    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]

    lines = ["| " + " | ".join(rows[0]) + " |", "| " + " | ".join(["---"] * width) + " |"]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(lines)


def _cell_to_text(text: str) -> str:
    # 마크다운 표 셀 안에서 깨지는 문자 처리
    return text.strip().replace("|", "\\|").replace("\r", "").replace("\n", "<br>")
