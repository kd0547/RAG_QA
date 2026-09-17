"""PDF 업로드 컨트롤러: 청킹 -> 임베딩 -> 저장소 저장."""
from __future__ import annotations

import re
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile

from rag.embedder import embed_chunks
from rag.ingest import ingest_pdf,ingest_pdf_image
from repository.embedding_repository import save_embeddings

router = APIRouter()

BASE_DIR = Path(__file__).resolve().parent.parent.parent
UPLOAD_DIR = BASE_DIR / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _safe_filename(filename: str) -> str:
    name = Path(filename).name  # 경로 조작 방지
    name = re.sub(r"[^\w.\-]+", "_", name)
    return name or "upload.pdf"


@router.post("/upload")
async def upload_pdfs(files: list[UploadFile]) -> dict:
    if not files:
        raise HTTPException(status_code=400, detail="업로드된 파일이 없습니다.")

    results = []
    for file in files:
        if not file.filename or not file.filename.lower().endswith(".pdf"):
            results.append({"filename": file.filename, "error": "PDF 파일만 업로드할 수 있습니다."})
            continue

        safe_name = _safe_filename(file.filename)
        dest_path = UPLOAD_DIR / safe_name

        content = await file.read()
        dest_path.write_bytes(content)

        try:
            #chunks = ingest_pdf(dest_path)
            chunks = ingest_pdf_image(dest_path) #테스트용으로 교체
            embedded_chunks = embed_chunks(chunks)
        except Exception as exc:  # 개별 파일 실패는 건너뛰고 나머지는 계속 처리
            results.append({"filename": file.filename, "error": f"처리 실패: {exc}"})
            continue

        doc_id = dest_path.stem
        saved_path = save_embeddings(doc_id, embedded_chunks)

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
