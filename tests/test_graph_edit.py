"""문서 그래프 편집: 사람이 넣은 관계는 다시 뽑아도 남고, 지운 관계는 되살아나지 않는다.

임시 SQLite DB를 쓴다. API 테스트는 그래프 라우터의 저장소를 임시 DB 것으로 바꾼다.
"""
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
if not hasattr(sys.modules.get("parser"), "__path__"):
    sys.modules.pop("parser", None)

from app.routers import graph as graph_router  # noqa: E402
from entity.file import create_file  # noqa: E402
from graph_rag import service  # noqa: E402
from graph_rag.types import ExtractedEntity, ExtractedRelation, PageGraph  # noqa: E402
from repository.file_repository import FileRepository  # noqa: E402
from repository.graph_repository import GraphEditError, GraphRepository  # noqa: E402
from repository.repo_connect import Database  # noqa: E402

KC = {"KC 인증": ["안전확인 신고", "적합성 등록"]}


def _e(type_, name, *aliases, concept=None):
    return ExtractedEntity(type=type_, name=name, aliases=list(aliases), concept=concept)


def _r(source, type_, target):
    return ExtractedRelation(source=source, type=type_, target=target)


A650_PAGE = PageGraph(
    entities=[_e("product", "A650"), _e("component", "RTX 5070"), _e("cert_number", "A600")],
    relations=[_r("A650", "has_component", "RTX 5070"), _r("A650", "has_number", "A600")],
)


@pytest.fixture
def env(tmp_path, monkeypatch):
    db = Database(str(tmp_path / "graph.db"))
    files, graph = FileRepository(db), GraphRepository(db)
    monkeypatch.setattr(service, "graph_repo", graph)

    def add_file(name):
        file = create_file(original_name=name, stored_path=str(tmp_path / name))
        files.file_save(file)
        return file

    return files, graph, add_file


def _id(graph, type_, name):
    return next(e["id"] for e in graph.list_entities(type_) if e["name"] == name)


def _relations(graph, entity_id):
    return {(r["source_name"], r["type"], r["target_name"], r["origin"]) for r in graph.get_entity(entity_id)["relations"]}


def test_deleted_relation_stays_deleted_after_reextract(env):
    _, graph, add_file = env
    file = add_file("a650.docx")
    graph.replace_page(file.file_id, 1, A650_PAGE)
    a650 = _id(graph, "product", "A650")
    wrong = next(r for r in graph.get_entity(a650)["relations"] if r["target_name"] == "A600")

    assert graph.delete_relation(wrong["id"]) == 1
    graph.replace_page(file.file_id, 1, A650_PAGE)  # 같은 내용으로 다시 뽑아도

    assert _relations(graph, a650) == {("A650", "has_component", "RTX 5070", "extract")}
    assert graph.stats()["blocked_relations"] == 1


def test_manual_relation_survives_reextract_and_readding_unblocks(env):
    _, graph, add_file = env
    file = add_file("a650.docx")
    graph.replace_page(file.file_id, 1, A650_PAGE)
    a650 = _id(graph, "product", "A650")
    wrong = next(r for r in graph.get_entity(a650)["relations"] if r["target_name"] == "A600")
    graph.delete_relation(wrong["id"])

    graph.add_relation(a650, "has_certification", new_target=("certification", "KC 안전확인"))
    graph.add_relation(a650, "has_number", target_id=_id(graph, "cert_number", "A600"), file_id=file.file_id, page=1)
    graph.delete_file(file.file_id)  # 파일 전체를 다시 뽑기 직전 상태
    graph.replace_page(file.file_id, 1, A650_PAGE)

    assert _relations(graph, a650) == {
        ("A650", "has_component", "RTX 5070", "extract"),
        ("A650", "has_certification", "KC 안전확인", "manual"),
        ("A650", "has_number", "A600", "manual"),
    }
    assert graph.stats()["blocked_relations"] == 0  # 다시 넣은 관계는 차단이 풀린다


def test_manual_relation_with_evidence_goes_with_the_file(env):
    files, graph, add_file = env
    file = add_file("a650.docx")
    graph.replace_page(file.file_id, 1, A650_PAGE)
    a650 = _id(graph, "product", "A650")
    graph.add_relation(a650, "has_certification", new_target=("certification", "KC 안전확인"), file_id=file.file_id, page=1)
    graph.add_relation(a650, "complies_with", new_target=("standard", "KN 32"))  # 근거 문서 없음

    files.delete_file(file.file_id)
    graph.prune_orphans()

    assert _relations(graph, a650) == {("A650", "complies_with", "KN 32", "manual")}


def test_update_relation_reverses_and_changes_type(env):
    _, graph, add_file = env
    file = add_file("a650.docx")
    graph.replace_page(file.file_id, 1, A650_PAGE)
    a650 = _id(graph, "product", "A650")
    relation = next(r for r in graph.get_entity(a650)["relations"] if r["target_name"] == "A600")

    updated = graph.update_relation(relation["id"], rel_type="has_component", reverse=False)
    assert (updated["type"], updated["origin"], updated["file_id"], updated["page"]) == ("has_component", "manual", file.file_id, 1)

    flipped = graph.update_relation(updated["id"], reverse=True)
    assert (flipped["source_name"], flipped["target_name"]) == ("A600", "A650")

    graph.replace_page(file.file_id, 1, A650_PAGE)
    assert ("A650", "has_number", "A600", "extract") not in _relations(graph, a650)


def test_part_of_needs_concept_target(env):
    _, graph, add_file = env
    graph.seed_concepts(KC)
    file = add_file("a650.docx")
    graph.replace_page(file.file_id, 1, A650_PAGE)
    with pytest.raises(GraphEditError):
        graph.add_relation(_id(graph, "product", "A650"), "part_of", target_id=_id(graph, "component", "RTX 5070"))
    with pytest.raises(GraphEditError):
        graph.add_relation(_id(graph, "product", "A650"), "has_component", target_id=_id(graph, "product", "A650"))


def test_deleted_seed_link_is_not_reseeded(env):
    _, graph, _ = env
    graph.seed_concepts(KC)
    concept = _id(graph, "concept", "KC 인증")
    link = next(r for r in graph.get_entity(concept)["relations"] if r["source_name"] == "적합성 등록")

    graph.delete_relation(link["id"])
    graph.seed_concepts(KC)  # 서버 재시작

    assert graph.list_concepts() == [{"name": "KC 인증", "members": ["안전확인 신고"]}]


def test_rename_keeps_old_name_as_alias(env):
    _, graph, add_file = env
    file = add_file("a650.docx")
    graph.replace_page(file.file_id, 1, A650_PAGE)
    rtx = _id(graph, "component", "RTX 5070")

    renamed = graph.rename_entity(rtx, "NVIDIA GeForce RTX 5070")
    graph.replace_page(file.file_id, 1, A650_PAGE)  # 옛 이름으로 다시 뽑혀도 같은 개체

    assert renamed["name"] == "NVIDIA GeForce RTX 5070"
    assert set(renamed["aliases"]) == {"RTX 5070", "NVIDIA GeForce RTX 5070"}
    assert [e["name"] for e in graph.list_entities("component")] == ["NVIDIA GeForce RTX 5070"]
    assert graph.rename_entity(_id(graph, "product", "A650"), "A650")["name"] == "A650"  # 자기 이름은 괜찮고
    graph.add_relation(_id(graph, "product", "A650"), "has_component", new_target=("component", "Ryzen AI 7 350"))
    with pytest.raises(GraphEditError):
        graph.rename_entity(rtx, "Ryzen AI 7 350")  # 다른 개체가 쓰는 이름은 안 된다


def test_merge_moves_mentions_relations_and_future_extractions(env):
    _, graph, add_file = env
    first, second = add_file("guide.pdf"), add_file("spec.pdf")
    graph.replace_page(first.file_id, 1, PageGraph(
        entities=[_e("product", "A650 Series"), _e("component", "RTX 5070")],
        relations=[_r("A650 Series", "has_component", "RTX 5070")],
    ))
    graph.replace_page(second.file_id, 2, PageGraph(entities=[_e("product", "A650-GA70-OU01")]))
    series, model = _id(graph, "product", "A650 Series"), _id(graph, "product", "A650-GA70-OU01")

    merged = graph.merge_entities(series, model)

    assert {(m["original_name"], m["page"]) for m in merged["mentions"]} == {("guide.pdf", 1), ("spec.pdf", 2)}
    assert {(r["source_name"], r["target_name"]) for r in merged["relations"]} == {("A650-GA70-OU01", "RTX 5070")}
    graph.replace_page(first.file_id, 1, PageGraph(entities=[_e("product", "A650 Series")]))
    assert [e["name"] for e in graph.list_entities("product")] == ["A650-GA70-OU01"]


def test_view_focus_depth_and_overview_limit(env):
    _, graph, add_file = env
    graph.seed_concepts(KC)
    file = add_file("a650.docx")
    graph.replace_page(file.file_id, 1, PageGraph(
        entities=[_e("product", "A650"), _e("component", "RTX 5070"), _e("certification", "KC 안전확인", concept="KC 인증")],
        relations=[_r("A650", "has_component", "RTX 5070"), _r("A650", "has_certification", "KC 안전확인")],
    ))
    a650 = _id(graph, "product", "A650")

    one = graph.view(entity_id=a650, depth=1)
    two = graph.view(entity_id=a650, depth=2)
    assert {n["name"] for n in one["nodes"]} == {"A650", "RTX 5070", "KC 안전확인"}
    assert "KC 인증" in {n["name"] for n in two["nodes"]}
    assert all({e["source"], e["target"]} <= {n["id"] for n in two["nodes"]} for e in two["edges"])

    overview = graph.view(limit=2)
    assert len(overview["nodes"]) == 2 and overview["truncated"] is True
    by_file = graph.view(file_id=file.file_id, types=["product", "component"])
    assert {n["name"] for n in by_file["nodes"]} == {"A650", "RTX 5070"}


def test_migration_adds_origin_to_first_version_table(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        create table graph_entity (id integer primary key autoincrement, type text not null, name text not null,
                                   norm text not null, created_at text not null default current_timestamp, unique (type, norm));
        create table graph_relation (id integer primary key autoincrement, src_id integer not null, dst_id integer not null,
                                     type text not null, file_id text, page integer, created_at text not null default current_timestamp);
        insert into graph_entity (type, name, norm) values ('concept', 'KC 인증', 'kc인증'), ('certification', '안전확인', '안전확인');
        insert into graph_relation (src_id, dst_id, type) values (2, 1, 'part_of');
    """)
    conn.commit()
    conn.close()

    db = Database(str(path))

    with db.get_conn() as conn:
        assert conn.execute("SELECT origin FROM graph_relation").fetchone()[0] == "seed"


def test_api_create_update_delete(env, monkeypatch):
    _, graph, add_file = env
    monkeypatch.setattr(graph_router, "graph_repo", graph)
    app = FastAPI()
    app.include_router(graph_router.router)
    file = add_file("a650.docx")
    graph.replace_page(file.file_id, 1, A650_PAGE)
    a650 = _id(graph, "product", "A650")

    with TestClient(app) as client:
        created = client.post("/graph/relations", json={
            "source_id": a650, "type": "has_certification", "new_target": {"type": "certification", "name": "KC 적합등록"},
        })
        assert created.status_code == 201, created.text
        relation = created.json()
        assert (relation["target_name"], relation["origin"]) == ("KC 적합등록", "manual")

        assert client.patch(f"/graph/relations/{relation['id']}", json={"reverse": True}).json()["source_name"] == "KC 적합등록"
        bad = client.post("/graph/relations", json={"source_id": a650, "type": "part_of", "target_id": a650})
        assert bad.status_code == 400
        assert client.delete("/graph/relations/999999").status_code == 404

        view = client.get("/graph/view", params={"entity_id": a650}).json()
        assert {"A650", "RTX 5070", "A600", "KC 적합등록"} == {n["name"] for n in view["nodes"]}
        assert client.get("/graph/view", params={"types": "nope"}).status_code == 400
        assert {t["key"] for t in client.get("/graph/schema").json()["relation_types"]} >= {"part_of", "has_component"}
