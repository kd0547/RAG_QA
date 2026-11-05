"""PDF 미리보기: 원본 제공, 범위 요청, 미지원 형식과 잘못된 경로를 확인한다."""

import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def preview_client(tmp_path, monkeypatch):
    # 업로드 라우터만 테스트한다. 운영 DB와 Chroma에는 연결하지 않는다.
    project_root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(project_root))
    files = {}
    repository = ModuleType("repository")
    repository.file_repo = SimpleNamespace(get_file_by_id=files.get)
    repository.group_repo = SimpleNamespace(exists=lambda group_id: False)
    embeddings = ModuleType("repository.embedding_repository")
    embeddings.save_embeddings = lambda chunks: None
    embeddings.delete_embeddings = lambda file_id: None
    embeddings.update_group_metadata = lambda file_id, group_id: 0
    monkeypatch.setitem(sys.modules, "repository", repository)
    monkeypatch.setitem(sys.modules, "repository.embedding_repository", embeddings)

    spec = importlib.util.spec_from_file_location(
        "file_preview_router_test", project_root / "app" / "routers" / "files.py",
    )
    router_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(router_module)
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    monkeypatch.setattr(router_module, "UPLOAD_DIR", uploads)
    monkeypatch.setattr(router_module, "BASE_DIR", tmp_path)

    app = FastAPI()
    app.include_router(router_module.router)
    with TestClient(app) as client:
        yield client, files, uploads


def test_pdf_preview_inline_and_range(preview_client):
    client, files, uploads = preview_client
    content = b"%PDF-1.4\npreview test\n%%EOF"
    path = uploads / "sample.PDF"
    path.write_bytes(content)
    files["pdf"] = SimpleNamespace(original_name="검토 문서.PDF", stored_path="uploads/sample.PDF")

    response = client.get("/file/pdf/preview")

    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith("inline;")
    partial = client.get("/file/pdf/preview", headers={"Range": "bytes=0-7"})
    assert partial.status_code == 206
    assert partial.content == content[:8]


def test_pdf_preview_unknown_or_missing_file(preview_client):
    client, files, uploads = preview_client
    assert client.get("/file/unknown/preview").status_code == 404
    files["missing"] = SimpleNamespace(original_name="missing.pdf", stored_path=str(uploads / "missing.pdf"))
    assert client.get("/file/missing/preview").status_code == 404


def test_preview_rejects_non_pdf(preview_client):
    client, files, uploads = preview_client
    files["office"] = SimpleNamespace(original_name="report.docx", stored_path=str(uploads / "report.docx"))
    assert client.get("/file/office/preview").status_code == 415


def test_preview_cannot_serve_outside_uploads(preview_client):
    client, files, uploads = preview_client
    outside = uploads.parent / "private.pdf"
    outside.write_bytes(b"private content")
    files["outside"] = SimpleNamespace(original_name="private.pdf", stored_path=str(outside))
    assert client.get("/file/outside/preview").status_code == 404


def test_file_detail_for_non_pdf(preview_client):
    client, files, uploads = preview_client
    metadata = {
        "file_id": "office",
        "original_name": "report.docx",
        "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "size_bytes": 2048,
        "chunk_count": 12,
        "created_at": "2026-10-27 09:00:00",
        "updated_at": "2026-10-27 09:00:00",
        "group_id": "report",
        "description": "",
    }
    files["office"] = SimpleNamespace(**metadata, stored_path=str(uploads / "report.docx"))

    response = client.get("/file/office")

    assert response.status_code == 200
    assert response.json() == metadata
    assert "stored_path" not in response.json()


def test_file_detail_unknown_file(preview_client):
    client, _, _ = preview_client
    assert client.get("/file/unknown").status_code == 404
