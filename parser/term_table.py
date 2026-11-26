"""용어집 표 읽기 (엑셀·붙여넣기 → 용어 행). DB를 보지 않는다. 기존 용어와의 대조는 repository/term_repository.py가 한다.

양식 (시트 한 장, 첫 행이 머리글):
    | 표준 이름 | 다른 표기 | 종류 | 구성 용어 | 연결 대상 | 설명 |
- 표준 이름만 꼭 있어야 한다. 나머지 열은 없어도 된다.
- 다른 표기·구성 용어는 쉼표·줄바꿈·세미콜론으로 나눈다.
- 종류는 '용어' 또는 '묶음'. 비우면 구성 용어가 있을 때 묶음이다.
  구성 용어는 같은 표의 행이나 이미 등록된 용어의 이름(또는 표기)으로 쓴다.
- 연결 대상은 "그래프:인증", "사양:메모리 용량"처럼 쓴다 (앞말 없이 "인증"만 써도 된다).
"""
from __future__ import annotations

import re

from parser.spec_table import grid_from_text, grid_from_xlsx  # noqa: F401  (라우터가 같이 쓴다)

COLUMNS = ("name", "aliases", "kind", "members", "target", "description")
HEADERS = {"name": "표준 이름", "aliases": "다른 표기", "kind": "종류", "members": "구성 용어",
           "target": "연결 대상", "description": "설명"}

# 머리글 표기 (비교용: 소문자, 공백·기호 제거)
_HEADER_NAMES = {
    "name": ("표준이름", "표준용어", "용어", "이름", "name", "term", "standardname"),
    "aliases": ("다른표기", "동의어", "별칭", "다른이름", "표기", "aliases", "alias", "synonyms", "synonym"),
    "kind": ("종류", "구분", "kind", "type"),
    "members": ("구성용어", "구성", "포함용어", "members", "member"),
    "target": ("연결대상", "연결", "대상", "target"),
    "description": ("설명", "정의", "메모", "비고", "description", "note", "notes"),
}
_ALIAS_SPLIT = re.compile(r"[,\n;，、]")
# 머리글을 찾을 때 볼 첫 행 수 (양식 위에 제목 행을 둔 경우)
_HEADER_SCAN_ROWS = 5


def _label(text: str) -> str:
    return re.sub(r"[\s_\-·.,:/()（）\[\]*]+", "", (text or "").strip().lower())


def split_aliases(raw: str) -> list[str]:
    """다른 표기 칸을 나눈다. 빈 칸과 같은 표기(대소문자·공백 차이 포함)는 한 번만 남긴다."""
    seen: set[str] = set()
    result: list[str] = []
    for part in _ALIAS_SPLIT.split(raw or ""):
        alias = " ".join(part.split())
        key = _label(alias)
        if alias and key not in seen:
            seen.add(key)
            result.append(alias)
    return result


def find_header(grid: list[list[str]]) -> tuple[int, dict[str, int]]:
    """머리글 행 번호와 열 위치 {열 종류: 열 번호}. 표준 이름 열이 없으면 ValueError."""
    for row_index, row in enumerate(grid[:_HEADER_SCAN_ROWS]):
        columns: dict[str, int] = {}
        for col_index, cell in enumerate(row):
            label = _label(cell)
            for column, names in _HEADER_NAMES.items():
                if column not in columns and label in names:
                    columns[column] = col_index
                    break
        if "name" in columns:
            return row_index, columns
    raise ValueError("머리글에 '표준 이름' 열이 없습니다. 양식의 첫 행(표준 이름 | 다른 표기 | 종류 | 구성 용어 | 연결 대상 | 설명)을 그대로 두세요.")


def rows_from_grid(grid: list[list[str]]) -> list[dict]:
    """격자를 용어 행으로 바꾼다. 표준 이름과 다른 표기가 모두 빈 행은 건너뛴다.

    반환: [{"line": 원본 행 번호(1부터), "name", "aliases": [..], "kind", "members": [..], "target", "description"}]
    """
    if not grid:
        raise ValueError("표가 비어 있습니다.")
    header_row, columns = find_header(grid)

    def cell(row: list[str], column: str) -> str:
        index = columns.get(column)
        return (row[index] if index is not None and index < len(row) else "").strip()

    rows = []
    for offset, row in enumerate(grid[header_row + 1:], start=header_row + 2):
        name = " ".join(cell(row, "name").split())
        aliases = split_aliases(cell(row, "aliases"))
        if not name and not aliases and not cell(row, "members"):
            continue
        rows.append({
            "line": offset,
            "name": name,
            "aliases": aliases,
            "kind": cell(row, "kind"),
            "members": split_aliases(cell(row, "members")),
            "target": cell(row, "target"),
            "description": cell(row, "description"),
        })
    if not rows:
        raise ValueError("머리글 아래에 용어 행이 없습니다.")
    return rows


def build_template(rows: list[dict]) -> bytes:
    """엑셀 양식. rows가 있으면 (등록된 용어) 채워서 준다. 채운 뒤 그대로 올리면 된다.

    rows: [{"name", "aliases": [..], "kind"("용어"/"묶음"), "members": [이름..], "target", "description"}]
    — target은 화면 표기("그래프:인증").
    """
    import io

    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "용어집"
    ws.append([HEADERS[c] for c in COLUMNS])
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="E8EEF5")
    for row in rows:
        ws.append([row["name"], ", ".join(row["aliases"]), row.get("kind", ""), ", ".join(row.get("members") or []),
                   row.get("target", ""), row.get("description", "")])
    for column, width in zip("ABCDEF", (24, 40, 10, 36, 22, 56)):
        ws.column_dimensions[column].width = width
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "A2"

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
