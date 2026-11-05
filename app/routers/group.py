"""문서 그룹 목록·생성·수정 API. 파일 등록과 그룹 이동은 app/routers/files.py가 담당한다."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from repository import group_repo
from repository.group_repository import DuplicateGroupNameError, GroupNotFoundError

router = APIRouter(prefix="/groups", tags=["groups"])


class GroupCreateBody(BaseModel):
    name: str
    description: str = ""


class GroupUpdateBody(BaseModel):
    name: str | None = None
    description: str | None = None


@router.get("")
def list_groups() -> list[dict]:
    """그룹 속성·생성/수정 시각과 그룹별 파일 수를 반환한다."""
    return group_repo.list_all()


@router.post("", status_code=201)
def create_group(body: GroupCreateBody) -> dict:
    """이름과 선택적 설명으로 문서 그룹을 만든다."""
    try:
        return group_repo.create(body.name, body.description)
    except DuplicateGroupNameError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/{group_id}")
def update_group(group_id: str, body: GroupUpdateBody) -> dict:
    """이름 또는 설명을 부분 수정한다. 빈 설명은 설명을 지운다."""
    changes = body.model_dump(exclude_unset=True)
    if not changes or any(value is None for value in changes.values()):
        raise HTTPException(status_code=400, detail="수정할 그룹 이름 또는 설명을 입력해 주세요.")
    try:
        return group_repo.update(group_id, **changes)
    except GroupNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DuplicateGroupNameError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
