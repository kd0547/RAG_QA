import re
from pathlib import Path

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from parser.pdf.type import PageText

_INDENT = "  "


def parser_docx_md(
        docx_path: Path) -> str:
    """docx를 마크다운 텍스트로 변환한다. 본문 순서(문단/표)를 유지한다."""
    docx = Document(docx_path)

    blocks: list[str] = []
    # 레벨별 번호 카운터. 리스트가 아닌 블록을 만나면 초기화한다.
    counters: dict[int, int] = {}

    for child in docx.element.body.iterchildren():
        if child.tag.endswith("}p"):
            para = Paragraph(child, docx)
            text = _paragraph_to_text(para, counters)
            if text is None:  # 빈 문단
                continue
            if not _is_list(para.style.name):
                counters.clear()
            blocks.append(text)
        elif child.tag.endswith("}tbl"):
            counters.clear()
            blocks.append(_table_to_text(Table(child, docx)))

    return _join_blocks(blocks)




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
