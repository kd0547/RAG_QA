"""GR5: 사람은 모든 것을 고칠 수 있다. 규칙은 경고로만 보인다. 사양 DB에서 온 노드·관계도 고치고 재투영 뒤에도 유지된다."""
import sys

import pytest

if not hasattr(sys.modules.get("parser"), "__path__"):
    sys.modules.pop("parser", None)

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import config  # noqa: E402
import repository  # noqa: E402
from app.routers import graph as router  # noqa: E402
from graph_rag.types import ExtractedEntity as E, ExtractedRelation as R, PageGraph  # noqa: E402
from repository.graph_repository import GraphRepository  # noqa: E402
from repository.repo_connect import Database  # noqa: E402
from repository.spec_repository import SpecRepository  # noqa: E402


@pytest.fixture
def env(tmp_path, monkeypatch):
    db = Database(str(tmp_path / "free.db"))
    graph, spec = GraphRepository(db), SpecRepository(db)
    monkeypatch.setattr(router, "graph_repo", graph)
    monkeypatch.setattr(repository, "spec_repo", spec)
    monkeypatch.setattr(config, "GRAPH_EDIT_ENABLED", True)
    monkeypatch.setattr(config, "GRAPH_SPEC_SEED_ENABLED", True)
    a650 = spec.create_product("A650")
    pu02 = spec.create_product("A650-GA70-PU02", parent_id=a650["id"])
    spec.add_default_attributes()
    spec.add_spec("product", pu02["id"], "ram_gb", "64")
    graph.project_specs()
    app = FastAPI()
    app.include_router(router.router)
    client = TestClient(app)
    with db.transaction() as conn:
        conn.execute("INSERT INTO file (file_id, original_name, stored_path) VALUES ('f', 'a.pdf', 'a.pdf')")
    return db, graph, spec, client


def _node(client, name):
    found = client.get("/graph/entities", params={"q": name}).json()
    return client.get(f"/graph/entities/{next(e['id'] for e in found if e['name'] == name)}").json()


def _types(client):
    return {t["key"]: t for t in client.get("/graph/schema").json()["relation_types"]}


def test_builtin_relation_type_fully_editable(env):
    _, graph, _, client = env
    has_component = _types(client)["has_component"]
    response = client.patch("/graph/relation-types/has_component", json={
        "label": "구성 부품", "description": "제품 -> 들어가는 부품", "source_entity_types": ["product"],
        "target_entity_types": ["component", "spec_value"], "extract": False, "expected_revision": has_component["revision"]})
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["label"], body["source_entity_types"], body["extract"]) == ("구성 부품", ["product"], 0)
    # 바뀐 허용 종류가 다음 문서 추출부터 쓰인다 (GR3 검사)
    result = graph.replace_page("f", 1, PageGraph(
        entities=[E(type="product", name="N5800"), E(type="component", name="RTX 5070")],
        relations=[R(source="N5800", type="has_component", target="RTX 5070")]))
    assert result["relations"] == 0 and result["dropped"]["relation_type"] == 1  # 추출 대상이 아니게 됐다


def test_disallowed_relation_is_created_with_warning(env):
    _, _, _, client = env
    line = _node(client, "A650")
    value = _node(client, "메모리 용량 64GB")
    response = client.post("/graph/relations", json={"source_id": value["id"], "type": "issued_by", "target_id": line["id"]})
    assert response.status_code == 201, response.text
    assert response.json()["warnings"] and response.json()["warnings"][0].startswith("허용 종류가 아닙니다")
    warnings = client.get("/graph/rule-warnings").json()
    assert any(r["id"] == response.json()["id"] for r in warnings["relations"])
    assert warnings["counts"]["relations_by_origin"] == {"manual": 1}


def test_entity_type_change_locks_against_projection(env):
    _, graph, _, client = env
    line = _node(client, "A650")
    changed = client.patch(f"/graph/entities/{line['id']}", json={"type": "product", "expected_revision": line["revision"]})
    assert changed.status_code == 200, changed.text
    assert changed.json()["type"] == "product" and changed.json()["type_locked"] == 1
    assert changed.json()["spec_diff"]["type_changed"] is True
    graph.project_specs()
    assert _node(client, "A650")["type"] == "product"  # 재투영이 종류를 되돌리지 않는다
    # 같은 종류에 같은 이름이 있으면 병합 안내
    other = client.post("/graph/entities", json={"type": "certification", "name": "A650"}).json()
    conflict = client.patch(f"/graph/entities/{other['id']}", json={"type": "product", "expected_revision": other["revision"]})
    assert conflict.status_code == 409 and "합치기" in conflict.json()["detail"]["message"]
    # 식별자 규칙과 다르면 경고만
    plain = client.post("/graph/entities", json={"type": "certification", "name": "브랜드 시리즈"}).json()
    warned = client.patch(f"/graph/entities/{plain['id']}", json={"type": "component", "expected_revision": plain["revision"]})
    assert warned.status_code == 200 and warned.json()["warnings"]


def test_spec_relation_delete_and_retype_survive_and_reset_restores(env):
    _, graph, _, client = env
    pu02 = _node(client, "A650-GA70-PU02")
    variant = next(r for r in pu02["relations"] if r["type"] == "variant_of")
    spec_value = next(r for r in pu02["relations"] if r["type"] == "has_spec")
    assert client.delete(f"/graph/relations/{variant['id']}", params={"expected_revision": variant["revision"]}).status_code == 200
    retyped = client.patch(f"/graph/relations/{spec_value['id']}", json={"type": "has_component", "expected_revision": spec_value["revision"]})
    assert retyped.status_code == 200 and retyped.json()["origin"] == "manual" and retyped.json()["warnings"]
    graph.project_specs()
    after = _node(client, "A650-GA70-PU02")
    kinds = {(r["type"], r["target_name"], r["origin"]) for r in after["relations"]}
    assert ("variant_of", "A650", "spec") not in kinds
    assert ("has_spec", "메모리 용량 64GB", "spec") not in kinds and ("has_component", "메모리 용량 64GB", "manual") in kinds
    assert after["spec_diff"]["differs"] and len(after["spec_diff"]["excluded_relations"]) == 2

    reset = client.post(f"/graph/entities/{after['id']}/reset-spec", json={"expected_revision": after["revision"]})
    assert reset.status_code == 200, reset.text
    kinds = {(r["type"], r["target_name"], r["origin"]) for r in reset.json()["relations"]}
    assert ("variant_of", "A650", "spec") in kinds and ("has_spec", "메모리 용량 64GB", "spec") in kinds
    assert ("has_component", "메모리 용량 64GB", "manual") not in kinds
    assert reset.json()["spec_diff"]["differs"] is False
    with repository.spec_repo.db.get_conn() as conn:  # 사양 DB는 그대로
        assert conn.execute("SELECT count(*) FROM product WHERE parent_id IS NOT NULL").fetchone()[0] == 1


def test_spec_node_rename_and_manual_relation_on_spec_node(env):
    _, graph, _, client = env
    line = _node(client, "A650")
    renamed = client.patch(f"/graph/entities/{line['id']}", json={"name": "A650 시리즈", "expected_revision": line["revision"]})
    assert renamed.json()["spec_diff"]["renamed"] is True
    added = client.post("/graph/relations", json={"source_id": line["id"], "type": "made_by",
                                                  "new_target": {"type": "organization", "name": "TG삼보"}})
    assert added.status_code == 201 and added.json()["warnings"] == []
    graph.project_specs()
    assert _node(client, "A650 시리즈")["ref_type"] == "product"


def test_property_definition_type_change_converts_or_lists_bad_values(env):
    _, _, _, client = env
    pu02 = _node(client, "A650-GA70-PU02")
    definition = client.post("/graph/property-definitions", json={"key": "custom:memo", "label": "메모", "value_type": "text",
                                                                  "allowed_entity_types": ["product"], "multiple": True}).json()
    for text in ("12", "확인 필요"):
        client.post(f"/graph/entities/{pu02['id']}/properties", json={"property_id": definition["property_id"], "value": text})
    blocked = client.patch(f"/graph/property-definitions/{definition['property_id']}",
                           json={"value_type": "number", "unit": "개", "expected_revision": definition["revision"]})
    assert blocked.status_code == 400 and blocked.json()["detail"]["code"] == "value_conversion"
    assert [v["value"] for v in blocked.json()["detail"]["values"]] == ["확인 필요"]
    props = client.get(f"/graph/entities/{pu02['id']}/properties").json()
    assert sorted(p["value"] for p in props) == ["12", "확인 필요"]  # 저장하지 않았다
    bad = next(p for p in props if p["value"] == "확인 필요")
    client.delete(f"/graph/entities/{pu02['id']}/properties/{bad['value_id']}", params={"expected_revision": bad["revision"]})
    ok = client.patch(f"/graph/property-definitions/{definition['property_id']}",
                      json={"value_type": "number", "unit": "개", "expected_revision": definition["revision"]})
    assert ok.status_code == 200, ok.text
    assert (ok.json()["value_type"], ok.json()["unit"]) == ("number", "개")
    assert [p["value"] for p in client.get(f"/graph/entities/{pu02['id']}/properties").json()] == [12.0]


def test_rule_warnings_list_identifier_entities_by_origin(env):
    _, graph, _, client = env
    graph.replace_page("f", 1, PageGraph(entities=[E(type="product", name="N5800")]))
    client.post("/graph/entities", json={"type": "component", "name": "Radeon"})
    warnings = client.get("/graph/rule-warnings").json()
    assert [(e["name"], e["creation_origin"]) for e in warnings["entities"]] == [("Radeon", "manual")]
    assert warnings["counts"]["entities_by_origin"] == {"manual": 1}
