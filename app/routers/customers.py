"""고객방 API. 발신자별 문의·초안·반려·발송을 시간순으로 보여 주고(조회 전용), 담당자 메모를 남긴다.

처리(승인·반려·편집)는 검토 화면(/mails/…)에서만 한다. 타임라인 응답은 모델 입력에 쓰지 않는다.
담당자 메모(사용 중인 것)는 답변 에이전트의 get_customer_history 도구가 보여 준다 (통합 지시서 G1).
"""
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from repository import customer_history_repo, customer_repo
from repository.customer_history_repository import CustomerNoteNotFoundError

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



# ---------------------------------------------------------------- 담당자 메모

class NoteBody(BaseModel):
    text: str


@router.get("/customers/{sender}/notes")
def list_notes(sender: str) -> dict:
    """메모 목록 (사용 중지한 것 포함, 최근 것부터)."""
    return {"sender": sender.strip().lower(), "items": customer_history_repo.list_notes(sender)}


@router.post("/customers/{sender}/notes", status_code=201)
def add_note(sender: str, body: NoteBody, request: Request) -> dict:
    """메모 추가. 500자까지. 작성자는 요청 IP다 (로그인이 없다)."""
    try:
        return customer_history_repo.add_note(sender, body.text, created_by=request.client.host if request.client else "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/customers/{sender}/notes/{note_id}/retire")
def retire_note(sender: str, note_id: int) -> dict:
    """메모 사용 중지 (지우지 않는다). 사용 중지한 메모는 답변 에이전트에 보이지 않는다."""
    try:
        return customer_history_repo.retire_note(sender, note_id)
    except CustomerNoteNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
