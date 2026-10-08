from dataclasses import asdict
from datetime import datetime, date
from pathlib import Path

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
    # 답장에 첨부할 참고 문서. 사내 문서가 외부로 나가지 않도록 담당자가 고른 것만 붙인다(기본: 없음).
    attachment_file_ids: list[str] = []


def _attachment_candidates(task_id: str) -> list[dict]:
    """답장에 첨부할 수 있는 파일 = 답변이 참고한 문서 원본 (같은 파일은 한 번만)."""
    candidates = []
    for f in task_repo.get_source_files(task_id):
        path = Path(f["stored_path"])
        available = path.is_file()
        candidates.append({
            "file_id": f["file_id"],
            "filename": f["original_name"],
            "mime_type": f["mime_type"],
            "size_bytes": path.stat().st_size if available else None,
            "available": available,
            "path": f["stored_path"],
        })
    return candidates


class RejectBody(BaseModel):
    reason: str
    requeue: bool = True


# 검토 대기 중인 초안만 반려할 수 있다
REJECTABLE = [TaskStatus.DRAFTED, TaskStatus.IN_REVIEW]

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
        "sources": [
            {"source": s["source"], "page": s["page"], "text": s["text"]}
            for s in task_repo.get_sources(task_id)
        ],
        # 디스크 경로는 화면에 내보내지 않는다
        "attachments": [
            {k: v for k, v in c.items() if k != "path"}
            for c in _attachment_candidates(task_id)
        ],
    }

@router.post("/mails/{task_id}/reject")
def mail_reject(task_id: str, payload: RejectBody):
    task = task_repo.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="not_found")

    if task.status not in REJECTABLE:
        raise HTTPException(status_code=409, detail=f"반려할 수 없는 상태입니다: {task.status.value}")

    reason = payload.reason.strip()
    if not reason:
        raise HTTPException(status_code=400, detail="반려 사유가 필요합니다")

    # requeue면 pending으로 돌려 consumer가 초안을 다시 만들고, 아니면 사람이 직접 처리하도록 failed
    next_status = TaskStatus.PENDING if payload.requeue else TaskStatus.FAILED
    if not task_repo.reject(task_id, reason, next_status, REJECTABLE):
        # 조회와 갱신 사이에 다른 요청이 상태를 바꾼 경우
        raise HTTPException(status_code=409, detail="상태가 변경되어 반려할 수 없습니다")

    return {"task_id": task_id, "status": next_status.value}

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

    #첨부파일: 담당자가 고른 참고 문서만. 이 메일이 참고하지 않은 파일은 받지 않는다.
    selected = list(dict.fromkeys(payload.attachment_file_ids if payload else []))  # 중복 ID 제거, 순서 유지
    candidates = {c["file_id"]: c for c in _attachment_candidates(task_id)}
    unknown = [file_id for file_id in selected if file_id not in candidates]
    if unknown:
        raise HTTPException(status_code=400, detail=f"이 메일이 참고하지 않은 파일입니다: {', '.join(unknown)}")
    missing = [candidates[file_id]["filename"] for file_id in selected if not candidates[file_id]["available"]]
    if missing:
        raise HTTPException(status_code=409, detail=f"첨부할 파일을 찾을 수 없습니다: {', '.join(missing)}")
    attachments = [
        {"filename": candidates[file_id]["filename"], "path": candidates[file_id]["path"],
         "mime_type": candidates[file_id]["mime_type"]}
        for file_id in selected
    ]

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
            attachments=attachments,
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
