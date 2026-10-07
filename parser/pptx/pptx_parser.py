from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE, PP_PLACEHOLDER
from pptx.shapes.base import BaseShape
from pptx.slide import Slide

from parser.pdf.type import PageText

_INDENT = "  "
_TITLE_TYPES = (PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE, PP_PLACEHOLDER.VERTICAL_TITLE)
# 날짜/쪽번호/바닥글 개체 틀은 본문이 아니므로 버린다.
_SKIP_PLACEHOLDERS = (PP_PLACEHOLDER.DATE, PP_PLACEHOLDER.FOOTER, PP_PLACEHOLDER.SLIDE_NUMBER)
_COLUMN_GAP_WEIGHT = 2
_MIN_ROW_PAIRS = 3
_AUTO_ALT_NOTICE = ("AI 생성 콘텐츠는", "AI-generated content may be incorrect")


def parser_pptx_md(pptx_file: str) -> str:
    """pptx를 마크다운 텍스트로 변환한다. 슬라이드마다 읽는 순서(위→아래, 단 단위)를 유지한다."""
    prs = Presentation(pptx_file)

    slides: list[str] = []
    for i, slide in enumerate(prs.slides, start=1):
        slides.append(_slide_to_text(slide, i))

    return "\n\n---\n\n".join(slides).strip() + "\n"

def parser_pptx_pages(pptx_file: str) -> list[PageText]:
    prs = Presentation(pptx_file)
    slides: list[PageText] = []
    for i, slide in enumerate(prs.slides, start=1):
        slides.append(
            PageText(
                page=i,
                text=_slide_to_text(slide, i),
            )
        )
    return slides

# -------------------------------------------------------------------- slide

def _slide_to_text(slide: Slide, number: int) -> str:
    #타이틀 구하기
    title_shape = _find_title(slide, slide.part.package.presentation_part.presentation.slide_height)
    title = _clean(title_shape.text_frame.text) if title_shape is not None else ""

    heading = f"## Slide {number}: {title}" if title else f"## Slide {number}"
    blocks = [heading]

    # 도형 프록시는 접근할 때마다 새로 만들어지므로 XML 요소로 비교한다.
    title_el = title_shape._element if title_shape is not None else None

    blocks += _shapes_to_blocks([s for s in slide.shapes if s._element is not title_el])

    notes = _notes_to_text(slide)
    if notes:
        blocks.append(notes)

    return "\n\n".join(blocks)


def _find_title(slide: Slide, slide_height: int) -> BaseShape | None:
    """제목 개체 틀이 있으면 그것을, 없으면 슬라이드 상단의 첫 텍스트 개체 틀을 제목으로 본다."""
    for shape in slide.placeholders:
        if shape.placeholder_format.type in _TITLE_TYPES and shape.text_frame.text.strip():
            return shape

    candidates = [
        s for s in slide.placeholders
        if s.has_text_frame and s.text_frame.text.strip()
        and s.top is not None and s.top < slide_height * 0.15
    ]
    return min(candidates, key=lambda s: (s.top, s.left or 0), default=None)


def _notes_to_text(slide: Slide) -> str:
    if not slide.has_notes_slide:
        return ""
    text = slide.notes_slide.notes_text_frame.text.strip() if slide.notes_slide.notes_text_frame else ""
    if not text:
        return ""
    return "\n".join(f"> {line}" if line.strip() else ">" for line in _clean(text).splitlines())


# ------------------------------------------------------------- reading order

def _shapes_to_blocks(shapes) -> list[str]:
    """내용이 있는 도형만 골라 읽는 순서대로 정렬한 뒤 텍스트 블록으로 만든다."""
    items: list[tuple[tuple[int, int, int, int], str]] = []
    for shape in shapes:
        text = _shape_to_text(shape)
        if not text:
            continue  # 선, 빈 도형 등은 배치 계산을 방해하므로 먼저 걸러낸다.
        items.append((_bbox(shape), text))

    return [text for _, text in _xy_cut(items)]


def _bbox(shape: BaseShape) -> tuple[int, int, int, int]:
    left, top = shape.left or 0, shape.top or 0
    return left, top, left + (shape.width or 0), top + (shape.height or 0)


def _xy_cut(items: list) -> list:
    """재귀 XY-cut: 도형 사이 빈 띠 중 가장 넓은 곳 하나를 기준으로 둘로 나누기를 반복한다.

    모든 빈 띠를 한꺼번에 자르면 '단 제목 행 / 단 본문 행'이 갈라지므로 한 번에 하나만 자른다.
    슬라이드는 단 사이 여백이 좁게 잡히는 경우가 많아 단(세로 빈 띠) 틈에 가중치를 준다.
    """
    if len(items) <= 1:
        return items

    best: tuple[int, float, list, list] | None = None
    for axis in (1, 0):  # 1: y축(행), 0: x축(단). 틈이 같으면 행 분할 우선.
        cut = _largest_gap_cut(items, axis)
        if cut is None:
            continue
        score = cut[0] * (_COLUMN_GAP_WEIGHT if axis == 0 else 1)
        if best is None or score > best[1]:
            best = (axis, score, cut[1], cut[2])

    if best is None:
        # 더 이상 나눌 수 없으면(겹친 도형) 위→왼쪽 순으로.
        return sorted(items, key=lambda it: (it[0][1], it[0][0]))

    axis, _, first, second = best
    if axis == 0 and _is_row_layout(first, second):
        # '항목 | 값'이 줄마다 짝지어진 구성은 단이 아니라 행 단위로 읽는다.
        return [item for band in _bands(items, 1) for item in _xy_cut(band)]

    return _xy_cut(first) + _xy_cut(second)


def _largest_gap_cut(items: list, axis: int) -> tuple[int, list, list] | None:
    """axis 방향 투영에서 가장 넓은 빈 구간을 찾아 (틈 크기, 앞쪽, 뒤쪽)으로 나눈다."""
    ordered = sorted(items, key=lambda it: it[0][axis])
    best_gap, best_idx = 0, None
    end = ordered[0][0][axis + 2]
    for idx, item in enumerate(ordered[1:], start=1):
        gap = item[0][axis] - end
        if gap >= 0 and (best_idx is None or gap > best_gap):
            best_gap, best_idx = gap, idx
        end = max(end, item[0][axis + 2])

    if best_idx is None:
        return None
    return best_gap, ordered[:best_idx], ordered[best_idx:]


def _bands(items: list, axis: int) -> list[list]:
    """axis 방향 투영에서 서로 겹치지 않는 구간끼리 묶는다(모든 빈 띠에서 자름)."""
    ordered = sorted(items, key=lambda it: it[0][axis])
    groups = [[ordered[0]]]
    end = ordered[0][0][axis + 2]
    for item in ordered[1:]:
        if item[0][axis] >= end:
            groups.append([item])
        else:
            groups[-1].append(item)
        end = max(end, item[0][axis + 2])
    return groups


def _is_row_layout(left: list, right: list) -> bool:
    """좌우 도형이 행마다 1:1로 짝지어져 있으면(3행 이상) 행 구조로 본다."""
    left_ids = {id(it) for it in left}
    paired = 0
    for band in _bands(left + right, 1):
        n_left = sum(id(it) in left_ids for it in band)
        n_right = len(band) - n_left
        if n_left > 1 or n_right > 1:
            return False
        paired += n_left == 1 and n_right == 1
    return paired >= _MIN_ROW_PAIRS


# -------------------------------------------------------------------- shape

def _shape_to_text(shape: BaseShape) -> str:
    if shape.is_placeholder and shape.placeholder_format.type in _SKIP_PLACEHOLDERS:
        return ""

    if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
        return "\n\n".join(_shapes_to_blocks(shape.shapes))
    if getattr(shape, "has_table", False) and shape.has_table:
        return _table_to_text(shape.table)
    if getattr(shape, "has_chart", False) and shape.has_chart:
        return _chart_to_text(shape.chart)
    if shape.shape_type == MSO_SHAPE_TYPE.PICTURE or (
        shape.is_placeholder and shape.placeholder_format.type == PP_PLACEHOLDER.PICTURE
        and not shape.has_text_frame
    ):
        return _picture_to_text(shape)
    if shape.has_text_frame:
        return _text_frame_to_text(shape.text_frame)
    return ""


def _picture_to_text(shape: BaseShape) -> str:
    # 대체 텍스트(descr)가 있는 그림만 남긴다. 장식용 그림까지 넣으면 잡음이 된다.
    descr = shape._element._nvXxPr.cNvPr.get("descr", "")
    lines = [line.strip() for line in _clean(descr).splitlines()]
    # PowerPoint 자동 생성 대체 텍스트에 붙는 안내 문구는 뺀다.
    lines = [line for line in lines if line and not line.startswith(_AUTO_ALT_NOTICE)]
    return f"[이미지: {' '.join(lines)}]" if lines else ""


# --------------------------------------------------------------------- text

def _text_frame_to_text(text_frame) -> str:
    lines: list[str] = []
    for para in text_frame.paragraphs:
        text = _clean(para.text).strip()
        if not text:
            continue
        if para.level > 0:
            # 하위 수준 문단은 들여쓴 리스트로 표현한다.
            lines.append(f"{_INDENT * (para.level - 1)}- {text}")
        else:
            lines.append(text)
    return "\n".join(lines)


def _clean(text: str) -> str:
    # python-pptx는 줄바꿈(<a:br>)을 \v로 돌려준다.
    return text.replace("\v", "\n").replace("\r", "").replace("\xa0", " ")


# -------------------------------------------------------------------- table

def _table_to_text(table) -> str:
    rows: list[list[str]] = []
    for row in table.rows:
        # 병합으로 가려진 셀은 빈 칸으로 두어 열 정렬을 유지한다.
        rows.append(["" if cell.is_spanned else _cell_to_text(cell.text) for cell in row.cells])

    rows = [r for r in rows if any(r)]
    if not rows:
        return ""

    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]

    lines = ["| " + " | ".join(rows[0]) + " |", "| " + " | ".join(["---"] * width) + " |"]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(lines)


def _cell_to_text(text: str) -> str:
    # 마크다운 표 셀 안에서 깨지는 문자 처리
    return _clean(text).strip().replace("|", "\\|").replace("\n", "<br>")


# -------------------------------------------------------------------- chart

def _chart_to_text(chart) -> str:
    title = ""
    if chart.has_title and chart.chart_title.has_text_frame:
        title = _clean(chart.chart_title.text_frame.text).strip()

    header = f"[차트: {title}]" if title else "[차트]"

    try:
        plot = chart.plots[0]
        categories = [str(c) for c in plot.categories]
        series = [s for p in chart.plots for s in p.series]
    except (IndexError, KeyError, ValueError):
        return header

    if not series:
        return header

    lines = ["| 항목 | " + " | ".join(_cell_to_text(s.name or "") for s in series) + " |",
             "| " + " | ".join(["---"] * (len(series) + 1)) + " |"]
    values = [list(s.values) for s in series]
    for idx in range(max(len(categories), max(len(v) for v in values))):
        category = categories[idx] if idx < len(categories) else ""
        cells = [_format_value(v[idx]) if idx < len(v) else "" for v in values]
        lines.append("| " + " | ".join([_cell_to_text(category), *cells]) + " |")

    return header + "\n\n" + "\n".join(lines)


def _format_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


if __name__ == "__main__":
    print(parser_pptx_md("./R&D팀 주간보고(260909)_A.pptx"))
