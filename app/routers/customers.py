"""고객방 API (조회 전용). 발신자별 문의·초안·반려·발송을 시간순으로 보여 준다.

처리(승인·반려·편집)는 검토 화면(/mails/…)에서만 한다. 이 응답은 모델 입력에 쓰지 않는다.
"""
from fastapi import APIRouter, HTTPException, Query

from repository import customer_repo

router = APIRouter()


@router.get("/customers")
def list_customers(
    q: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    return customer_repo.list_customers(q=q, limit=limit, offset=offset)


@router.get("/customers/{sender}/timeline")
def customer_timeline(
    sender: str,
    limit: int = Query(20, ge=1, le=100),
    before: str | None = None,
) -> dict:
    try:
        timeline = customer_repo.timeline(sender, limit=limit, before=before)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if timeline is None:
        raise HTTPException(status_code=404, detail="이 발신자의 메일이 없습니다.")
    return timeline
