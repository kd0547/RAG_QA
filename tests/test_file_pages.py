"""파일 검수: 페이지 텍스트 저장·조회·수정(그 페이지만 다시 청킹·임베딩)을 확인한다.

임시 SQLite DB를 쓰고, Chroma와 임베딩 모델은 가짜로 바꾼다.
"""

import importlib.util
from pathlib import Path
import sys
from types import ModuleType

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from entity.file import create_file  # noqa: E402
from parser.pdf.type import PageText  # noqa: E402
from repository.file_page_repository import FilePageRepository  # noqa: E402
from repository.file_repository import FileRepository  # noqa: E402
from repository.repo_connect import Database  # noqa: E402
from retrieval.type import EmbeddedChunk  # noqa: E402


@pytest.fixture
def env(tmp_path, monkeypatch):
    db = Database(str(tmp_path / "pages.db"))
    file_repo = FileRepository(db)
    page_repo = FilePageRepository(db)
    uploads = tmp_path / "uploads"
    (uploads / "abc").mkdir(parents=True)
    original = uploads / "abc" / "doc.pdf"
    original.write_bytes(b"%PDF-1.4 original")

    file = create_file(original_name="doc.pdf", stored_path=str(original), chunk_count=3)
    file_repo.file_save(file)

    replaced = []
    repository = ModuleType("repository")
    repository.file_repo = file_repo
    repository.group_repo = ModuleType("group_repo")
    repository.page_repo = page_repo
    embeddings = ModuleType("repository.embedding_repository")
    embeddings.save_embeddings = lambda chunks: None
    embeddings.delete_embeddings = lambda file_id: None
    embeddings.update_group_metadata = lambda file_id, group_id: 0

    def replace_page_embeddings(file_id, page, chunks):
        replaced.append((file_id, page, chunks))
        return 1  # 그 페이지의 옛 청크 1개를 지웠다고 가정

    embeddings.replace_page_embeddings = replace_page_embeddings
    monkeypatch.setitem(sys.modules, "repository", repository)
    monkeypatch.setitem(sys.modules, "repository.embedding_repository", embeddings)

    spec = importlib.util.spec_from_file_location("file_pages_router_test", PROJECT_ROOT / "app" / "routers" / "files.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "UPLOAD_DIR", uploads)
    monkeypatch.setattr(module, "BASE_DIR", tmp_path)
    monkeypatch.setattr(
        module, "embed_chunks",
        lambda chunks: [EmbeddedChunk(**{**c.__dict__, "embedding": [0.1, 0.2]}) for c in chunks],
    )

    app = FastAPI()
    app.include_router(module.router)
    with TestClient(app) as client:
        yield client, file, file_repo, page_repo, replaced, module, original


def test_list_pages_in_parser_order(env):
    client, file, _, page_repo, *_ = env
    page_repo.save_pages(file.file_id, [PageText(page=1, text="첫 쪽"), PageText(page=2, text="둘째 쪽")])

    body = client.get(f"/file/{file.file_id}/pages").json()

    assert body["original_name"] == "doc.pdf"
    assert [(p["page"], p["text"], p["edited"]) for p in body["pages"]] == [(1, "첫 쪽", False), (2, "둘째 쪽", False)]
    assert client.get("/file/unknown/pages").status_code == 404


def test_edit_page_rechunks_only_that_page_and_keeps_original(env):
    client, file, file_repo, page_repo, replaced, _, original = env
    page_repo.save_pages(file.file_id, [PageText(page=1, text="첫 쪽"), PageText(page=2, text="오타 있는 쪽")])
    page2 = page_repo.list_pages(file.file_id)[1]

    response = client.put(f"/file/{file.file_id}/pages/{page2['page_id']}", json={"text": "고친 둘째 쪽"})

    assert response.status_code == 200
    saved = response.json()["page"]
    assert saved["text"] == "고친 둘째 쪽"
    assert saved["original_text"] == "오타 있는 쪽"  # 처음 파싱 결과는 그대로
    assert saved["edited"] is True
    # 2쪽만 새 청크로 갈아끼우고, 청크 ID·메타데이터는 업로드와 같은 규칙
    [(file_id, page, chunks)] = replaced
    assert (file_id, page) == (file.file_id, 2)
    assert [c.id for c in chunks] == [f"{file.file_id}-p2-c0"]
    assert chunks[0].text == "고친 둘째 쪽" and chunks[0].file_id == file.file_id
    assert file_repo.get_file_by_id(file.file_id).chunk_count == 3  # 1개 지우고 1개 추가
    assert page_repo.list_pages(file.file_id)[0]["text"] == "첫 쪽"
    assert original.read_bytes() == b"%PDF-1.4 original"  # 업로드 원본 파일은 그대로


def test_edit_block_rechunks_whole_sheet(env):
    # xlsx처럼 한 page에 블록이 여럿이면 모두 모아 다시 청킹해 청크 번호가 이어진다
    client, file, _, page_repo, replaced, *_ = env
    page_repo.save_pages(file.file_id, [PageText(page=1, text="A"), PageText(page=1, text="B")])
    block_b = page_repo.list_pages(file.file_id)[1]

    assert client.put(f"/file/{file.file_id}/pages/{block_b['page_id']}", json={"text": "B2"}).status_code == 200

    [(_, page, chunks)] = replaced
    assert page == 1
    assert [(c.chunk_index, c.text) for c in chunks] == [(0, "A"), (1, "B2")]


def test_unchanged_text_skips_reembedding(env):
    client, file, _, page_repo, replaced, *_ = env
    page_repo.save_pages(file.file_id, [PageText(page=1, text="그대로")])
    page = page_repo.list_pages(file.file_id)[0]

    assert client.put(f"/file/{file.file_id}/pages/{page['page_id']}", json={"text": "그대로"}).status_code == 200
    assert replaced == []


def test_edit_rejects_other_files_page(env):
    client, file, file_repo, page_repo, replaced, *_ = env
    other = create_file(original_name="other.pdf", stored_path="x.pdf")
    file_repo.file_save(other)
    page_repo.save_pages(other.file_id, [PageText(page=1, text="다른 파일")])
    other_page = page_repo.list_pages(other.file_id)[0]

    assert client.put(f"/file/{file.file_id}/pages/{other_page['page_id']}", json={"text": "x"}).status_code == 404
    assert client.put(f"/file/unknown/pages/{other_page['page_id']}", json={"text": "x"}).status_code == 404
    assert replaced == []


def test_import_pages_for_old_upload(env, monkeypatch):
    client, file, _, page_repo, replaced, module, original = env
    parsed = []
    monkeypatch.setattr(module, "parse_file", lambda path: parsed.append(path) or [PageText(page=1, text="다시 파싱")])

    response = client.post(f"/file/{file.file_id}/pages/import")

    assert response.status_code == 200
    assert [p["text"] for p in response.json()["pages"]] == ["다시 파싱"]
    assert parsed == [original.resolve()]
    assert replaced == []  # 가져오기만으로는 검색 청크를 바꾸지 않는다
    assert client.post(f"/file/{file.file_id}/pages/import").status_code == 409


def test_deleting_file_removes_pages(env):
    client, file, _, page_repo, *_ = env
    page_repo.save_pages(file.file_id, [PageText(page=1, text="쪽")])

    assert client.delete(f"/file/{file.file_id}").status_code == 200
    assert page_repo.list_pages(file.file_id) == []


def test_edit_and_import_schedule_graph_extraction(env, monkeypatch):
    client, file, _, page_repo, _, module, _ = env
    calls = []
    monkeypatch.setattr(module, "_graph_index", lambda file_id, page=None: calls.append((file_id, page)))
    page_repo.save_pages(file.file_id, [PageText(page=1, text="첫 쪽"), PageText(page=2, text="둘째 쪽")])
    page2 = page_repo.list_pages(file.file_id)[1]

    assert client.put(f"/file/{file.file_id}/pages/{page2['page_id']}", json={"text": "고친 둘째 쪽"}).status_code == 200
    # 바뀌지 않은 저장은 다시 뽑지 않는다
    assert client.put(f"/file/{file.file_id}/pages/{page2['page_id']}", json={"text": "고친 둘째 쪽"}).status_code == 200
    assert calls == [(file.file_id, 2)]

    monkeypatch.setattr(module.config, "GRAPH_EXTRACT_ENABLED", False)
    assert client.put(f"/file/{file.file_id}/pages/{page2['page_id']}", json={"text": "또 고침"}).status_code == 200
    assert calls == [(file.file_id, 2)]
