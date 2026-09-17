from fastapi import APIRouter, HTTPException

from entity.type import parse_status_filter
from repository import task_repo

router = APIRouter()


@router.get("/mails")
def mail_view(
    status: str = "drafted,in_review,failed",
    q: str | None = None,
    order: str = "-received_at",
    limit: int = 50,
    offset: int = 0,
):
    """승인 대기 목록. 계약: docs/mail_approval_api.md 3장 GET /mails."""
    statuses = parse_status_filter(status)
    if statuses is None:
        raise HTTPException(status_code=400, detail=f"알 수 없는 status 값: {status}")

    # TODO: mails/tasks 조인 조회는 아직 미구현 (TaskRepository.view_all 등이 스텁).
    # 여기는 라우팅/파라미터 계약만 맞춰둔 상태 — 실제 쿼리는 repository 계층에서 채워야 함.
    items = task_repo.view_all() or []
    return {"items": items, "total": len(items), "limit": limit, "offset": offset}

