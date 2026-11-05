"""사용자 질문 -> LangGraph RAG 에이전트 라우터."""
from __future__ import annotations

import base64
import logging
import shutil
import time
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Form, HTTPException, UploadFile
from pydantic import BaseModel

from agent.agent import get_agent, run_agent_temp_attachments
from entity.type import Attachment
from parser.file_parser import SUPPORTED_EXTENSIONS

logger = logging.getLogger(__name__)

router = APIRouter()


class QuestionRequest(BaseModel):
    question: str
    mode: Literal['claude', 'local'] = 'local'
    rerank_top_n:int
    query_top_n:int

from agent.agent import run_agent

@router.post("/ask")
async def ask_question(payload: QuestionRequest) -> dict:
    question = payload.question.strip()
    mode = payload.mode
    query_top_n = payload.query_top_n
    rerank_top_n = payload.rerank_top_n
    if not question:
        raise HTTPException(status_code=400, detail="질문을 입력해주세요.")

    user_message = question
    #if query_top_n or rerank_top_n:
    #    user_message += (
    #        f"\n\n(참고: 검색 시 top_k는 {query_top_n or 5}, "
    #        f"리랭킹 시 top_n은 {rerank_top_n or 3}을 기본값으로 사용하세요.)"
    #    )

    started = time.perf_counter()
    logger.debug("질문 수신: mode=%s, question=%s", mode, question[:200])
    try:
        result = run_agent(user_message, mode)
    except RuntimeError as exc:
        # 모델 미로드 등. 클라이언트에는 503만 가므로 원인을 남긴다
        logger.warning("질문 처리 불가(503): mode=%s, %s", mode, exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    sources = [
        {"source": doc["source"], "page": doc["page"], "text": doc["text"]}
        for doc in result["sources"]
    ]

    logger.info(
        "질문 응답 완료: mode=%s, question_len=%d, answer_len=%d, sources=%d, %.1f초",
        mode, len(question), len(str(result["answer"])), len(sources), time.perf_counter() - started,
    )

    return {
        "question": question,
        "answer": result["answer"],
        "sources": sources,
    }


# ---------- 첨부가 있는 질문 (POST /ask/attachments, multipart) ----------
# 화면에서 사양서·캡처 같은 파일을 질문에 붙여 보낸다. 문서 저장소에 올리지 않고 그 질문에만 쓴다.
# 메일 수신부(mail/email_receiver.py)와 같은 Attachment 형태로 만들어 run_agent_temp_attachments 에 넘긴다.
#   - 이미지: data URL 로 모델에 직접 보여준다 (VLM)
#   - 그 외 문서(pdf/docx/pptx/xlsx/hwp/hwpx): 임시 폴더에 저장 → 에이전트가 parse_file 로 텍스트를 뽑는다 → 응답 후 삭제

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
    question: Annotated[str, Form()],
    mode: Annotated[Literal["claude", "local"], Form()] = "local",
    query_top_n: Annotated[int, Form()] = 5,
    rerank_top_n: Annotated[int, Form()] = 3,
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
        try:
            result = run_agent_temp_attachments(question, mode, attachments=attachments)
        except RuntimeError as exc:
            logger.warning("첨부 질문 처리 불가(503): mode=%s, %s", mode, exc)
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    sources = [
        {"source": doc["source"], "page": doc["page"], "text": doc["text"]}
        for doc in result["sources"]
    ]
    logger.info(
        "첨부 질문 응답 완료: mode=%s, attachments=%d, question_len=%d, answer_len=%d, sources=%d, %.1f초",
        mode, len(attachments), len(question), len(str(result["answer"])), len(sources), time.perf_counter() - started,
    )
    return {
        "question": question,
        "answer": result["answer"],
        "sources": sources,
        "attachments": [{"filename": a.filename, "type": a.type} for a in attachments],
    }
