"""용어집 API (/graph/terms). 지식 그래프 화면의 용어집 탭이 쓴다.

용어집은 사람이 관리하는 회사 용어다 (repository/term_repository.py). 문서 그래프에는 쓰지 않고,
그래프 검색이 질문을 읽을 때만 쓴다 (graph_rag/service.py).

- GET    /graph/terms                 목록 (?q=검색어)
- POST   /graph/terms                 직접 추가
- PATCH  /graph/terms/{id}            수정 (준 항목만. aliases는 목록 통째로)
- DELETE /graph/terms/{id}            삭제
- GET    /graph/terms/targets         연결 대상 후보 (그래프 개체 종류, 사양 속성)
- GET    /graph/terms/resolve?q=      질문을 어떻게 읽는지 미리보기 (찾은 용어와 그 표기로 찾은 그래프 개체)
- GET    /graph/terms/changes         변경 이력
- GET    /graph/terms/template        엑셀 양식 (등록된 용어를 채워서 준다)
- POST   /graph/terms/import/parse    엑셀(file)·붙여넣기(text)를 읽어 미리보기. 저장하지 않는다
- POST   /graph/terms/import/check    미리보기에서 고친 행을 다시 대조. 저장하지 않는다
- POST   /graph/terms/import/apply    미리보기에서 고친 행을 저장. 충돌·오류 행이 남아 있으면 400, 아무것도 저장하지 않는다
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from parser.term_table import build_template, grid_from_text, grid_from_xlsx, rows_from_grid
from repository import graph_repo, term_repo
from repository.term_repository import KIND_LABELS, TermConflictError, TermError, TermImportError, TermNotFoundError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/graph/terms", tags=["terms"])

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_TEXT_CHARS = 200_000


def _client(request: Request) -> str:
    return request.client.host if request.client else ""


def _raise(exc: Exception):
    if isinstance(exc, TermNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, TermConflictError):
        raise HTTPException(status_code=409, detail={"message": str(exc), "conflicts": exc.conflicts}) from exc
    if isinstance(exc, TermImportError):
        raise HTTPException(status_code=400, detail={"message": str(exc), "rows": exc.rows}) from exc
    if isinstance(exc, TermError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    raise exc


class TermBody(BaseModel):
    name: str
    aliases: list[str] = []
    target_type: str = ""
    target_key: str = ""
    description: str = ""
    members: list[int] = []  # 구성 용어 id. 있으면 묶음


class TermPatch(BaseModel):
    name: str | None = None
    aliases: list[str] | None = None
    target_type: str | None = None
    target_key: str | None = None
    description: str | None = None
    members: list[int] | None = None  # 주면 통째로 바꾼다. []면 묶음을 푼다


@router.get("")
def list_terms(q: str | None = None) -> list[dict]:
    return term_repo.list_terms(q)


@router.get("/targets")
def list_targets() -> dict:
    return term_repo.targets()


@router.get("/resolve")
def resolve(q: str) -> dict:
    """질문 하나를 용어집으로 어떻게 읽는지. 그래프 검색(graph_search)이 쓰는 것과 같은 규칙이다."""
    terms = term_repo.find_in_query(q)
    for term in [*terms, *(m for t in terms for m in t["members"])]:
        entity_type = term["target_key"] if term["target_type"] == "entity_type" else None
        term["graph_entities"] = graph_repo.find_entities_by_norms(term.pop("alias_norms"), entity_type)
    return {"query": q, "terms": terms}


@router.get("/changes")
def list_changes(term_id: int | None = None, limit: int = 50) -> list[dict]:
    return term_repo.changes(term_id, max(1, min(limit, 200)))


@router.post("", status_code=201)
def create_term(body: TermBody, request: Request) -> dict:
    try:
        term = term_repo.create(body.name, body.aliases, body.target_type, body.target_key, body.description,
                                members=body.members, created_by=_client(request))
    except Exception as exc:
        _raise(exc)
    logger.info("용어 추가: %s (표기 %d)", term["name"], len(term["aliases"]))
    return term


@router.patch("/{term_id}")
def update_term(term_id: int, body: TermPatch, request: Request) -> dict:
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=400, detail="바꿀 항목이 없습니다.")
    try:
        return term_repo.update(term_id, created_by=_client(request), **changes)
    except Exception as exc:
        _raise(exc)


@router.delete("/{term_id}", status_code=204)
def delete_term(term_id: int, request: Request) -> None:
    try:
        term_repo.delete(term_id, created_by=_client(request))
    except Exception as exc:
        _raise(exc)


@router.get("/template")
def download_template() -> Response:
    rows = [{"name": t["name"], "aliases": t["aliases"], "kind": KIND_LABELS[t["kind"]],
             "members": [m["name"] for m in t["members"]], "target": t["target_text"], "description": t["description"]}
            for t in term_repo.list_terms()]
    return Response(
        content=build_template(rows),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=term_template.xlsx"},
    )


@router.post("/import/parse")
async def parse_import(
    text: Annotated[str | None, Form()] = None,
    file: UploadFile | None = None,
) -> dict:
    if file is not None and file.filename:
        if Path(file.filename).suffix.lower() not in (".xlsx", ".xlsm"):
            raise HTTPException(status_code=400, detail="엑셀(.xlsx)만 올릴 수 있습니다. 다른 형식은 표를 복사해 붙여넣으세요.")
        content = await file.read()
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="파일이 너무 큽니다 (5MB 이하).")
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)
        try:
            grid = grid_from_xlsx(tmp_path)
        except Exception as exc:
            logger.warning("용어집 엑셀 읽기 실패: %s (%s)", file.filename, exc)
            raise HTTPException(status_code=400, detail=f"엑셀 파일을 읽지 못했습니다: {exc}") from exc
        finally:
            tmp_path.unlink(missing_ok=True)
        source = file.filename
    elif text and text.strip():
        if len(text) > MAX_TEXT_CHARS:
            raise HTTPException(status_code=413, detail="붙여넣은 표가 너무 큽니다.")
        grid = grid_from_text(text)
        source = "붙여넣기"
    else:
        raise HTTPException(status_code=400, detail="엑셀 파일을 올리거나 표를 붙여넣으세요.")

    try:
        rows = rows_from_grid(grid)
        plan = term_repo.plan_import(rows)
    except (ValueError, TermError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    logger.info("용어집 미리보기: %s, 행 %d, %s", source, len(rows), plan["counts"])
    return {"source": source, **plan}


class ImportRow(BaseModel):
    line: int | None = None
    name: str = ""
    aliases: list[str] = []
    kind: str = ""
    members: list[str] = []
    target: str = ""
    description: str = ""
    skip: bool = False


class ImportBody(BaseModel):
    source: str = ""
    rows: list[ImportRow]


@router.post("/import/check")
def check_import(body: ImportBody) -> dict:
    """미리보기에서 고친 행을 다시 대조한다. 저장하지 않는다."""
    try:
        return {"source": body.source, **term_repo.plan_import([r.model_dump() for r in body.rows])}
    except TermError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/import/apply")
def apply_import(body: ImportBody, request: Request) -> dict:
    source = f"import:{body.source or '표'}"
    try:
        summary = term_repo.apply_import([r.model_dump() for r in body.rows], source=source, created_by=_client(request))
    except Exception as exc:
        _raise(exc)
    logger.info("용어집 가져오기 완료: %s, %s", source, summary)
    return summary
