"""GR2: 개체 종류를 DB 테이블로. 기본 종류도 고칠 수 있고, 추출 형식·편집·화면이 같은 목록을 쓴다."""
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import config
from app.routers import graph as router
from graph_rag import extractor
from graph_rag.defaults import DEFAULT_ENTITY_TYPES
from graph_rag.edit_service import GraphEditService
from graph_rag.schema import load_schema, page_graph_model
from graph_rag.types import ExtractedEntity, PageGraph
from repository.graph_repository import GraphEditError, GraphRepository
from repository.repo_connect import Database


@pytest.fixture
def env(tmp_path, monkeypatch):
    db = Database(str(tmp_path / "types.db"))
    graph = GraphRepository(db)
    monkeypatch.setattr(router, "graph_repo", graph)
    monkeypatch.setattr(config, "GRAPH_EDIT_ENABLED", True)
    app = FastAPI()
    app.include_router(router.router)
    return db, graph, GraphEditService(db), TestClient(app)


def _types(db):
    with db.get_conn() as conn:
        return {r["key"]: dict(r) for r in conn.execute("SELECT * FROM graph_entity_type")}


def _type(service, key):
    return next(t for t in service.schema()["entity_types"] if t["key"] == key)


def test_eight_defaults_inserted_once_and_user_edits_kept(tmp_path):
    path = tmp_path / "g.db"
    db = Database(str(path))
    types = _types(db)
    assert list(types) and set(types) == {t["key"] for t in DEFAULT_ENTITY_TYPES} and len(types) == 8
    assert types["spec_value"]["extract"] == 0 and types["product"]["requires_identifier"] == 1
    assert all(t["builtin"] == 1 for t in types.values())
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE graph_entity_type SET label='모델', revision=2 WHERE key='product'")
        conn.execute("DELETE FROM graph_entity_type WHERE key='standard'")

    Database(str(path))  # 서버 재시작

    again = _types(Database(str(path)))
    assert again["product"]["label"] == "모델"  # 사용자가 고친 값을 덮지 않는다
    assert "standard" not in again  # 지운 기본 종류를 되살리지 않는다


def test_builtin_type_name_description_color_editable(env):
    db, _, service, client = env
    product = _type(service, "product")
    response = client.patch("/graph/entity-types/product", json={
        "label": "판매 모델", "description": "실제로 파는 모델", "color": "#112233", "expected_revision": product["revision"]})
    assert response.status_code == 200, response.text
    assert (response.json()["label"], response.json()["color"]) == ("판매 모델", "#112233")
    assert client.patch("/graph/entity-types/product", json={"label": "x", "expected_revision": 1}).status_code == 409
    assert client.patch("/graph/entity-types/product", json={"key": "p2", "expected_revision": 2}).status_code == 400
    # 추출 프롬프트는 바뀐 설명을 그대로 쓴다
    with db.get_conn() as conn:
        prompt = extractor.build_extract_prompt(load_schema(conn))
    assert "product(판매 모델): 실제로 파는 모델" in prompt


def test_user_type_and_entity_of_that_type(env):
    _, graph, service, client = env
    created = client.post("/graph/entity-types", json={"key": "concept_user", "label": "개념", "description": "사용자 묶음"})
    assert created.status_code == 201, created.text
    assert created.json()["color"].startswith("#") and created.json()["builtin"] == 0
    assert client.post("/graph/entity-types", json={"key": "Bad-Key", "label": "x"}).status_code == 400
    assert client.post("/graph/entity-types", json={"key": "other", "label": "개념"}).status_code == 409

    entity = client.post("/graph/entities", json={"type": "concept_user", "name": "KC 인증 묶음"})
    assert entity.status_code == 201, entity.text
    assert [e["name"] for e in graph.list_entities("concept_user")] == ["KC 인증 묶음"]
    assert client.get("/graph/entities", params={"type": "concept_user"}).status_code == 200
    assert client.get("/graph/view", params={"types": "concept_user"}).status_code == 200
    # 관계 종류의 허용 종류에 새 종류 키를 쓸 수 있다
    rel = client.post("/graph/relation-types", json={"key": "custom:member", "label": "묶음 구성",
                                                      "source_entity_types": ["certification"], "target_entity_types": ["concept_user"]})
    assert rel.status_code == 201, rel.text
    assert client.post("/graph/relation-types", json={"key": "custom:bad", "label": "나쁨",
                                                      "source_entity_types": ["nope"], "target_entity_types": ["product"]}).status_code == 400


def test_extract_flag_controls_structured_output(env):
    db, _, service, _ = env
    service.execute("create_entity_type", data={"key": "concept_user", "label": "개념", "extract": True})
    with db.get_conn() as conn:
        schema = load_schema(conn)
    model = page_graph_model(schema)
    entity_enum = model.model_json_schema()["$defs"]["ExtractedEntity"]["properties"]["type"]["enum"]
    assert "concept_user" in entity_enum and "spec_value" not in entity_enum

    service.execute("update_entity_type", "concept_user", {"extract": False, "expected_revision": 1})
    with db.get_conn() as conn:
        schema = load_schema(conn)
    entity_enum = page_graph_model(schema).model_json_schema()["$defs"]["ExtractedEntity"]["properties"]["type"]["enum"]
    assert "concept_user" not in entity_enum
    # 같은 종류 목록이면 형식을 재사용한다
    assert page_graph_model(schema) is page_graph_model(schema)


def test_inactive_type_drops_from_extraction_but_entities_stay(env):
    db, graph, service, _ = env
    with db.transaction() as conn:
        conn.execute("INSERT INTO file (file_id, original_name, stored_path) VALUES ('f', 'a.pdf', 'a.pdf')")
    graph.replace_page("f", 1, PageGraph(entities=[ExtractedEntity(type="standard", name="KN 32")]))
    service.execute("update_entity_type", "standard", {"active": False, "expected_revision": 1})

    with db.get_conn() as conn:
        assert "standard" not in load_schema(conn).entity_keys
    assert [e["name"] for e in graph.list_entities("standard")] == ["KN 32"]
    assert [e["name"] for e in graph.find_entities("KN 32 규격")] == ["KN 32"]


def test_merge_type_moves_entities_and_removes_type(env):
    db, graph, service, client = env
    service.execute("create_entity_type", data={"key": "brand", "label": "브랜드"})
    service.execute("create_entity", data={"type": "brand", "name": "NVIDIA"})
    service.execute("create_entity", data={"type": "brand", "name": "Realtek"})
    existing = service.execute("create_entity", data={"type": "organization", "name": "NVIDIA"})
    service.execute("create_relation_type", data={"key": "custom:brand_of", "label": "브랜드",
                                                  "source_entity_types": ["product"], "target_entity_types": ["brand"]})

    response = client.post("/graph/entity-types/brand/merge", json={"into": "organization", "expected_revision": 1})

    assert response.status_code == 200, response.text
    assert (response.json()["moved"], response.json()["merged"]) == (1, 1)
    assert "brand" not in _types(db)
    assert sorted(e["name"] for e in graph.list_entities("organization")) == ["NVIDIA", "Realtek"]
    assert [e["id"] for e in graph.list_entities("organization") if e["name"] == "NVIDIA"] == [existing["id"]]
    rel = next(t for t in service.schema()["relation_types"] if t["key"] == "custom:brand_of")
    assert rel["target_entity_types"] == ["organization"]


def test_builtin_type_can_be_merged(env):
    db, graph, service, _ = env
    service.execute("create_entity", data={"type": "standard", "name": "KN 32"})
    service.execute("merge_entity_type", "standard", {"into": "certification", "expected_revision": 1})
    assert "standard" not in _types(db) and [e["name"] for e in graph.list_entities("certification")] == ["KN 32"]


def test_delete_type_with_entities_needs_merge(env):
    db, _, service, client = env
    service.execute("create_entity_type", data={"key": "brand", "label": "브랜드"})
    service.execute("create_entity", data={"type": "brand", "name": "Radeon"})

    response = client.delete("/graph/entity-types/brand", params={"expected_revision": 1})
    assert response.status_code == 400 and "합치기" in response.json()["detail"]["message"]

    service.execute("create_entity_type", data={"key": "empty_kind", "label": "빈 종류"})
    assert client.delete("/graph/entity-types/empty_kind", params={"expected_revision": 1}).status_code == 200
    assert "empty_kind" not in _types(db)


def test_schema_lists_types_with_projection_flag_and_counts(env):
    _, _, service, client = env
    service.execute("create_entity", data={"type": "product", "name": "N5800"})
    types = {t["key"]: t for t in client.get("/graph/schema").json()["entity_types"]}
    assert types["product"]["used_by_projection"] and not types["certification"]["used_by_projection"]
    assert types["product"]["entity_count"] == 1
    assert [t["key"] for t in client.get("/graph/entity-types").json()][:3] == ["product_line", "product", "component"]


def test_type_edits_leave_history(env):
    _, _, service, client = env
    client.post("/graph/entity-types", json={"key": "brand", "label": "브랜드"})
    client.patch("/graph/entity-types/brand", json={"active": False, "expected_revision": 1})
    actions = [c["action"] for c in client.get("/graph/changes", params={"kind": "entity_type"}).json()]
    assert actions == ["update", "create"]


def test_unknown_type_rejected_for_new_entity(env):
    _, _, service, _ = env
    with pytest.raises(GraphEditError):
        service.execute("create_entity", data={"type": "concept", "name": "KC 인증"})
