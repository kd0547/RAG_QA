"""사양 표 가져오기 API (/specs/import).

- GET  /specs/import/template  현재 속성과 제품(부품)을 담은 엑셀 양식. 값이 있으면 같이 넣어 내려준다 (내려받아 고쳐서 올리면 된다).
- POST /specs/import/parse     붙여넣은 표(text) 또는 엑셀(file)을 읽어 미리보기를 만든다. 저장하지 않는다.
- POST /specs/import/apply     미리보기에서 고친 표를 저장한다. 한 곳이라도 못 읽으면 400과 함께 위치를 돌려주고 아무것도 저장하지 않는다.
"""

import io
import logging
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from entity.spec import COMPONENT_KINDS
from parser.spec_table import analyze_grid, extract_table_text, grid_from_text, grid_from_xlsx
from repository import spec_repo
from repository.spec_repository import OWNER_TYPES, SpecImportError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/specs/import", tags=["specs"])

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_TEXT_CHARS = 200_000
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"})


def _recognize_table_image(content: bytes) -> str:
    """화면 캡처 같은 표 이미지를 VLM OCR(ocr/llm_ocr.py)로 읽어 표 텍스트만 돌려준다."""
    from ocr.provider import ocr_image  # 환경변수로 선택한 OCR 백엔드

    return extract_table_text(ocr_image(content))


def _check_owner(owner_type: str, kind: str | None) -> str | None:
    if owner_type not in OWNER_TYPES:
        raise HTTPException(status_code=400, detail="owner_type은 product 또는 component여야 합니다.")
    if owner_type == "component":
        if not kind or kind not in COMPONENT_KINDS:
            raise HTTPException(status_code=400, detail=f"부품을 가져오려면 종류(kind)를 지정하세요. 가능: {', '.join(COMPONENT_KINDS)}")
        return kind
    return None


@router.get("/template")
def download_template(owner_type: str = "product", kind: str | None = None) -> Response:
    """엑셀 양식. 1행 머리글, A열 속성 키, B열 속성 이름, C열 단위, D열부터 모델명. 기존 값이 있으면 채워서 준다."""
    kind = _check_owner(owner_type, kind)
    try:
        import openpyxl
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter
    except ImportError as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail="openpyxl이 설치되어 있지 않습니다.") from exc

    attributes = spec_repo.list_attributes()
    owners = spec_repo.list_products() if owner_type == "product" else spec_repo.list_components(kind)
    details = [spec_repo.get_product(o["id"]) if owner_type == "product" else spec_repo.get_component(o["id"]) for o in owners]
    values: dict[tuple[str, str], list[str]] = {}
    for detail in details:
        for spec in detail["specs"]:
            text = f"{spec['value_text']}(옵션)" if spec["is_option"] else spec["value_text"]
            values.setdefault((detail["id"], spec["attribute_key"]), []).append(text)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "제품 사양" if owner_type == "product" else f"부품 사양 ({COMPONENT_KINDS[kind]})"
    header = ["속성키", "속성명", "단위"] + ([o["model"] for o in owners] or ["모델명1", "모델명2"])
    ws.append(header)
    for attribute in attributes:
        row = [attribute["key"], attribute["name"], attribute["unit"]]
        for detail in details:
            row.append(" / ".join(values.get((detail["id"], attribute["key"]), [])))
        if not details:
            row += ["", ""]
        ws.append(row)

    bold = Font(bold=True)
    fill = PatternFill("solid", fgColor="EBF8FC")
    for cell in ws[1]:
        cell.font = bold
        cell.fill = fill
        cell.alignment = Alignment(horizontal="center")
    for column in range(1, len(header) + 1):
        ws.column_dimensions[get_column_letter(column)].width = 18 if column != 2 else 26
    ws.freeze_panes = "D2"

    guide = wb.create_sheet("작성 안내")
    for line in (
        "A열 속성키는 바꾸지 마세요. 화면의 속성 탭과 같은 키입니다. 새 속성이 필요하면 행을 추가하고 속성키 대신 속성명만 적어도 됩니다 (가져오기 화면에서 속성을 고르게 됩니다).",
        "D열부터 한 열이 제품(부품) 하나입니다. 머리글에 모델명을 적으세요. 없는 모델은 가져올 때 새로 등록됩니다.",
        "값이 여러 개면 슬래시(/)나 줄바꿈으로 나누세요. 두 번째 값부터는 옵션 구성으로 봅니다. '(옵션)'을 붙여 직접 표시해도 됩니다. 예: 16GB / 32GB(옵션)",
        "숫자 속성은 단위를 같이 적어도 됩니다 (2.16kg → 2.16). 예/아니오 속성은 예, 아니오, 있음, 없음, O, X 로 적습니다.",
        "빈 칸은 건너뜁니다. 값이 있는 칸은 가져올 때 그 제품·속성의 기존 값을 표의 값으로 바꿉니다.",
    ):
        guide.append([line])
    guide.column_dimensions["A"].width = 120

    buffer = io.BytesIO()
    wb.save(buffer)
    filename = f"spec_template_{owner_type}{'_' + kind if kind else ''}.xlsx"
    return Response(
        content=buffer.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/parse")
async def parse_table(
    owner_type: Annotated[str, Form()] = "product",
    kind: Annotated[str | None, Form()] = None,
    text: Annotated[str | None, Form()] = None,
    file: UploadFile | None = None,
) -> dict:
    """표를 읽어 미리보기를 만든다. 열 머리글은 기존 제품(부품)과 맞춰 owner_id를 채운다."""
    kind = _check_owner(owner_type, kind or None)

    recognized_text: str | None = None
    if file is not None and file.filename:
        suffix = Path(file.filename).suffix.lower()
        is_image = suffix in IMAGE_SUFFIXES or (file.content_type or "").startswith("image/")
        if not is_image and suffix not in (".xlsx", ".xlsm"):
            raise HTTPException(status_code=400, detail="엑셀(.xlsx)이나 이미지(화면 캡처)만 올릴 수 있습니다. 다른 형식은 표를 복사해 붙여넣으세요.")
        content = await file.read()
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="파일이 너무 큽니다 (5MB 이하).")
        if is_image:
            # 화면 캡처: VLM이 표를 마크다운으로 읽는다. 결과 텍스트도 같이 돌려줘 화면에서 고쳐 다시 읽을 수 있게 한다
            try:
                recognized_text = _recognize_table_image(content)
            except Exception as exc:
                logger.exception("사양 표 이미지 인식 실패: %s", file.filename)
                raise HTTPException(status_code=502, detail=f"이미지에서 표를 읽지 못했습니다 (VLM 오류): {exc}") from exc
            grid = grid_from_text(recognized_text)
            if len(grid) < 2:
                raise HTTPException(
                    status_code=400,
                    detail="이미지에서 표를 인식하지 못했습니다. 표 부분만 크게 캡처하거나, 표를 텍스트로 복사해 붙여넣으세요.",
                )
            source = "캡처 이미지 (VLM 인식)"
        else:
            source = None
    if file is not None and file.filename and source is None:
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)
        try:
            grid = grid_from_xlsx(tmp_path)
        except Exception as exc:
            logger.warning("사양 엑셀 읽기 실패: %s (%s)", file.filename, exc)
            raise HTTPException(status_code=400, detail=f"엑셀 파일을 읽지 못했습니다: {exc}") from exc
        finally:
            tmp_path.unlink(missing_ok=True)
        source = file.filename
    elif file is not None and file.filename:
        pass  # 이미지 분기에서 이미 grid와 source를 만들었다
    elif text and text.strip():
        if len(text) > MAX_TEXT_CHARS:
            raise HTTPException(status_code=413, detail="붙여넣은 표가 너무 큽니다.")
        grid = grid_from_text(text)
        source = "붙여넣기"
    else:
        raise HTTPException(status_code=400, detail="엑셀 파일을 올리거나 표를 붙여넣으세요.")

    try:
        preview = analyze_grid(grid, spec_repo.list_attributes())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    for column in preview["columns"]:
        owner = spec_repo.find_owner(owner_type, column["header"], kind)
        column["owner_id"] = owner["id"] if owner else None
        column["owner_label"] = (owner.get("name") or owner["model"]) if owner else None

    preview.update({"owner_type": owner_type, "kind": kind, "source": source, "recognized_text": recognized_text})
    logger.info(
        "사양 표 미리보기: %s, %s, 열 %d, 행 %d, 속성 못 맞춘 행 %d",
        owner_type, source, len(preview["columns"]), len(preview["rows"]), preview["unmatched_rows"],
    )
    return preview


class ImportColumn(BaseModel):
    header: str
    owner_id: str | None = None
    create: bool = True
    skip: bool = False


class NewAttribute(BaseModel):
    key: str
    name: str
    category: str = "other"
    data_type: str = "text"
    unit: str = ""
    description: str = ""


class ImportRow(BaseModel):
    attribute_key: str | None = None
    new_attribute: NewAttribute | None = None
    cells: list[str]


class ImportBody(BaseModel):
    owner_type: str = "product"
    kind: str | None = None
    replace: bool = True
    source_note: str = ""
    source_page: int | None = None
    columns: list[ImportColumn]
    rows: list[ImportRow]


@router.post("/apply")
def apply_table(body: ImportBody) -> dict:
    kind = _check_owner(body.owner_type, body.kind)
    try:
        summary = spec_repo.import_values(
            body.owner_type,
            [c.model_dump() for c in body.columns],
            [r.model_dump() for r in body.rows],
            kind=kind,
            replace=body.replace,
            source_note=body.source_note,
            source_page=body.source_page,
        )
    except SpecImportError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc), "errors": exc.errors}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    logger.info("사양 표 가져오기 완료: %s, %s", body.owner_type, {k: v for k, v in summary.items() if k != "owners"})
    return summary
