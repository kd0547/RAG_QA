"""사용자 질문 -> LangGraph RAG 에이전트 라우터."""
from __future__ import annotations

import base64
import csv
import io
import logging
import shutil
import time
from collections import Counter
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Form, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from agent.agent import get_agent, run_agent_temp_attachments
from app import qa_log
from entity.type import Attachment
from parser.file_parser import SUPPORTED_EXTENSIONS
from repository import qa_log_repo

logger = logging.getLogger(__name__)

router = APIRouter()


class QuestionRequest(BaseModel):
    """질문 요청.

    query_top_n·rerank_top_n은 예전 화면과의 호환을 위해 받기만 하고 무시한다.
    검색·리랭크 개수는 서버 설정(config.SEARCH_TOP_K, config.RERANK_TOP_N)과 도구 기본값이 정한다.
    """
    question: str
    mode: Literal['claude', 'local'] = 'local'
    rerank_top_n: int | None = None   # 무시됨
    query_top_n: int | None = None    # 무시됨

from agent.agent import run_agent

@router.post("/ask")
async def ask_question(payload: QuestionRequest, request: Request) -> dict:
    question = payload.question.strip()
    mode = payload.mode
    if not question:
        raise HTTPException(status_code=400, detail="질문을 입력해주세요.")

    user_message = question

    started = time.perf_counter()
    logger.debug("질문 수신: mode=%s, question=%s", mode, question[:200])
    try:
        # 에이전트 실행(LLM·도구 호출)은 동기라 수십 초 걸린다. async 함수에서 바로 부르면 이벤트 루프를 막아
        # 답변이 끝날 때까지 서버의 다른 요청이 모두 멈춘다. 스레드풀에서 돌린다.
        result = await run_in_threadpool(run_agent, user_message, mode)
    except Exception as exc:
        qa_log.record_failure(request, "ask", mode, question, started, exc)
        if not isinstance(exc, RuntimeError):
            raise
        # 모델 미로드 등. 클라이언트에는 503만 가므로 원인을 남긴다
        logger.warning("질문 처리 불가(503): mode=%s, %s", mode, exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    sources = _public_sources(result["sources"])

    logger.info(
        "질문 응답 완료: mode=%s, question_len=%d, answer_len=%d, sources=%d, %.1f초",
        mode, len(question), len(str(result["answer"])), len(sources), time.perf_counter() - started,
    )
    log_id = qa_log.record_answer(request, "ask", mode, question, started, result, sources)

    return {
        "question": question,
        "answer": result["answer"],
        "sources": sources,
        "validation": result.get("validation"),
        "log_id": log_id,
    }


def _public_sources(sources: list[dict]) -> list[dict]:
    """화면에 보낼 출처. cited: 답변이 인용한 근거면 true, 읽기만 한 근거면 false."""
    return [
        {"source": doc["source"], "page": doc["page"], "text": doc["text"],
         "evidence_id": doc.get("evidence_id"), "cited": bool(doc.get("cited"))}
        for doc in sources
    ]


# ---------- 첨부가 있는 질문 (POST /ask/attachments, multipart) ----------
# 화면에서 사양서·캡처 같은 파일을 질문에 붙여 보낸다. 문서 저장소에 올리지 않고 그 질문에만 쓴다.
# 메일 수신부(mail/email_receiver.py)와 같은 Attachment 형태로 만들어 run_agent_temp_attachments 에 넘긴다.
#   - 이미지: data URL 로 모델에 직접 보여준다 (VLM)
#   - 그 외 문서(pdf/docx/pptx/xlsx/hwp/hwpx): 임시 폴더에 저장 → 메시지에는 안내 한 줄만 넣고 에이전트가
#     read_attachment(음수 번호)로 필요한 페이지만 읽는다 (파싱 결과는 이 질문 동안만 메모리에) → 응답 후 삭제

ATTACHMENT_TEMP_DIR = Path(__file__).resolve().parents[2] / "temp" / "ask"
MAX_ATTACHMENTS = 5
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"})
IMAGE_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".bmp": "image/bmp", ".webp": "image/webp"}


def _safe_attachment_name(filename: str) -> str:
    name = Path(filename).name.strip() or "attachment"
    return "".join(ch for ch in name if ch not in '<>:"/\\|?*').strip() or "attachment"


async def _build_attachments(files: list[UploadFile], work_dir: Path) -> list[Attachment]:
    attachments: list[Attachment] = []
    for file in files:
        filename = _safe_attachment_name(file.filename or "")
        ext = Path(filename).suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"지원하지 않는 첨부 형식입니다: {filename} (지원: {', '.join(sorted(SUPPORTED_EXTENSIONS))})",
            )
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail=f"빈 파일입니다: {filename}")
        if len(content) > MAX_ATTACHMENT_BYTES:
            raise HTTPException(status_code=413, detail=f"첨부가 너무 큽니다 (20MB 이하): {filename}")

        if ext in IMAGE_EXTENSIONS:
            mime = file.content_type if (file.content_type or "").startswith("image/") else IMAGE_MIME[ext]
            data_url = f"data:{mime};base64,{base64.b64encode(content).decode('ascii')}"
            attachments.append(Attachment(type="image", filename=filename, content_type=mime, image=data_url, path=None))
            continue

        work_dir.mkdir(parents=True, exist_ok=True)
        # 같은 이름의 파일을 두 개 붙여도 덮어쓰지 않도록 순번을 붙인다
        save_path = work_dir / f"{len(attachments)}_{filename}"
        save_path.write_bytes(content)
        attachments.append(Attachment(
            type=ext.lstrip("."), filename=filename,
            content_type=file.content_type or "application/octet-stream", image=None, path=str(save_path),
        ))
    return attachments


@router.post("/ask/attachments")
async def ask_question_with_attachments(
    request: Request,
    question: Annotated[str, Form()],
    mode: Annotated[Literal["claude", "local"], Form()] = "local",
    query_top_n: Annotated[int | None, Form()] = None,   # 무시됨 (QuestionRequest 참고)
    rerank_top_n: Annotated[int | None, Form()] = None,  # 무시됨
    files: list[UploadFile] | None = None,
) -> dict:
    """첨부 파일·이미지와 함께 질문한다. 첨부는 이 질문에만 쓰고 저장소에는 남기지 않는다."""
    question = question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="질문을 입력해주세요.")
    files = [f for f in (files or []) if f.filename]
    if len(files) > MAX_ATTACHMENTS:
        raise HTTPException(status_code=400, detail=f"첨부는 한 번에 {MAX_ATTACHMENTS}개까지 보낼 수 있습니다.")

    work_dir = ATTACHMENT_TEMP_DIR / uuid4().hex
    started = time.perf_counter()
    try:
        attachments = await _build_attachments(files, work_dir)
        logger.debug(
            "첨부 질문 수신: mode=%s, attachments=%s, question=%s",
            mode, [a.filename for a in attachments], question[:200],
        )
        attachment_info = [{"filename": a.filename, "type": a.type} for a in attachments]
        try:
            # /ask와 같은 이유로 스레드풀에서 돌린다 (이벤트 루프를 막지 않게)
            result = await run_in_threadpool(run_agent_temp_attachments, question, mode, attachments=attachments)
        except Exception as exc:
            qa_log.record_failure(request, "ask_attachments", mode, question, started, exc, attachment_info)
            if not isinstance(exc, RuntimeError):
                raise
            logger.warning("첨부 질문 처리 불가(503): mode=%s, %s", mode, exc)
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    sources = _public_sources(result["sources"])
    logger.info(
        "첨부 질문 응답 완료: mode=%s, attachments=%d, question_len=%d, answer_len=%d, sources=%d, %.1f초",
        mode, len(attachments), len(question), len(str(result["answer"])), len(sources), time.perf_counter() - started,
    )
    log_id = qa_log.record_answer(
        request, "ask_attachments", mode, question, started, result, sources, attachment_info,
    )
    return {
        "question": question,
        "answer": result["answer"],
        "sources": sources,
        "validation": result.get("validation"),
        "attachments": attachment_info,
        "log_id": log_id,
    }


# ---------- 질의응답 평가와 로그 내려받기 ----------
# 화면의 좋음/아쉬움 버튼이 /ask/feedback 으로 평가를 붙이고, 검토용으로 /ask/logs 에서 모아 내려받는다.

GRAPH_TOOLS = frozenset({"graph_search", "read_graph_facts"})


class FeedbackRequest(BaseModel):
    log_id: str
    rating: Literal["good", "bad"] | None = None   # None이면 평가를 지운다
    comment: str | None = None


@router.post("/ask/feedback")
def ask_feedback(payload: FeedbackRequest) -> dict:
    if not qa_log_repo.set_feedback(payload.log_id, payload.rating, payload.comment):
        raise HTTPException(status_code=404, detail="질의응답 기록을 찾을 수 없습니다.")
    return {"log_id": payload.log_id, "rating": payload.rating}


@router.get("/ask/logs")
def ask_logs(
    since: str | None = None,
    until: str | None = None,
    rating: Literal["good", "bad", "rated", "unrated"] | None = None,
    format: Literal["json", "csv"] = "json",
):
    """질의응답 로그. since/until은 'YYYY-MM-DD' 또는 ISO 시각 (until은 그 시각 전까지).

    json: 출처 본문·도구 호출까지 전부. csv: 엑셀로 훑어보는 요약 (BOM 포함 UTF-8).
    """
    logs = qa_log_repo.list_logs(since=since, until=until, rating=rating)
    if format == "json":
        return {"count": len(logs), "logs": logs}
    stamp = time.strftime("%Y%m%d-%H%M")
    return Response(
        content="﻿" + _logs_csv(logs),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="qa_log_{stamp}.csv"'},
    )


def _tool_summary(calls: list[dict] | None) -> tuple[int, int, str]:
    """(도구 호출 수, 그래프 도구 호출 수, '도구×횟수' 요약)."""
    counts = Counter(c.get("tool", "?") for c in calls or [] if isinstance(c, dict))
    graph = sum(n for name, n in counts.items() if name in GRAPH_TOOLS)
    return sum(counts.values()), graph, ", ".join(f"{name}×{n}" for name, n in counts.most_common())


_CSV_HEADER = [
    "질문 시각", "접속 주소", "평가", "의견", "질문", "답변", "상태", "오류", "모드", "모델",
    "걸린 시간(초)", "도구 호출 수", "그래프 도구 호출 수", "도구 호출", "인용 출처 수", "읽은 출처 수",
    "입력 토큰", "출력 토큰", "첨부", "log_id", "run_id",
]
_RATING_LABEL = {"good": "좋음", "bad": "아쉬움"}


def _logs_csv(logs: list[dict]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(_CSV_HEADER)
    for log in logs:
        total, graph, summary = _tool_summary(log.get("tool_calls"))
        sources = log.get("sources") or []
        writer.writerow([
            log["asked_at"], log["client_ip"], _RATING_LABEL.get(log.get("rating") or "", ""), log.get("comment") or "",
            log["question"], log.get("answer") or "", log["status"], log.get("error") or "", log["mode"],
            log.get("model") or "", round((log.get("duration_ms") or 0) / 1000, 1), total, graph, summary,
            sum(1 for s in sources if s.get("cited")), len(sources),
            log.get("tokens_in") if log.get("tokens_in") is not None else "",
            log.get("tokens_out") if log.get("tokens_out") is not None else "",
            ", ".join(a.get("filename", "") for a in log.get("attachments") or []),
            log["log_id"], log.get("run_id") or "",
        ])
    return buffer.getvalue()
