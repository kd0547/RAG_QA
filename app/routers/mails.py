import json
import logging
from dataclasses import asdict
from datetime import datetime, date
from pathlib import Path, PureWindowsPath

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from entity.type import parse_status_filter, TaskStatus
from mail.email_send import SENDER_EMAIL, SendOutcome, SendResult, send_email
from mail.templates import render_answer_email
from repository import evidence_repo, task_repo
from repository.task_repository import TaskRepository
from logging_config import mask_email

logger = logging.getLogger(__name__)

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
            "average_score": f["average_score"],
            "path": f["stored_path"],
        })
    return candidates


class RejectBody(BaseModel):
    reason: str
    requeue: bool = True


def _client_ip(request: Request) -> str | None:
    """감사 로그용 요청자 IP. 로그인 기능이 없어 담당자를 구분할 수 있는 값은 이것뿐이다."""
    return request.client.host if request.client else None


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


    sources = [
        {"source": PureWindowsPath(s["source"] or "").name, "page": s["page"], "text": s["text"],
         "evidence_id": s["chunk_id"], "cited": bool(s["cited"])}
        for s in task_repo.get_sources(task_id)
    ]
    return {
        **asdict(detail),
        "recipient": SENDER_EMAIL,
        "model": None,
        "retrieval": None,
        # 초안의 근거 검증 결과 {ok, errors, warnings, cited_ids}. 검증 전 초안은 None
        "validation": task_repo.get_validation(task_id),
        # 파일명만 내보낸다 (task_sources.source에는 디스크 경로가 들어 있을 수 있다).
        # 윈도우에서 저장한 경로를 리눅스(Docker)에서 읽어도 잘리도록 \와 / 둘 다 구분자로 본다.
        # 답변이 인용한 근거가 있으면 그것(cited=true), 없으면 읽은 근거(cited=false)
        "sources": sources,
        # 에이전트가 읽었지만 sources에 없는 근거 (인용하지 않은 페이지). 화면이 따로 보여 준다
        "read_sources": _read_sources(task_id, {s["evidence_id"] for s in sources}),
        # 가장 최근 실행에서 에이전트가 부른 도구 [{tool, args_summary, at}] (호환용. 화면은 runs를 쓴다)
        "trace": _latest_trace(task_id),
        # 이 메일의 실행 전체 (1차 초안, 반려 반영 …) 시작 순서. 검토 화면 '에이전트가 한 일'
        "runs": _runs(task_id),
        # 디스크 경로는 화면에 내보내지 않는다
        "attachments": [
            {k: v for k, v in c.items() if k != "path"}
            for c in _attachment_candidates(task_id)
        ],
    }

def _latest_trace(task_id: str) -> list[dict]:
    run = evidence_repo.latest_run("task", task_id)
    if run is None or not run.get("tool_calls_json"):
        return []
    try:
        return json.loads(run["tool_calls_json"])
    except ValueError:
        logger.warning("실행 기록의 도구 호출 목록을 읽지 못함: task_id=%s, run=%s", task_id, run["run_id"])
        return []


_RUN_FIELDS = ("run_id", "label", "status", "started_at", "seconds", "tokens_in", "tokens_out", "tool_calls", "skills")


def _runs(task_id: str) -> list[dict]:
    return [{key: run.get(key) for key in _RUN_FIELDS} for run in evidence_repo.runs_for_owner("task", task_id)]


def _read_sources(task_id: str, shown: set) -> list[dict]:
    """이 메일의 실행들에서 읽은 근거 중 sources에 없는 것 (본문 앞 300자)."""
    return [
        {"source": e["source_name"] or "", "page": e["page"], "text": (e["text"] or "")[:300],
         "evidence_id": e["evidence_id"], "cited": False}
        for e in evidence_repo.uses_for_owner("task", task_id, "read")
        if e["evidence_id"] not in shown
    ]


@router.post("/mails/{task_id}/reject")
def mail_reject(task_id: str, payload: RejectBody, request: Request):
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
        logger.warning("반려 충돌(상태가 이미 변경됨): task_id=%s, client=%s", task_id, _client_ip(request))
        raise HTTPException(status_code=409, detail="상태가 변경되어 반려할 수 없습니다")

    logger.info(
        "답변 반려: task_id=%s, %s -> %s, requeue=%s, client=%s, reason=%s",
        task_id, task.status.value, next_status.value, payload.requeue, _client_ip(request), reason[:200],
    )
    return {"task_id": task_id, "status": next_status.value}

# 승인(발송)할 수 있는 상태. 실패·불명 건은 담당자가 다시 승인할 때만 다시 보낸다 (자동 재발송 없음).
SENDABLE = [s.value for s in TaskRepository.SENDABLE]

_SEND_STATUS = {
    SendOutcome.SENT: TaskStatus.SENT,
    SendOutcome.FAILED: TaskStatus.SEND_FAILED,
    SendOutcome.UNKNOWN: TaskStatus.SEND_UNKNOWN,
}

# 화면과 메일 링크 페이지가 그대로 보여주는 안내 문구
SEND_FAILED_MESSAGE = "메일 서버가 발송을 받지 않았습니다(send_failed). 원인을 확인한 뒤 다시 승인할 수 있습니다."
SEND_UNKNOWN_MESSAGE = (
    "발송 중 연결이 끊겨 메일이 전달됐는지 알 수 없습니다(send_unknown). "
    "보낸편지함·수신자에게 확인한 뒤 '발송 확인됨' 또는 '재발송'을 선택하세요. 자동으로 다시 보내지 않습니다."
)


@router.post("/mails/{task_id}/approve")
def mail_approve(task_id: str, request: Request, payload:ApproveBody | None = None):
    #먼저 task를 가져옴
    task = task_repo.approve(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="not_found")

    #상태 체크 (빠른 거절용. 실제 중복 방지는 아래 claim_for_send가 한다)
    if task.get("status") not in SENDABLE:
        # 버튼을 두 번 누르거나 이미 보낸 메일을 다시 승인한 경우. 중복 전송 시도를 추적할 수 있게 남긴다.
        logger.warning(
            "승인 거부(상태 불일치): task_id=%s, status=%s, client=%s",
            task_id, task.get("status"), _client_ip(request),
        )
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

    recipient = task.get("sender")
    # 발송 선점: 상태를 sending으로 바꾸고 본문·수신자·첨부를 고정한다. 동시에 두 번 승인하면 한쪽만 성공한다.
    send_id = task_repo.claim_for_send(task_id, answer, recipient, attachments)
    if send_id is None:
        logger.warning("승인 거부(다른 요청이 먼저 발송 시작): task_id=%s, client=%s", task_id, _client_ip(request))
        raise HTTPException(status_code=409, detail="이미 발송 중이거나 처리된 메일입니다")

    # 수정본이면 task에도 반영 (발송이 실패해도 재승인 때 수정본이 보이도록)
    if payload and payload.body:
        task_repo.update_draft_answer(task_id, answer)

    subject = f"[응답] {task.get('subject')}"

    #메일 전송. send_email은 예외 대신 결과를 돌려준다.
    try:
        result = send_email(
            to_addr=recipient,
            subject=subject,
            body=render_answer_email(answer, question=task.get("body") or ""),
            html=True,
            attachments=attachments,
        )
    except Exception as exc:
        # send_email이 예외를 던지는 것은 예상 밖이다. 메일이 나갔는지 모르므로 불명으로 둔다.
        logger.exception("답변 메일 발송 중 예상하지 못한 오류: task_id=%s", task_id)
        result = SendResult(SendOutcome.UNKNOWN, f"{type(exc).__name__}: {exc}"[:500])

    status = _SEND_STATUS[result.outcome]
    task_repo.finish_send(send_id, task_id, status, result.detail, result.cleanup_warning)
    if result.cleanup_warning:
        logger.warning("답변 메일은 수락됐지만 연결 정리 실패: task_id=%s, %s", task_id, result.cleanup_warning)

    if status == TaskStatus.SEND_FAILED:
        logger.error(
            "답변 메일 발송 실패: task_id=%s, send_id=%s, to=%s, attachments=%d, client=%s, %s",
            task_id, send_id, mask_email(recipient), len(attachments), _client_ip(request), result.detail,
        )
        raise HTTPException(status_code=502, detail=SEND_FAILED_MESSAGE)
    if status == TaskStatus.SEND_UNKNOWN:
        logger.error(
            "답변 메일 발송 결과 불명: task_id=%s, send_id=%s, to=%s, client=%s, %s",
            task_id, send_id, mask_email(recipient), _client_ip(request), result.detail,
        )
        raise HTTPException(status_code=502, detail=SEND_UNKNOWN_MESSAGE)

    logger.info(
        "답변 승인·전송 완료: task_id=%s, send_id=%s, to=%s, edited=%s, attachments=%d, client=%s",
        task_id, send_id, mask_email(recipient), bool(payload and payload.body), len(attachments), _client_ip(request),
    )

    return {
        "task_id": task_id,
        "status": TaskStatus.SENT.value,
        "sent_at": datetime.now().astimezone().isoformat(),
        "to": recipient,
    }


@router.post("/mails/{task_id}/retry")
def mail_retry(task_id: str, request: Request):
    """답변 생성에 실패한(failed) 작업을 다시 생성하도록 pending으로 돌린다. 메일은 보내지 않는다."""
    task = task_repo.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="not_found")
    if not task_repo.retry(task_id):
        raise HTTPException(status_code=409, detail=f"생성 실패(failed) 상태에서만 다시 생성할 수 있습니다: {task.status.value}")
    logger.info("다시 생성 요청: task_id=%s, failed -> pending, client=%s", task_id, _client_ip(request))
    return {"task_id": task_id, "status": TaskStatus.PENDING.value}


class MarkSentBody(BaseModel):
    reason: str


@router.post("/mails/{task_id}/mark-sent")
def mail_mark_sent(task_id: str, payload: MarkSentBody, request: Request):
    """수락 여부를 모르는 발송(send_unknown)을 담당자가 '실제로 나갔다'고 확인해 sent로 바꾼다. 메일은 보내지 않는다."""
    reason = payload.reason.strip()
    if not reason:
        raise HTTPException(status_code=400, detail="확인 사유가 필요합니다")

    task = task_repo.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="not_found")
    if not task_repo.mark_sent(task_id, reason):
        raise HTTPException(status_code=409, detail=f"발송 결과 불명(send_unknown) 상태에서만 확인할 수 있습니다: {task.status.value}")

    logger.info(
        "발송 확인 처리: task_id=%s, send_unknown -> sent, client=%s, reason=%s",
        task_id, _client_ip(request), reason[:200],
    )
    return {"task_id": task_id, "status": TaskStatus.SENT.value}
