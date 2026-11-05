"""엑셀·붙여넣기 표를 사양 값 격자로 읽는다.

입력 표는 "속성이 행, 제품(또는 부품)이 열"인 넓은 표다.
    | 속성      | 단위 | N5800 | A650        |
    | 메모리 용량 | GB  | 16    | 16 / 32(옵션) |

- 첫 열은 속성(키 또는 이름). "단위", "설명" 같은 보조 열은 건너뛴다.
- 나머지 열 머리글은 제품 모델명(부품이면 부품 모델명)이다.
- 셀 하나에 값이 여러 개면 줄바꿈, 세미콜론, 공백이 붙은 슬래시(" / ")로 나눈다. "MB/s", "N/A",
  "w/Hsink"처럼 붙어 있는 슬래시는 나누지 않는다. "(옵션)" 표시가 있거나 두 번째 값부터는 옵션 구성으로 본다.
- TBD, N/A, ?, 미정 같은 표기는 값이 아니라서 건너뛴다 (그 칸은 저장하지 않는다).

여기서는 읽고 맞추기만 한다. 저장은 SpecRepository.import_values()가 한다.
"""
from __future__ import annotations

import csv
import io
import re
from pathlib import Path

from entity.spec import DEFAULT_ATTRIBUTES
from repository.spec_repository import parse_value

# 첫 열 다음에 올 수 있는 보조 열. 머리글이 이 중 하나면 값 열로 보지 않는다.
_META_HEADERS = frozenset(
    _n for _n in (
        "속성키", "속성 키", "키", "key", "속성명", "속성 이름", "속성이름", "이름", "name",
        "단위", "unit", "설명", "description", "분류", "category", "비고", "note", "자료형", "type",
    )
)
_OPTION_MARK = re.compile(r"\(?\s*(옵션|option|opt|선택)\s*\)?", re.IGNORECASE)
# 값 구분자: 줄바꿈, 세미콜론, 양쪽(또는 한쪽)에 공백이 있는 슬래시. "MB/s", "N/A"는 붙어 있어 나뉘지 않는다
_VALUE_SPLIT = re.compile(r"[\n;]|\s+/\s*|\s*/\s+")
# 아직 모르는 값. 저장할 값이 아니므로 건너뛴다
UNKNOWN_TOKENS = frozenset({"tbd", "n/a", "na", "?", "??", "-", "—", "–", "미정", "확인필요", "확인 필요", "추후", "none"})
_MD_SEPARATOR = re.compile(r"^:?-{2,}:?$")


def normalize_label(text: str) -> str:
    """비교용 정규화: 소문자, 공백·괄호·기호 제거."""
    return re.sub(r"[\s_\-·.,:/()（）\[\]]+", "", (text or "").strip().lower())


# ---------- 원본 → 2차원 문자열 격자 ----------

def grid_from_text(text: str) -> list[list[str]]:
    """붙여넣은 텍스트를 격자로 바꾼다. 탭(엑셀 복사), 마크다운 표, CSV 순으로 판단한다."""
    lines = [line.rstrip("\r") for line in text.splitlines() if line.strip()]
    if not lines:
        return []

    if all(line.lstrip().startswith("|") for line in lines):
        rows = []
        for line in lines:
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if cells and all(_MD_SEPARATOR.match(c) for c in cells if c):
                continue  # |---|---| 구분선
            rows.append(cells)
        return _trim(rows)

    if any("\t" in line for line in lines):
        return _trim([[c.strip() for c in line.split("\t")] for line in lines])

    if any("," in line for line in lines):
        reader = csv.reader(io.StringIO("\n".join(lines)))
        return _trim([[c.strip() for c in row] for row in reader])

    # 구분자가 없으면 2칸 이상 공백으로 나눈다
    return _trim([[c.strip() for c in re.split(r"\s{2,}", line.strip())] for line in lines])


def grid_from_xlsx(path: str | Path, sheet: str | None = None) -> list[list[str]]:
    """엑셀 첫 시트(또는 지정 시트)를 격자로 바꾼다. 병합 셀은 왼쪽 위 값으로 채운다."""
    import openpyxl

    from parser.xlsx.xlsx_parser import _fill_merged_cells
    from parser.xlsx.xlsx_record_parser import _cell_text

    wb = openpyxl.load_workbook(path, data_only=True)
    try:
        ws = wb[sheet] if sheet else next((w for w in wb.worksheets if w.max_row > 0 and w.max_column > 0), wb.worksheets[0])
        grid = [[_cell_text(cell.value) for cell in row] for row in ws.iter_rows(min_row=1, max_row=ws.max_row, max_col=ws.max_column)]
        _fill_merged_cells(ws, grid)
    finally:
        wb.close()
    return _trim(grid)


def _trim(rows: list[list[str]]) -> list[list[str]]:
    """완전히 빈 행·열을 걷어낸다."""
    rows = [row for row in rows if any(c.strip() for c in row)]
    if not rows:
        return []
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    keep = [i for i in range(width) if any(r[i].strip() for r in rows)]
    return [[r[i] for i in keep] for r in rows]


# ---------- 셀 값 나누기 ----------

def split_cell(raw: str) -> list[dict]:
    """셀 하나를 값 목록으로 나눈다. [{"value_text", "is_option"}]"""
    parts = [p.strip() for p in _VALUE_SPLIT.split(raw or "") if p and p.strip()]
    values = []
    explicit = any(_OPTION_MARK.search(p) for p in parts)
    for index, part in enumerate(parts):
        marked = bool(_OPTION_MARK.search(part))
        text = _OPTION_MARK.sub("", part).strip(" -")
        if not text or text.lower() in UNKNOWN_TOKENS:
            continue
        is_option = marked if explicit else index > 0
        values.append({"value_text": text, "is_option": is_option})
    return values


# ---------- 속성 맞추기 ----------

def build_attribute_index(attributes: list[dict]) -> dict[str, tuple[str, str]]:
    """정규화한 표기 -> (속성 키, 맞춘 방법). 키·이름·기본 별칭을 모두 등록한다."""
    index: dict[str, tuple[str, str]] = {}
    defaults = {a.key: a for a in DEFAULT_ATTRIBUTES}
    for attribute in attributes:
        key = attribute["key"]
        index.setdefault(normalize_label(key), (key, "key"))
        index.setdefault(normalize_label(attribute["name"]), (key, "name"))
        if attribute.get("unit"):
            index.setdefault(normalize_label(f"{attribute['name']}({attribute['unit']})"), (key, "name"))
        default = defaults.get(key)
        if default:
            for alias in default.aliases:
                index.setdefault(normalize_label(alias), (key, "alias"))
    return index


def analyze_grid(grid: list[list[str]], attributes: list[dict]) -> dict:
    """격자를 미리보기 구조로 바꾼다. 속성 맞추기와 값 검증까지 한다. 저장은 하지 않는다."""
    if len(grid) < 2 or len(grid[0]) < 2:
        raise ValueError("표에 머리글 행과 값 열이 최소 하나씩 있어야 합니다. 첫 열은 속성, 나머지 열은 모델명입니다.")

    header = grid[0]
    value_columns = [
        i for i, h in enumerate(header)
        if i > 0 and h.strip() and normalize_label(h) not in {normalize_label(m) for m in _META_HEADERS}
    ]
    skipped = [header[i] for i in range(1, len(header)) if i not in value_columns]
    if not value_columns:
        raise ValueError("모델명 열을 찾지 못했습니다. 머리글에 제품(부품) 모델명이 있어야 합니다.")

    index = build_attribute_index(attributes)
    data_types = {a["key"]: a["data_type"] for a in attributes}
    rows = []
    for r, row in enumerate(grid[1:], start=1):
        label = row[0].strip()
        if not label:
            continue
        matched = index.get(normalize_label(label))
        attribute_key, match = matched if matched else (None, None)
        cells = []
        for c in value_columns:
            raw = row[c] if c < len(row) else ""
            values = split_cell(raw)
            for value in values:
                value["error"] = _validate(data_types.get(attribute_key), value["value_text"]) if attribute_key else None
            cells.append({"column": c, "raw": raw, "values": values})
        if not any(cell["values"] for cell in cells):
            continue  # 값이 하나도 없는 행은 미리보기에서 뺀다
        rows.append({"index": r, "label": label, "attribute_key": attribute_key, "match": match, "cells": cells})

    return {
        "columns": [{"index": c, "header": header[c].strip()} for c in value_columns],
        "rows": rows,
        "skipped_columns": skipped,
        "unmatched_rows": sum(1 for row in rows if row["attribute_key"] is None),
    }


def _validate(data_type: str | None, value_text: str) -> str | None:
    if data_type is None:
        return None
    try:
        parse_value(data_type, value_text)
    except ValueError as exc:
        return str(exc)
    return None


def extract_table_text(text: str) -> str:
    """VLM OCR 결과(ocr/llm_ocr.py)에서 표 부분만 남긴다.

    OCR 프롬프트는 표를 마크다운 표로 쓰므로 '|'로 시작하는 줄이 둘 이상이면 그 줄들만 쓴다.
    표가 여러 개면 한 덩어리로 이어 붙인다 (같은 머리글이면 뒤 표의 머리글 줄은 중복 행으로 들어가므로
    analyze_grid에서 속성이 안 맞아 건너뛰기로 보인다). 마크다운 표가 없으면 원문을 그대로 돌려준다.
    """
    lines = [line.strip() for line in (text or "").splitlines()]
    table_lines = [line for line in lines if line.startswith("|")]
    if len(table_lines) >= 2:
        return "\n".join(table_lines)
    return text or ""
