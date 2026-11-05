"""문서 업로드 결과와 원본 파일 보존을 확인한다."""

import importlib.util
from pathlib import Path
import sys
from tempfile import SpooledTemporaryFile
from types import ModuleType, SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile

from entity.file import create_file
from retrieval.type import Chunk, EmbeddedChunk


class MemoryFileRepository:
    def __init__(self):
        self.files = {}

    def exists_by_sha256(self, sha256):
        return any(file.sha256 == sha256 for file in self.files.values())

    def file_save(self, file):
        self.files[file.file_id] = file

    def get_file_by_id(self, file_id):
        return self.files.get(file_id)

    def has_other_stored_path(self, stored_path, file_id):
        return any(
            file.stored_path == stored_path and file.file_id != file_id
            for file in self.files.values()
        )

    def delete_file(self, file_id):
        self.files.pop(file_id, None)

    def update_description(self, file_id, description):
        file = self.files.get(file_id)
        if file is None:
            return False
        file.description = description
        return True


@pytest.fixture
def upload_router(tmp_path, monkeypatch):
    """라우터를 임시 업로드 폴더와 가짜 파서·임베딩 저장소로 실행한다."""
    project_root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(project_root))
    file_repo = MemoryFileRepository()
    saved_chunks = []
    repository = ModuleType("repository")
    repository.file_repo = file_repo
    repository.group_repo = SimpleNamespace(exists=lambda group_id: True)
    embeddings = ModuleType("repository.embedding_repository")
    def save_embeddings(chunks):
        saved_chunks.append(chunks)
        return tmp_path / "vectors.json"

    embeddings.save_embeddings = save_embeddings
    embeddings.delete_embeddings = lambda file_id: None
    embeddings.update_group_metadata = lambda file_id, group_id: 0
    monkeypatch.setitem(sys.modules, "repository", repository)
    monkeypatch.setitem(sys.modules, "repository.embedding_repository", embeddings)

    spec = importlib.util.spec_from_file_location(
        "file_upload_router_test", project_root / "app" / "routers" / "files.py",
    )
    router_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(router_module)
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    monkeypatch.setattr(router_module, "BASE_DIR", tmp_path)
    monkeypatch.setattr(router_module, "UPLOAD_DIR", uploads)
    monkeypatch.setattr(router_module, "parse_file", lambda path: [])
    monkeypatch.setattr(router_module, "chunk_pages", lambda path, pages, file_id, group_id: [
        Chunk(
            id=f"{Path(path).stem}-p1-c0",
            source=str(path),
            page=1,
            chunk_index=0,
            text="문서 내용",
            file_id=file_id,
            group_id=group_id,
        ),
    ])
    monkeypatch.setattr(router_module, "embed_chunks", lambda chunks: [
        EmbeddedChunk(**vars(chunk), embedding=[0.0, 1.0]) for chunk in chunks
    ])

    return router_module, file_repo, uploads, saved_chunks


def _upload(router_module, *files, descriptions=None):
    """메모리 안의 UploadFile은 await read()에서 대기하지 않아 루프 없이 실행할 수 있다."""
    uploads = []
    for name, content in files:
        stream = SpooledTemporaryFile(max_size=1024 * 1024)
        stream.write(content)
        stream.seek(0)
        uploads.append(UploadFile(file=stream, filename=name))
    coroutine = router_module.upload_files(uploads, group_id=None, descriptions=descriptions)
    try:
        try:
            coroutine.send(None)
        except StopIteration as done:
            return done.value
        raise AssertionError("업로드가 외부 비동기 작업을 기다렸습니다.")
    finally:
        for upload in uploads:
            upload.file.close()


def test_duplicate_upload_has_result_for_each_file(upload_router):
    router_module, file_repo, uploads, saved_chunks = upload_router

    response = _upload(router_module,
        ("original.pdf", b"same content"),
        ("copy.pdf", b"same content"),
    )

    results = response["results"]
    assert len(results) == 2
    assert results[0]["filename"] == "original.pdf"
    assert results[0]["num_chunks"] == 1
    assert results[1] == {"filename": "copy.pdf", "skipped": "duplicate"}
    assert len(file_repo.files) == 1
    assert len(saved_chunks) == 1
    assert len(list(uploads.rglob("*.pdf"))) == 1


def test_same_name_uploads_keep_both_originals(upload_router):
    router_module, file_repo, uploads, saved_chunks = upload_router

    first = _upload(router_module, ("report.pdf", b"first version"))
    second = _upload(router_module, ("report.pdf", b"second version"))

    assert first["results"][0]["num_chunks"] == 1
    assert second["results"][0]["num_chunks"] == 1
    assert len(file_repo.files) == 2
    stored = list(file_repo.files.values())
    assert {file.original_name for file in stored} == {"report.pdf"}
    assert stored[0].stored_path != stored[1].stored_path
    assert Path(stored[0].stored_path).read_bytes() == b"first version"
    assert Path(stored[1].stored_path).read_bytes() == b"second version"
    assert len(list(uploads.rglob("*.pdf"))) == 2
    assert saved_chunks[0][0].id != saved_chunks[1][0].id
    assert router_module.preview_file(stored[0].file_id).path == Path(stored[0].stored_path)
    assert router_module.preview_file(stored[1].file_id).path == Path(stored[1].stored_path)


def test_delete_removes_only_the_selected_original(upload_router):
    router_module, file_repo, uploads, _ = upload_router
    _upload(router_module, ("report.pdf", b"first version"))
    _upload(router_module, ("report.pdf", b"second version"))
    first, second = list(file_repo.files.values())
    first_path = Path(first.stored_path)
    second_path = Path(second.stored_path)

    assert router_module.delete_file(first.file_id) == {"message": "File deleted successfully"}

    assert first.file_id not in file_repo.files
    assert not first_path.exists()
    assert not first_path.parent.exists()
    assert second_path.read_bytes() == b"second version"
    assert len(list(uploads.rglob("*.pdf"))) == 1


def test_delete_preserves_outside_and_shared_originals(upload_router, tmp_path):
    router_module, file_repo, uploads, _ = upload_router
    outside = tmp_path / "private.pdf"
    outside.write_bytes(b"private")
    outside_file = create_file(original_name="private.pdf", stored_path=str(outside), sha256="outside")
    file_repo.file_save(outside_file)
    router_module.delete_file(outside_file.file_id)
    assert outside.read_bytes() == b"private"

    shared_path = uploads / "legacy.pdf"
    shared_path.write_bytes(b"shared")
    first = create_file(original_name="legacy.pdf", stored_path=str(shared_path), sha256="first")
    second = create_file(original_name="legacy.pdf", stored_path=str(shared_path), sha256="second")
    file_repo.file_save(first)
    file_repo.file_save(second)

    router_module.delete_file(first.file_id)
    assert shared_path.read_bytes() == b"shared"
    router_module.delete_file(second.file_id)
    assert not shared_path.exists()


def test_upload_and_edit_each_file_description(upload_router):
    router_module, file_repo, _, _ = upload_router
    _upload(
        router_module,
        ("first.pdf", b"first"),
        ("second.pdf", b"second"),
        descriptions=["  인증서  ", "  제품 사양  "],
    )
    first, second = list(file_repo.files.values())
    assert first.description == "인증서"
    assert second.description == "제품 사양"

    updated = router_module.set_file_description(
        first.file_id,
        router_module.FileDescriptionBody(description="  안전 인증  "),
    )
    assert updated == {"file_id": first.file_id, "description": "안전 인증"}
    assert router_module.get_file_detail(first.file_id)["description"] == "안전 인증"


def test_file_description_rejects_invalid_requests(upload_router):
    router_module, _, _, _ = upload_router
    with pytest.raises(HTTPException) as mismatch:
        _upload(router_module, ("first.pdf", b"first"), descriptions=["one", "two"])
    assert mismatch.value.status_code == 400

    with pytest.raises(HTTPException) as too_long:
        _upload(router_module, ("first.pdf", b"first"), descriptions=["a" * 501])
    assert too_long.value.status_code == 400

    with pytest.raises(HTTPException) as missing:
        router_module.set_file_description(
            "missing",
            router_module.FileDescriptionBody(description="설명"),
        )
    assert missing.value.status_code == 404
