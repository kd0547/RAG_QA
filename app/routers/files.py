"""문서 업로드 라우터.

업로드: 파싱 -> 페이지 텍스트 저장 (검수 대기, 검색에 쓰이지 않음)
검수 완료: 페이지 텍스트 -> 청킹 -> 임베딩 -> 벡터 저장 -> 그래프 추출(백그라운드)
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

import config
from entity.file import create_file
from repository import file_repo, group_repo, page_repo
from retrieval.embedder import embed_chunks
from parser.file_parser import SUPPORTED_EXTENSIONS, parse_file
from retrieval.chunker import chunk_pages, dump_chunks_markdown
from repository.embedding_repository import (
    delete_embeddings,
    replace_page_embeddings,
    save_embeddings,
    update_group_metadata,
)
from parser.pdf.type import PageText
from retrieval.type import Chunk

logger = logging.getLogger(__name__)

router = APIRouter(

)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
UPLOAD_DIR = BASE_DIR / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _safe_filename(filename: str) -> str:
    name = Path(filename).name  # 경로 조작 방지
    name = re.sub(r"[^\w.\-]+", "_", name)
    return name or "upload"


def _uploaded_original_path(stored_path: str) -> Path | None:
    """업로드 폴더 안의 일반 파일만 원본 삭제 대상으로 허용한다."""
    candidate = Path(stored_path)
    if not candidate.is_absolute():
        candidate = BASE_DIR / candidate
    if candidate.is_symlink():
        return None
    path = candidate.resolve()
    upload_root = UPLOAD_DIR.resolve()
    return path if path.is_relative_to(upload_root) and path.is_file() else None


def _remove_uploaded_original(stored_path: str) -> None:
    path = _uploaded_original_path(stored_path)
    if path is None:
        return
    try:
        path.unlink()
    except OSError:
        logger.exception("업로드 원본 삭제 실패: %s", path)
        return

    # 새 업로드의 고유 폴더가 비었다면 함께 치운다. 옛 업로드의 공용 폴더는 유지한다.
    upload_root = UPLOAD_DIR.resolve()
    if path.parent.parent == upload_root and re.fullmatch(r"[0-9a-f]{32}", path.parent.name):
        try:
            path.parent.rmdir()
        except OSError:
            pass


# ---------- 문서 그래프 동기화 ----------
# 그래프 추출은 페이지마다 LLM을 부르므로 응답을 보낸 뒤 백그라운드로 돈다. 실패해도 업로드·검수는 성공으로 둔다.

def _graph_index(file_id: str, page: int | None = None) -> None:
    try:
        from graph_rag.service import index_file, index_page
        if page is None:
            index_file(file_id)
        else:
            index_page(file_id, page)
    except Exception:
        logger.warning("문서 그래프 추출 실패: file_id=%s, page=%s", file_id, page, exc_info=True)


def _schedule_graph_index(background: BackgroundTasks | None, file_id: str, page: int | None = None) -> None:
    if config.GRAPH_EXTRACT_ENABLED and background is not None:
        background.add_task(_graph_index, file_id, page)


def _graph_prune() -> None:
    try:
        from repository import graph_repo
        graph_repo.prune_orphans()
    except Exception:
        logger.warning("문서 그래프 정리 실패", exc_info=True)


@router.delete("/file/{file_id}")
def delete_file(file_id:str):
    """

    :param id:
    :return:
    """

    file = file_repo.get_file_by_id(file_id)
    if file is None:
        raise HTTPException(status_code=404, detail="File not found")

    shared_original = file_repo.has_other_stored_path(file.stored_path, file_id)
    file_repo.delete_file(file_id)
    delete_embeddings(file_id)
    _graph_prune()  # 파일의 개체 등장·관계는 외래키로 지워졌고, 남은 빈 개체를 치운다
    if not shared_original:
        _remove_uploaded_original(file.stored_path)
    logger.info("문서 삭제: file_id=%s, name=%s", file_id, file.original_name)

    return {"message": "File deleted successfully"}


@router.get("/files")
def get_files():

    return file_repo.file_list()


@router.get("/file/{file_id}/preview")
def preview_file(file_id: str) -> FileResponse:
    """등록된 PDF 원본을 브라우저에서 표시한다. 업로드 폴더 안의 파일만 제공한다."""
    file = file_repo.get_file_by_id(file_id)
    if file is None:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
    if Path(file.original_name).suffix.lower() != ".pdf":
        raise HTTPException(status_code=415, detail="미리보기는 PDF만 지원합니다.")

    path = Path(file.stored_path)
    if not path.is_absolute():
        path = BASE_DIR / path
    path = path.resolve()
    if not path.is_relative_to(UPLOAD_DIR.resolve()) or not path.is_file():
        raise HTTPException(status_code=404, detail="PDF 원본 파일을 찾을 수 없습니다.")

    return FileResponse(
        path,
        media_type="application/pdf",
        filename=file.original_name,
        content_disposition_type="inline",
    )


@router.get("/file/{file_id}")
def get_file_detail(file_id: str) -> dict:
    """선택한 파일의 기본 정보를 반환한다. 서버 내부 저장 경로는 노출하지 않는다."""
    file = file_repo.get_file_by_id(file_id)
    if file is None:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
    return {
        "file_id": file.file_id,
        "original_name": file.original_name,
        "mime_type": file.mime_type,
        "size_bytes": file.size_bytes,
        "chunk_count": file.chunk_count,
        "created_at": file.created_at,
        "updated_at": file.updated_at,
        "group_id": file.group_id,
        "description": file.description,
        "review_status": file.review_status,
        "error_message": file.error_message,
    }


MAX_PAGE_TEXT = 200_000


def _chunk_ids(file_id: str, chunks: list[Chunk]) -> list[Chunk]:
    # chunk_pages의 기본 ID는 파일명 기반이라 동명 문서끼리 충돌한다. 업로드와 같은 규칙으로 바꾼다.
    for chunk in chunks:
        chunk.id = f"{file_id}-p{chunk.page}-c{chunk.chunk_index}"
    return chunks


@router.get("/file/{file_id}/pages")
def get_file_pages(file_id: str) -> dict:
    """파일 검수용: 업로드 때 저장한 페이지별 텍스트를 파서 순서대로 돌려준다."""
    file = file_repo.get_file_by_id(file_id)
    if file is None:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
    return {
        "file_id": file_id,
        "original_name": file.original_name,
        "review_status": file.review_status,
        "error_message": file.error_message,
        "pages": page_repo.list_pages(file_id),
    }


@router.post("/file/{file_id}/pages/import")
def import_file_pages(file_id: str, background: BackgroundTasks) -> dict:
    """페이지 텍스트가 없는 예전 업로드 파일용: 보관된 원본을 다시 파싱해 페이지 텍스트만 저장한다.

    검색용 청크는 바꾸지 않는다. 페이지를 고쳐 저장할 때 그 페이지만 새 텍스트로 다시 청킹된다.
    """
    file = file_repo.get_file_by_id(file_id)
    if file is None:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
    if page_repo.has_pages(file_id):
        raise HTTPException(status_code=409, detail="이미 페이지 텍스트가 저장된 파일입니다.")
    path = _uploaded_original_path(file.stored_path)
    if path is None:
        raise HTTPException(status_code=404, detail="원본 파일을 찾을 수 없습니다.")
    started = time.perf_counter()
    try:
        pages = parse_file(path)
    except Exception as exc:
        logger.exception("페이지 텍스트 가져오기 실패: file_id=%s", file_id)
        raise HTTPException(status_code=500, detail=f"원본 파싱 실패: {exc}") from exc
    page_repo.save_pages(file_id, pages)
    if file.review_status == "done":  # 검수 대기 파일은 [검수 완료] 때 뽑는다
        _schedule_graph_index(background, file_id)
    logger.info("페이지 텍스트 가져오기: file_id=%s, pages=%d, %.1f초", file_id, len(pages), time.perf_counter() - started)
    return {"file_id": file_id, "original_name": file.original_name, "pages": page_repo.list_pages(file_id)}


class PageTextBody(BaseModel):
    text: str


@router.put("/file/{file_id}/pages/{page_id}")
def set_page_text(file_id: str, page_id: int, body: PageTextBody, background: BackgroundTasks) -> dict:
    """파일 검수에서 고친 페이지 텍스트를 저장하고, 그 페이지만 다시 청킹·임베딩한다.

    검수 대기 파일은 아직 색인 전이라 텍스트만 저장한다 (chunk_count는 None). [검수 완료] 때 전체를 색인한다.
    업로드 원본 파일과 original_text(처음 파싱 결과)는 바꾸지 않는다.
    """
    file = file_repo.get_file_by_id(file_id)
    if file is None:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
    row = page_repo.get_page(file_id, page_id)
    if row is None:
        raise HTTPException(status_code=404, detail="페이지를 찾을 수 없습니다.")
    text = body.text
    if len(text) > MAX_PAGE_TEXT:
        raise HTTPException(status_code=400, detail=f"페이지 텍스트는 {MAX_PAGE_TEXT:,}자 이하여야 합니다.")
    if text == row["text"]:
        return {"page": row, "chunk_count": None}
    if file.review_status == "pending":
        page_repo.update_text(page_id, text)
        logger.info("검수 대기 페이지 저장: file_id=%s, page=%s, %d자 -> %d자", file_id, row["page"], len(row["text"]), len(text))
        return {"page": page_repo.get_page(file_id, page_id), "chunk_count": None}

    # 같은 페이지 번호의 블록을 모두 모아 다시 청킹해야 청크 번호가 업로드 때와 같은 규칙으로 이어진다
    siblings = page_repo.pages_with_number(file_id, row["page"])
    pages = [PageText(page=p["page"], text=text if p["page_id"] == page_id else p["text"]) for p in siblings]
    chunks = _chunk_ids(file_id, chunk_pages(Path(file.stored_path), pages, file_id=file_id, group_id=file.group_id))
    try:
        embedded = embed_chunks(chunks)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    removed = replace_page_embeddings(file_id, row["page"], embedded)
    page_repo.update_text(page_id, text)
    _schedule_graph_index(background, file_id, row["page"])
    if file.chunk_count is not None:
        file_repo.update_chunk_count(file_id, max(file.chunk_count - removed + len(embedded), 0))
    logger.info(
        "페이지 검수 저장: file_id=%s, page=%s, %d자 -> %d자, chunks %d -> %d",
        file_id, row["page"], len(row["text"]), len(text), removed, len(embedded),
    )
    return {"page": page_repo.get_page(file_id, page_id), "chunk_count": len(embedded)}


@router.post("/file/{file_id}/review/complete")
def complete_review(file_id: str, background: BackgroundTasks) -> dict:
    """[검수 완료]: 저장된(검수로 고친) 페이지 텍스트 전체를 청킹·임베딩해 검색에 넣고, 그래프 추출을 건다.

    실패하면 검수 대기로 남기고 error_message에 원인을 적는다. 같은 요청으로 다시 시도할 수 있다.
    """
    file = file_repo.get_file_by_id(file_id)
    if file is None:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
    if file.review_status != "pending":
        raise HTTPException(status_code=409, detail="이미 검수가 끝난 파일입니다.")

    started = time.perf_counter()
    pages = [PageText(page=p["page"], text=p["text"]) for p in page_repo.list_pages(file_id)]
    try:
        chunks = _chunk_ids(file_id, chunk_pages(Path(file.stored_path), pages, file_id=file_id, group_id=file.group_id))
        embedded = embed_chunks(chunks)
        # 앞선 시도가 벡터 저장 뒤에 실패했을 수 있으니 이 파일의 청크를 비우고 넣는다
        delete_embeddings(file_id)
        save_embeddings(embedded)
    except Exception as exc:
        logger.exception("검수 완료 색인 실패: file_id=%s", file_id)
        message = f"검색 반영 실패: {exc}"
        file_repo.set_error(file_id, message)
        status = 503 if isinstance(exc, RuntimeError) else 500
        raise HTTPException(status_code=status, detail=message) from exc

    file_repo.mark_reviewed(file_id, len(embedded))
    _schedule_graph_index(background, file_id)
    logger.info(
        "검수 완료: %s, file_id=%s, pages=%d, chunks=%d, %.1f초",
        file.original_name, file_id, len(pages), len(embedded), time.perf_counter() - started,
    )
    return {"file_id": file_id, "review_status": "done", "chunk_count": len(embedded)}


class FileGroupBody(BaseModel):
    group_id: str | None  # None이면 미분류로 돌린다


class FileDescriptionBody(BaseModel):
    description: str


def _check_group(group_id: str | None) -> None:
    if group_id is not None and not group_repo.exists(group_id):
        raise HTTPException(status_code=400, detail=f"없는 문서 그룹입니다: {group_id} (GET /groups 참고)")


@router.patch("/file/{file_id}/description")
def set_file_description(file_id: str, body: FileDescriptionBody) -> dict:
    """파일 목록에 보이는 짧은 설명을 수정한다."""
    description = body.description.strip()
    if len(description) > 500:
        raise HTTPException(status_code=400, detail="파일 설명은 500자 이하여야 합니다.")
    if not file_repo.update_description(file_id, description):
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
    return {"file_id": file_id, "description": description}


@router.put("/file/{file_id}/group")
def set_file_group(file_id: str, body: FileGroupBody) -> dict:
    """파일의 문서 그룹을 바꾼다. SQLite와 Chroma 청크 메타데이터를 같이 바꿔 검색 필터가 맞게 한다."""
    file = file_repo.get_file_by_id(file_id)
    if file is None:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
    _check_group(body.group_id)

    file_repo.update_group([file_id], body.group_id)
    updated_chunks = update_group_metadata(file_id, body.group_id)
    logger.info(
        "문서 그룹 변경: file_id=%s, name=%s, %s -> %s, chunks=%d",
        file_id, file.original_name, file.group_id, body.group_id, updated_chunks,
    )
    return {"file_id": file_id, "group_id": body.group_id, "updated_chunks": updated_chunks}


class FilesGroupBody(BaseModel):
    file_ids: list[str]
    group_id: str | None  # None이면 미분류로 돌린다


@router.put("/files/group")
def set_files_group(body: FilesGroupBody) -> dict:
    """여러 파일을 한 번에 같은 그룹으로 옮긴다. 없는 file_id는 건너뛰고 개수만 돌려준다."""
    _check_group(body.group_id)
    file_ids = list(dict.fromkeys(body.file_ids))  # 중복 제거, 순서 유지
    if not file_ids:
        raise HTTPException(status_code=400, detail="옮길 파일이 없습니다.")

    updated = file_repo.update_group(file_ids, body.group_id)
    updated_chunks = sum(update_group_metadata(file_id, body.group_id) for file_id in file_ids)
    logger.info("문서 그룹 일괄 변경: files=%d/%d -> %s, chunks=%d", updated, len(file_ids), body.group_id, updated_chunks)
    return {"updated": updated, "group_id": body.group_id, "updated_chunks": updated_chunks}


@router.post("/upload")
async def upload_files(
    files: list[UploadFile],
    group_id: Annotated[str | None, Form()] = None,
    descriptions: Annotated[list[str] | None, Form()] = None,
) -> dict:
    """여러 파일을 올린다. group_id는 소속 그룹, descriptions는 파일 순서에 맞춘 간단한 설명이다.

    파싱해서 페이지 텍스트까지만 저장하고 검수 대기로 둔다. 검색 반영(청킹·임베딩·그래프)은
    파일 검수에서 [검수 완료]를 누를 때 한다 (POST /file/{file_id}/review/complete).
    """
    if not files:
        raise HTTPException(status_code=400, detail="업로드된 파일이 없습니다.")
    group_id = group_id or None  # 폼에서 빈 문자열로 오면 미분류
    _check_group(group_id)
    if descriptions is not None and len(descriptions) != len(files):
        raise HTTPException(status_code=400, detail="파일 수와 설명 수가 일치하지 않습니다.")
    normalized_descriptions = [description.strip() for description in descriptions] if descriptions is not None else [""] * len(files)
    if any(len(description) > 500 for description in normalized_descriptions):
        raise HTTPException(status_code=400, detail="파일 설명은 500자 이하여야 합니다.")

    results = []
    for file, description in zip(files, normalized_descriptions):
        #파일 업로드
        if not file.filename or Path(file.filename).suffix.lower() not in SUPPORTED_EXTENSIONS:
            logger.info("업로드 거부(지원하지 않는 형식): %s", file.filename)
            results.append({
                "filename": file.filename,
                "error": f"지원하지 않는 파일 형식입니다. (지원: {', '.join(sorted(SUPPORTED_EXTENSIONS))})",
            })
            continue


        content = await file.read()
        started = time.perf_counter()

        try:
            sha256 = hashlib.sha256(content).hexdigest()

            if file_repo.exists_by_sha256(sha256):
                logger.info("업로드 건너뜀(같은 내용의 문서 존재): %s, sha256=%s", file.filename, sha256[:12])
                results.append({"filename": file.filename, "skipped": "duplicate"})
                continue

            safe_name = _safe_filename(file.filename)
            # 검색 근거의 파일명은 유지하고, 업로드별 폴더로 동명 원본의 덮어쓰기를 막는다.
            dest_dir = UPLOAD_DIR / uuid4().hex
            dest_dir.mkdir()
            dest_path = dest_dir / safe_name
            dest_path.write_bytes(content)

            db_file = create_file(
                original_name=safe_name,
                stored_path=str(dest_path),
                mime_type=file.content_type,
                size_bytes=len(content),
                sha256=sha256,
                group_id=group_id,
                description=description,
                # 파싱 결과(OCR 환각, 표 깨짐)를 사람이 확인하기 전에는 검색에 넣지 않는다
                review_status="pending",
                chunk_count=None,
            )

            pages = parse_file(dest_path)

        except Exception as exc:  # 개별 파일 실패는 건너뛰고 나머지는 계속 처리
            logger.exception("업로드 처리 실패: %s", file.filename)
            results.append({"filename": file.filename, "error": f"처리 실패: {exc}"})
            continue

        file_repo.file_save(db_file)
        # 검수용 페이지 텍스트. 파일 행이 먼저 있어야 외래키가 맞는다
        page_repo.save_pages(db_file.file_id, pages)
        num_chars = sum(len(p.text.strip()) for p in pages)
        logger.info(
            "문서 업로드(검수 대기): %s, file_id=%s, group=%s, pages=%d, chars=%d, size=%d, %.1f초",
            file.filename, db_file.file_id, group_id, len(pages), num_chars, len(content),
            time.perf_counter() - started,
        )

        results.append(
            {
                "filename": file.filename,
                "file_id": db_file.file_id,
                "review_status": "pending",
                "num_pages": len({p.page for p in pages}),
                "num_chars": num_chars,
            }
        )

    return {"results": results}
