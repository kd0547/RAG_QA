"""문서 업로드 라우터: 파싱 -> 청킹 -> 임베딩 -> 저장소 저장."""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile

from entity.file import create_file
from repository import file_repo
from retrieval.embedder import embed_chunks
from parser.file_parser import SUPPORTED_EXTENSIONS, parse_file
from retrieval.chunker import chunk_pages, dump_chunks_markdown
from repository.embedding_repository import save_embeddings,delete_embeddings
from retrieval.type import Chunk
router = APIRouter(

)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
UPLOAD_DIR = BASE_DIR / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _safe_filename(filename: str) -> str:
    name = Path(filename).name  # 경로 조작 방지
    name = re.sub(r"[^\w.\-]+", "_", name)
    return name or "upload"


@router.delete("/file/{file_id}")
def delete_file(file_id:str):
    """

    :param id:
    :return:
    """

    file = file_repo.get_file_by_id(file_id)
    if file is None:
        raise HTTPException(status_code=404, detail="File not found")

    file_repo.delete_file(file_id)
    delete_embeddings(file_id)

    return {"message": "File deleted successfully"}


@router.get("/files")
def get_files():

    return file_repo.file_list()


@router.post("/upload")
async def upload_files(files: list[UploadFile]) -> dict:
    if not files:
        raise HTTPException(status_code=400, detail="업로드된 파일이 없습니다.")

    results = []
    for file in files:
        #파일 업로드
        if not file.filename or Path(file.filename).suffix.lower() not in SUPPORTED_EXTENSIONS:
            results.append({
                "filename": file.filename,
                "error": f"지원하지 않는 파일 형식입니다. (지원: {', '.join(sorted(SUPPORTED_EXTENSIONS))})",
            })
            continue


        safe_name = _safe_filename(file.filename)
        dest_path = UPLOAD_DIR / safe_name

        content = await file.read()
        dest_path.write_bytes(content)

        try:
            sha256 = hashlib.sha256(content).hexdigest()

            #파일이 이미 존재하면 건너뜀 여기서 무언가 액션을 클라이언트에 보냄(구현은 나중에)
            if file_repo.exists_by_sha256(sha256):
                continue

            db_file = create_file(
                original_name=safe_name,
                stored_path=str(dest_path),
                mime_type=file.content_type,
                size_bytes=len(content),
                sha256=sha256,
            )

            #파싱 후 청킹을 진행
            pages = parse_file(dest_path)
            chunks: list[Chunk] = chunk_pages(dest_path, pages, file_id=db_file.file_id)
            #dump_chunks_markdown(dest_path, chunks)

            db_file.chunk_count = len(chunks)

            #임베딩 된 청크를 반환
            embedded_chunks = embed_chunks(chunks)


        except Exception as exc:  # 개별 파일 실패는 건너뛰고 나머지는 계속 처리
            results.append({"filename": file.filename, "error": f"처리 실패: {exc}"})
            continue

        #임베딩 저장

        saved_path = save_embeddings(embedded_chunks)
        file_repo.file_save(db_file)


        # 응답에는 임베딩 벡터는 빼고 미리보기용 필드만 담는다
        preview_chunks = [
            {k: v for k, v in asdict(c).items() if k != "embedding"} for c in embedded_chunks
        ]

        results.append(
            {
                "filename": file.filename,
                "num_chunks": len(embedded_chunks),
                "chunks_saved_to": str(saved_path.relative_to(BASE_DIR)),
                "chunks": preview_chunks,
            }
        )

    return {"results": results}
