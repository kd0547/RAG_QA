from contextlib import closing
from pathlib import Path

from bs4 import BeautifulSoup
from hwp5.xmlmodel import Hwp5File


def _hwp_to_xml(hwp_path: Path) -> bytes:
    """HWP 5.x 파일을 외부 프로세스 실행 없이 XML로 변환."""
    with closing(Hwp5File(str(hwp_path))) as hwp:
        return b"".join(hwp.xmlevents().bytechunks())


def _cell_to_md(cell) -> str:
    """셀 내부 문단을 추출하고 마크다운 표에 맞게 처리."""
    paragraphs = []

    for paragraph in cell.find_all("Paragraph"):
        # Text 조각 사이에는 임의의 공백을 넣지 않음
        text = "".join(
            node.get_text()
            for node in paragraph.find_all("Text")
            if node.find_parent("Paragraph") is paragraph
        )

        # 셀 내부 개행·연속 공백 정리
        text = " ".join(text.split())

        if text:
            paragraphs.append(text)

    text = "<br>".join(paragraphs)

    # 표 구분자로 해석되지 않도록 이스케이프
    return text.replace("|", r"\|")


def _table_to_md(table) -> str:
    """표를 마크다운으로 변환. 첫 행을 헤더로 사용."""
    rows = []

    for row in table.find_all("TableRow"):
        # 중첩 표의 행을 현재 표의 행으로 중복 처리하지 않음
        if row.find_parent("TableControl") is not table:
            continue

        cells = [
            _cell_to_md(cell)
            for cell in row.find_all("TableCell")
            if cell.find_parent("TableRow") is row
            and cell.find_parent("TableControl") is table
        ]

        if cells:
            rows.append(cells)

    if not rows:
        return ""

    # 행마다 셀 개수가 다르면 빈 셀로 보정
    column_count = max(len(row) for row in rows)

    for row in rows:
        row.extend([""] * (column_count - len(row)))

    lines = [
        "| " + " | ".join(rows[0]) + " |",
        "| " + " | ".join(["---"] * column_count) + " |",
    ]

    for row in rows[1:]:
        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines)


def _render_node(node) -> str:
    """XML 트리를 순서대로 탐색하며 문단과 표를 변환."""
    name = getattr(node, "name", None)

    if name is None:
        return ""

    if name == "Text":
        return node.get_text()

    if name == "TableControl":
        table_md = _table_to_md(node)
        return f"\n\n{table_md}\n\n" if table_md else ""

    # 자식들을 순서대로 처리해 표 내부 텍스트 중복 추출 방지
    content = "".join(_render_node(child) for child in node.children)

    if name == "Paragraph":
        content = content.strip()
        return content + "\n\n" if content else ""

    return content


def parser_hwp_md(hwp_path: Path) -> str:
    """HWP 파일의 본문과 표를 마크다운 문자열로 반환."""
    hwp_path = Path(hwp_path)

    if not hwp_path.is_file():
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {hwp_path}")

    xml_bytes = _hwp_to_xml(hwp_path)
    soup = BeautifulSoup(xml_bytes, "xml")

    body = soup.find("BodyText")
    if body is None:
        raise ValueError("HWP XML에서 BodyText를 찾을 수 없습니다.")

    return _render_node(body).strip()


if __name__ == "__main__":
    path = "test.hwp"
    hwp_path = Path(path)
    print(parser_hwp_md(hwp_path))