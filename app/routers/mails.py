from dataclasses import asdict
from datetime import datetime, date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from entity.type import parse_status_filter, TaskStatus
from mail.email_send import SENDER_EMAIL, send_email
from mail.templates import render_answer_email
from repository import task_repo

router = APIRouter()



class ApproveBody(BaseModel):
    body: str | None = None
    subject: str | None = None
    edited: bool = False

@router.get("/mails/stats")
def view_mail_stats():
    return  {
        "date": date.today().isoformat(),
        "pending_review": 0,
        "sent_today": 0,
        "rejected_today": 0,
        "failed": 0,
        "avg_review_seconds": None,
        "draft_adoption_rate": None,
        "sent_delta": None,
        "daily_volume": [],
    }

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

    items = task_repo.view_all(statuses) or []
    return {"items": items, "total": len(items), "limit": limit, "offset": offset}

@router.get("/mails/{task_id}")
def view_mail_detail(task_id: str):
    detail = task_repo.view_task(task_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="메일을 찾을 수 없습니다")

    return {
        **asdict(detail),
        "recipient": SENDER_EMAIL,
        "model": None,
        "retrieval": None,
        "sources": [],
    }


@router.post("/mails/{task_id}/approve")
def mail_approve(task_id: str,payload:ApproveBody | None = None):
    #먼저 task를 가져옴
    task = task_repo.approve(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="not_found")

    #상태 체크
    if task.get("status") != "drafted":
        raise HTTPException(status_code=409, detail=f"승인할 수 없는 상태입니다: {task.get('status')}")

    #수정된 답변
    answer = (payload.body if payload and payload.body else task.get("draft_answer")) or ""
    if not answer:
        raise HTTPException(status_code=409, detail="draft_answer가 없습니다")

    # 수정본이면 task에 먼저 반영 (전송이 실패해도 재전송 때 수정본이 나가도록)
    if payload and payload.body:
        task_repo.update_draft_answer(task_id, answer)

    subject = f"[응답] {task.get('subject')}"

    #메일 전송
    try:
        send_email(
            to_addr=task.get("sender"),
            subject=subject,
            body=render_answer_email(answer),
            html=True,
        )
    except Exception:
        task_repo.update_status(task_id, TaskStatus.FAILED)
        raise HTTPException(status_code=502, detail="smtp_error")

    #상태 변경
    task_repo.update_status(task_id, TaskStatus.SENT)

    return {
        "task_id": task_id,
        "status": TaskStatus.SENT.value,
        "sent_at": datetime.now().astimezone().isoformat(),
        "to": task.get("sender"),
    }
