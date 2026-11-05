"""문서 그룹: 기본 그룹 등록, 파일 그룹 변경, 청크 메타데이터 전파, 그룹 API를 확인한다."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from entity.file import create_file  # noqa: E402
from entity.group import DEFAULT_GROUPS, GROUP_IDS  # noqa: E402
from parser.pdf.type import PageText  # noqa: E402
from repository.file_page_repository import FilePageRepository  # noqa: E402
from repository.file_repository import FileRepository  # noqa: E402
from repository.group_repository import GroupRepository  # noqa: E402
from repository.repo_connect import Database  # noqa: E402
from retrieval.chunker import chunk_pages  # noqa: E402
from retrieval.embedder import embed_chunks, set_embedding_model  # noqa: E402


@pytest.fixture
def repos(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    return FileRepository(db), GroupRepository(db)


def _file(name: str, group_id: str | None = None):
    return create_file(original_name=name, stored_path=f"uploads/{name}", sha256=name, group_id=group_id)


# ---------- 저장소 ----------

def test_ensure_defaults_inserts_once_and_keeps_edits(repos):
    _, group_repo = repos

    assert group_repo.ensure_defaults() == len(DEFAULT_GROUPS)
    assert group_repo.ensure_defaults() == 0  # 두 번째는 아무것도 안 넣는다

    groups = group_repo.list_all()
    assert [g["id"] for g in groups] == [g.id for g in DEFAULT_GROUPS]  # 코드에 적은 순서
    assert all(g["file_count"] == 0 for g in groups)
    assert all(group_repo.exists(gid) for gid in GROUP_IDS)
    assert not group_repo.exists("nope")


def test_list_all_counts_files_per_group(repos):
    file_repo, group_repo = repos
    group_repo.ensure_defaults()
    file_repo.file_save(_file("kc1.pdf", "certificate"))
    file_repo.file_save(_file("kc2.pdf", "certificate"))
    file_repo.file_save(_file("guide.pdf", "sales"))
    file_repo.file_save(_file("unsorted.pdf"))

    counts = {g["id"]: g["file_count"] for g in group_repo.list_all()}

    assert counts["certificate"] == 2
    assert counts["sales"] == 1
    assert counts["general"] == 0  # 미분류는 일반 문서가 아니다


def test_update_group_moves_file_and_clears_it(repos):
    file_repo, group_repo = repos
    group_repo.ensure_defaults()
    file = _file("spec.docx")
    file_repo.file_save(file)

    assert file_repo.update_group([file.file_id], "product_spec") == 1
    assert file_repo.get_file_by_id(file.file_id).group_id == "product_spec"
    assert file_repo.file_list()[0]["group_id"] == "product_spec"

    assert file_repo.update_group([file.file_id], None) == 1
    assert file_repo.get_file_by_id(file.file_id).group_id is None


# ---------- 청크 메타데이터 ----------

class _FakeEmbedding:
    def embed_documents(self, texts):
        return [[0.0, 1.0] for _ in texts]

    def embed_query(self, text):
        return [0.0, 1.0]


def test_group_id_flows_from_chunks_to_embedded_chunks():
    pages = [PageText(page=1, text="첫 페이지"), PageText(page=2, text="둘째 페이지")]

    chunks = chunk_pages("docs/a.pdf", pages, file_id="f1", group_id="manual")
    assert {c.group_id for c in chunks} == {"manual"}

    set_embedding_model(_FakeEmbedding())
    embedded = embed_chunks(chunks)
    assert {c.group_id for c in embedded} == {"manual"}

    # 그룹 없이 만들면 None이다 (저장소가 빈 문자열로 바꿔 Chroma에 넣는다)
    assert {c.group_id for c in chunk_pages("docs/a.pdf", pages, file_id="f1")} == {None}


# ---------- API ----------

@pytest.fixture
def api_client(tmp_path, monkeypatch):
    """파일·그룹 라우터를 임시 DB와 가짜 Chroma로 띄운다."""
    db = Database(str(tmp_path / "api.db"))
    file_repo = FileRepository(db)
    group_repo = GroupRepository(db)
    group_repo.ensure_defaults()

    metadata_calls: list[tuple[str, str | None]] = []
    repository = ModuleType("repository")
    repository.file_repo = file_repo
    repository.group_repo = group_repo
    repository.page_repo = FilePageRepository(db)
    embeddings = ModuleType("repository.embedding_repository")
    embeddings.save_embeddings = lambda chunks: None
    embeddings.delete_embeddings = lambda file_id: None
    embeddings.replace_page_embeddings = lambda file_id, page, chunks: 0
    embeddings.update_group_metadata = lambda file_id, group_id: metadata_calls.append((file_id, group_id)) or 3
    monkeypatch.setitem(sys.modules, "repository", repository)
    monkeypatch.setitem(sys.modules, "repository.embedding_repository", embeddings)

    app = FastAPI()
    for module_name in ("files", "group"):
        spec = importlib.util.spec_from_file_location(
            f"{module_name}_router_group_test", PROJECT_ROOT / "app" / "routers" / f"{module_name}.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        app.include_router(module.router)

    with TestClient(app) as client:
        yield client, file_repo, metadata_calls


def test_list_groups_endpoint(api_client):
    client, _, _ = api_client

    response = client.get("/groups")

    assert response.status_code == 200
    body = response.json()
    assert [g["id"] for g in body] == [g.id for g in DEFAULT_GROUPS]
    first = body[0]
    assert (first["id"], first["name"], first["description"], first["file_count"]) == ("product_spec", "제품 사양", DEFAULT_GROUPS[0].description, 0)


def test_set_file_group_updates_db_and_chunks(api_client):
    client, file_repo, metadata_calls = api_client
    file = _file("kc.pdf")
    file_repo.file_save(file)

    response = client.put(f"/file/{file.file_id}/group", json={"group_id": "certificate"})

    assert response.status_code == 200
    assert response.json() == {"file_id": file.file_id, "group_id": "certificate", "updated_chunks": 3}
    assert file_repo.get_file_by_id(file.file_id).group_id == "certificate"
    assert metadata_calls == [(file.file_id, "certificate")]

    # 미분류로 되돌리기
    assert client.put(f"/file/{file.file_id}/group", json={"group_id": None}).status_code == 200
    assert file_repo.get_file_by_id(file.file_id).group_id is None
    assert metadata_calls[-1] == (file.file_id, None)


def test_set_file_group_rejects_unknown_group_or_file(api_client):
    client, file_repo, metadata_calls = api_client
    file = _file("x.pdf")
    file_repo.file_save(file)

    assert client.put(f"/file/{file.file_id}/group", json={"group_id": "nope"}).status_code == 400
    assert client.put("/file/missing/group", json={"group_id": "sales"}).status_code == 404
    assert metadata_calls == []  # 거부됐으면 Chroma는 건드리지 않는다


def test_file_detail_includes_group(api_client):
    client, file_repo, _ = api_client
    file = _file("guide.pdf", "sales")
    file_repo.file_save(file)

    body = client.get(f"/file/{file.file_id}").json()

    assert body["group_id"] == "sales"
    assert body["description"] == ""
    assert "stored_path" not in body


def test_upload_rejects_unknown_group(api_client):
    client, _, _ = api_client

    response = client.post("/upload", data={"group_id": "nope"}, files=[("files", ("a.pdf", b"%PDF-1.4", "application/pdf"))])

    assert response.status_code == 400


def test_set_files_group_bulk(api_client):
    client, file_repo, metadata_calls = api_client
    a, b = _file("a.pdf"), _file("b.pdf", "sales")
    file_repo.file_save(a)
    file_repo.file_save(b)

    response = client.put("/files/group", json={"file_ids": [a.file_id, b.file_id, a.file_id, "missing"], "group_id": "certificate"})

    assert response.status_code == 200
    assert response.json() == {"updated": 2, "group_id": "certificate", "updated_chunks": 9}  # 중복·없는 id 제외, 청크 3건씩
    assert file_repo.get_file_by_id(a.file_id).group_id == "certificate"
    assert file_repo.get_file_by_id(b.file_id).group_id == "certificate"
    assert [c[1] for c in metadata_calls] == ["certificate"] * 3

    assert client.put("/files/group", json={"file_ids": [], "group_id": "sales"}).status_code == 400
    assert client.put("/files/group", json={"file_ids": [a.file_id], "group_id": "nope"}).status_code == 400
