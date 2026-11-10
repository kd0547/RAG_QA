"""사양 가져오기용 엑셀 양식을 만든다. 내려받아 채워서 그대로 올리면 parser/spec_table.py가 읽는다.

시트 구성 (제품):
    | 분류     | 속성키        | 속성명   | 단위 | A650 | A650-GA70-OU01 | A650-GA70-PU02 |
    | 모델 정보 | parent_model | 상위 모델 |      |      | A650           | A650           |
    | 모델 정보 | product_name | 제품 이름 |      | ...  | Home           | Pro            |
    | CPU      | cpu_model    | CPU 모델  |      | (병합: AMD Ryzen AI 7 350)                 |
    | 메모리    | ram_gb       | 메모리 용량 | GB  |      | 16             | 64             |

- 열 하나가 모델 하나다. 제품은 상위 모델 → 하위 모델 순서(트리)로 놓는다.
- 속성은 분류 순서로 묶고, 분류 칸은 세로로 병합한다.
- 사전에 있는 속성에 더해 아직 사전에 없는 기본 속성(entity/spec.py)도 넣는다. 값을 넣고 가져오면 속성도 같이 등록된다.
- 부품 양식은 모델 정보 행이 없고, 그 부품 종류에 쓰는 분류(KIND_CATEGORIES)의 속성만 넣는다.
"""
from __future__ import annotations

import io

from entity.spec import ATTRIBUTE_CATEGORIES, COMPONENT_KINDS, DEFAULT_ATTRIBUTES, KIND_CATEGORIES

INFO_LABEL = "모델 정보"
PRODUCT_INFO = (("parent_model", "상위 모델"), ("product_name", "제품 이름"))
FIXED_COLUMNS = ("분류", "속성키", "속성명", "단위")

_HEADER_FILL = "EBF8FC"
_INFO_FILL = "FFF7E0"
_GROUP_FILLS = ("FFFFFF", "F6F8FA")


def template_attributes(attributes: list[dict], kind: str | None) -> list[dict]:
    """양식에 넣을 속성: 사전 속성 + 사전에 없는 기본 속성. 분류 순서 → 정렬 순서 → 이름 순."""
    known = {a["key"] for a in attributes}
    merged = list(attributes) + [
        {"key": a.key, "name": a.name, "category": a.category, "unit": a.unit, "sort_order": index}
        for index, a in enumerate(DEFAULT_ATTRIBUTES)
        if a.key not in known
    ]
    if kind and kind in KIND_CATEGORIES:
        allowed = set(KIND_CATEGORIES[kind]) | {"other"}
        merged = [a for a in merged if a["category"] in allowed]
    order = {key: i for i, key in enumerate(ATTRIBUTE_CATEGORIES)}
    return sorted(merged, key=lambda a: (order.get(a["category"], len(order)), a.get("sort_order", 0), a["name"]))


def tree_order(products: list[dict]) -> list[dict]:
    """상위 모델 바로 뒤에 하위 모델이 오도록 줄 세운다. 상위가 목록에 없으면 최상위로 본다."""
    ids = {p["id"] for p in products}
    children: dict[str | None, list[dict]] = {}
    for p in sorted(products, key=lambda p: p["model"].lower()):
        parent = p.get("parent_id") if p.get("parent_id") in ids else None
        children.setdefault(parent, []).append(p)
    ordered: list[dict] = []

    def walk(parent_id: str | None, depth: int) -> None:
        for p in children.get(parent_id, []):
            if depth > 20:
                return
            ordered.append(p)
            walk(p["id"], depth + 1)

    walk(None, 0)
    return ordered


def build_template(owner_type: str, kind: str | None, attributes: list[dict], owners: list[dict]) -> bytes:
    """owners: 제품(또는 부품) 상세 목록. 각 항목에 model, specs가 있고 제품이면 parent_id, name도 있다."""
    import openpyxl
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.datavalidation import DataValidation

    is_product = owner_type == "product"
    if is_product:
        owners = tree_order(owners)
    rows = template_attributes(attributes, kind if not is_product else None)
    values: dict[tuple[str, str], list[str]] = {}
    for owner in owners:
        for spec in owner.get("specs", []):
            text = f"{spec['value_text']}(옵션)" if spec["is_option"] else spec["value_text"]
            values.setdefault((owner["id"], spec["attribute_key"]), []).append(text)
    by_id = {o["id"]: o for o in owners}
    headers = [o["model"] for o in owners] or ["모델명1", "모델명2", "모델명3"]
    first_value_col = len(FIXED_COLUMNS) + 1
    last_col = len(FIXED_COLUMNS) + len(headers)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "제품 사양" if is_product else f"부품 사양 ({COMPONENT_KINDS.get(kind or '', kind or '')})"
    ws.append(list(FIXED_COLUMNS) + headers)

    if is_product:
        for key, label in PRODUCT_INFO:
            row = [INFO_LABEL, key, label, ""]
            for owner in owners:
                if key == "parent_model":
                    parent = by_id.get(owner.get("parent_id") or "")
                    row.append(parent["model"] if parent else "")
                else:
                    row.append(owner.get("name") or "")
            ws.append(row + [""] * (len(headers) - len(owners)))

    groups: list[tuple[str, int, int]] = []  # (분류, 시작 행, 끝 행)
    for attribute in rows:
        label = ATTRIBUTE_CATEGORIES.get(attribute["category"], attribute["category"])
        row = [label, attribute["key"], attribute["name"], attribute.get("unit") or ""]
        for owner in owners:
            row.append(" / ".join(values.get((owner["id"], attribute["key"]), [])))
        ws.append(row + [""] * (len(headers) - len(owners)))
        if groups and groups[-1][0] == label:
            groups[-1] = (label, groups[-1][1], ws.max_row)
        else:
            groups.append((label, ws.max_row, ws.max_row))

    # ---- 꾸미기 ----
    thin = Side(style="thin", color="D9DEE5")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    wrap_top = Alignment(vertical="top", wrap_text=True)
    for row in ws.iter_rows(min_row=1, max_row=ws.max_row, max_col=last_col):
        for cell in row:
            cell.border = border
            cell.alignment = wrap_top
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor=_HEADER_FILL)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    info_rows = range(2, 2 + len(PRODUCT_INFO)) if is_product else range(0)
    for r in info_rows:
        for c in range(1, last_col + 1):
            ws.cell(r, c).fill = PatternFill("solid", fgColor=_INFO_FILL)
        ws.cell(r, 3).font = Font(bold=True)
    if is_product:
        ws.merge_cells(start_row=2, start_column=1, end_row=1 + len(PRODUCT_INFO), end_column=1)
    for index, (_, start, end) in enumerate(groups):
        fill = PatternFill("solid", fgColor=_GROUP_FILLS[index % 2])
        for r in range(start, end + 1):
            for c in range(1, last_col + 1):
                ws.cell(r, c).fill = fill
        ws.cell(start, 1).font = Font(bold=True)
        if end > start:
            ws.merge_cells(start_row=start, start_column=1, end_row=end, end_column=1)
    for r in range(2, ws.max_row + 1):
        ws.cell(r, 2).font = Font(color="8A94A3", size=9)  # 속성키는 기계용이라 흐리게

    widths = {1: 12, 2: 18, 3: 24, 4: 8}
    for c in range(1, last_col + 1):
        ws.column_dimensions[get_column_letter(c)].width = widths.get(c, 28)
    ws.freeze_panes = ws.cell(2 + len(PRODUCT_INFO) if is_product else 2, first_value_col)

    if is_product:
        # 상위 모델 칸은 1행 모델명 목록에서 고를 수 있게 한다 (직접 입력도 된다). 열을 더 붙여도 되게 넓게 잡는다
        validation = DataValidation(
            type="list", formula1=f"=${get_column_letter(first_value_col)}$1:$AZ$1", allow_blank=True,
            showErrorMessage=False, promptTitle="상위 모델", prompt="파생 모델이면 시리즈(상위) 모델명. 시리즈 열은 비웁니다.",
        )
        validation.showInputMessage = True
        ws.add_data_validation(validation)
        validation.add(f"{get_column_letter(first_value_col)}2:AZ2")

    _add_guide(wb, is_product)
    if is_product:
        _add_example(wb)

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _add_guide(wb, is_product: bool) -> None:
    guide = wb.create_sheet("작성 안내")
    lines = ["첫 시트만 읽습니다. 시트 이름과 순서는 바꾸지 마세요.",
             "1행: E열부터 한 열이 모델 하나입니다. 모델명을 적으세요. 없는 모델은 가져올 때 새로 등록됩니다."]
    if is_product:
        lines += [
            "2행 상위 모델: 파생 모델이면 갈라져 나온 시리즈(상위) 모델명을 적습니다. 시리즈 열은 비웁니다. "
            "같은 표의 다른 열이거나 이미 등록된 모델이어야 합니다. 칸을 누르면 1행 모델명 목록에서 고를 수 있습니다.",
            "3행 제품 이름: 화면에 보일 이름입니다. 예: Home, Pro, N5800 14세대",
            "여러 모델에 같은 값이면 제안서처럼 셀을 가로로 병합하세요. 병합된 모든 모델에 같은 값이 들어갑니다. ('작성 예시' 시트 참고)",
        ]
    lines += [
        "B열 속성키는 바꾸지 마세요. 새 항목이 필요하면 행을 추가하고 속성명(C열)만 적어도 됩니다. 가져오기 화면에서 속성을 고르거나 새로 만듭니다.",
        "속성 사전에 아직 없는 기본 항목(베어본, 칩셋, 인증 모델명 등)도 들어 있습니다. 값을 넣으면 가져올 때 속성이 함께 등록됩니다.",
        "값이 여러 개면 슬래시( / )나 줄바꿈으로 나누세요. 두 번째 값부터는 옵션 구성으로 봅니다. '(옵션)'을 붙여 직접 표시해도 됩니다. 예: 16GB / 32GB(옵션)",
        "숫자 속성은 단위를 같이 적어도 됩니다 (2.16kg → 2.16). 예/아니오 속성은 예, 아니오, 있음, 없음, O, X 로 적습니다.",
        "빈 칸은 건너뜁니다. 값이 있는 칸은 가져올 때 그 모델·속성의 기존 값을 표의 값으로 바꿉니다.",
    ]
    for index, line in enumerate(lines, start=1):
        guide.append([f"{index}. {line}"])
    guide.column_dimensions["A"].width = 120


def _add_example(wb) -> None:
    """병합 셀로 시리즈 공통 값을 넣는 예시. 가져오기는 첫 시트만 읽으므로 이 시트는 읽히지 않는다."""
    from openpyxl.styles import Alignment, Font, PatternFill

    ws = wb.create_sheet("작성 예시")
    ws.append(list(FIXED_COLUMNS) + ["A650", "A650-GA70-OU01", "A650-GA70-PU02"])
    ws.append([INFO_LABEL, "parent_model", "상위 모델", "", "", "A650", "A650"])
    ws.append([INFO_LABEL, "product_name", "제품 이름", "", "A650 Series", "Home", "Pro"])
    ws.append(["CPU", "cpu_model", "CPU 모델", "", "AMD Ryzen AI 7 350", "", ""])
    ws.append(["메모리", "ram_gb", "메모리 용량", "GB", "", "16", "64"])
    ws.append(["저장장치", "ssd_gb", "SSD 용량", "GB", "", "2048", "4096"])
    ws.append(["운영체제", "os", "운영체제", "", "", "Windows 11 Home", "Windows 11 Pro"])
    ws.append(["인증·규격", "cert_model", "인증 모델명", "", "A600", "", ""])
    ws.merge_cells("E4:G4")  # 세 모델 공통
    ws.merge_cells("E8:G8")
    ws.merge_cells("A2:A3")
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor=_HEADER_FILL)
    for r in (2, 3):
        for c in range(1, 8):
            ws.cell(r, c).fill = PatternFill("solid", fgColor=_INFO_FILL)
    for row in ws.iter_rows():
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    for column, width in zip("ABCDEFG", (12, 16, 16, 8, 22, 22, 22)):
        ws.column_dimensions[column].width = width
    ws.append([])
    ws.append(["CPU·인증 모델명처럼 병합한 칸은 세 모델 모두에 들어갑니다. 메모리처럼 모델마다 다르면 칸마다 따로 적습니다."])
