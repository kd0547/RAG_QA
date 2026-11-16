"""GR4: 사양 DB를 그래프로 투영 (제품군·제품 트리, 부품, 대상 값, 사양 값 노드). 사양 데이터는 바뀌지 않는다."""
import sqlite3
import sys
from types import SimpleNamespace

import pytest

if not hasattr(sys.modules.get("parser"), "__path__"):
    sys.modules.pop("parser", None)

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import config  # noqa: E402
import repository  # noqa: E402
from entity.file import create_file  # noqa: E402
from graph_rag import service  # noqa: E402
from graph_rag.edit_service import GraphEditService  # noqa: E402
from graph_rag.types import ExtractedEntity, ExtractedRelation, PageGraph  # noqa: E402
from repository.file_page_repository import FilePageRepository  # noqa: E402
from repository.file_repository import FileRepository  # noqa: E402
from repository.graph_projection import number_text  # noqa: E402
from repository.graph_repository import GraphRepository  # noqa: E402
from repository.repo_connect import Database  # noqa: E402
from repository.spec_repository import SpecRepository  # noqa: E402

SPEC_TABLES = ("product", "component", "spec_value", "product_component")


@pytest.fixture
def g(tmp_path, monkeypatch):
    db = Database(str(tmp_path / "proj.db"))
    spec, graph, files = SpecRepository(db), GraphRepository(db), FileRepository(db)
    monkeypatch.setattr(service, "graph_repo", graph)
    monkeypatch.setattr(repository, "spec_repo", spec)
    monkeypatch.setattr(repository, "graph_repo", graph)
    monkeypatch.setattr(config, "GRAPH_SPEC_SEED_ENABLED", True)
    spec.add_default_attributes()
    a650 = spec.create_product("A650", name="A650 Series")
    ou01 = spec.create_product("A650-GA70-OU01", parent_id=a650["id"])
    pu02 = spec.create_product("A650-GA70-PU02", parent_id=a650["id"])
    n5800 = spec.create_product("N5800")
    cpu = spec.create_component("cpu", "AMD Ryzen AI 7 350", vendor="AMD")
    spec.add_spec("product", pu02["id"], "cpu_model", "AMD Ryzen AI 7 350")
    spec.add_spec("product", pu02["id"], "gpu_model", "NVIDIA GeForce RTX 5070 (105W)")
    spec.add_spec("product", pu02["id"], "ram_gb", "64")
    spec.add_spec("product", n5800["id"], "ram_gb", "64GB")
    spec.add_spec("product", ou01["id"], "ram_gb", "16")
    spec.add_spec("product", ou01["id"], "ssd_gb", "1TB")
    spec.add_spec("product", ou01["id"], "card_reader", "있음")
    spec.add_spec("product", ou01["id"], "usb_c_ports", "2")
    spec.add_spec("product", ou01["id"], "os", "Windows 11 Pro")
    spec.add_spec("product", ou01["id"], "io_ports", "USB-C 2개, USB-A 2개, HDMI 1개, 유선 LAN 1개, 오디오 잭 1개, 카드리더 1개")

    def add_file(name):
        file = create_file(original_name=name, stored_path=str(tmp_path / name))
        files.file_save(file)
        return file.file_id

    return SimpleNamespace(db=db, spec=spec, graph=graph, edit=GraphEditService(db), add_file=add_file,
                           a650=a650, ou01=ou01, pu02=pu02, n5800=n5800, cpu=cpu)


def _nodes(g):
    with g.db.get_conn() as conn:
        return {r["name"]: dict(r) for r in conn.execute("SELECT * FROM effective_graph_entity")}


def _rel(g):
    with g.db.get_conn() as conn:
        return {(r["s"], r["type"], r["d"]) for r in conn.execute(
            """SELECT s.name AS s, r.type, d.name AS d FROM effective_graph_relation r
               JOIN effective_graph_entity s ON s.id=r.src_id JOIN effective_graph_entity d ON d.id=r.dst_id""")}


def _counts(g):
    with g.db.get_conn() as conn:
        return {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in SPEC_TABLES}


def test_tree_types_and_variant_of(g):
    summary = g.graph.project_specs()
    nodes = _nodes(g)
    assert nodes["A650"]["type"] == "product_line"
    assert nodes["A650-GA70-PU02"]["type"] == nodes["A650-GA70-OU01"]["type"] == nodes["N5800"]["type"] == "product"
    assert {("A650-GA70-PU02", "variant_of", "A650"), ("A650-GA70-OU01", "variant_of", "A650")} <= _rel(g)
    # 부품 테이블의 부품은 CPU 하나 (GPU 값의 대상 노드는 부품 테이블 밖이라 세지 않는다)
    assert (summary["product_lines"], summary["products"], summary["components"]) == (1, 3, 1)
    assert summary["seconds"] >= 0


def test_multi_level_tree_and_type_follows_tree(g):
    mid = g.spec.create_product("A650-GA70", parent_id=g.a650["id"])
    g.spec.update_product(g.pu02["id"], parent_id=mid["id"])
    g.graph.project_specs()
    nodes, rel = _nodes(g), _rel(g)
    assert nodes["A650-GA70"]["type"] == "product_line" and ("A650-GA70-PU02", "variant_of", "A650-GA70") in rel
    assert ("A650-GA70", "variant_of", "A650") in rel
    detail = g.graph.get_entity(nodes["A650-GA70-PU02"]["id"])
    assert [a["name"] for a in detail["hierarchy"]["ancestors"]] == ["A650", "A650-GA70"]
    assert [c["name"] for c in g.graph.get_entity(nodes["A650"]["id"])["hierarchy"]["children"]] == ["A650-GA70", "A650-GA70-OU01"]
    # 하위 모델이 모두 없어지면 제품이 된다
    g.spec.update_product(g.pu02["id"], parent_id=g.a650["id"])
    g.spec.delete_product(mid["id"])
    g.spec.delete_product(g.ou01["id"])
    g.spec.delete_product(g.pu02["id"])
    g.graph.project_specs()
    assert _nodes(g)["A650"]["type"] == "product"


def test_user_type_change_is_kept(g):
    g.graph.project_specs()
    node = _nodes(g)["A650"]
    with g.db.transaction() as conn:
        conn.execute("UPDATE graph_entity SET type='product', type_locked=1 WHERE id=?", (node["id"],))
    g.graph.project_specs()
    assert _nodes(g)["A650"]["type"] == "product"


def test_entity_values_link_spec_component_and_attach_document_names(g):
    g.graph.project_specs()
    nodes, rel = _nodes(g), _rel(g)
    with g.db.get_conn() as conn:
        cpu_nodes = conn.execute("SELECT count(*) FROM graph_entity WHERE name LIKE '%Ryzen AI 7 350%'").fetchone()[0]
    assert cpu_nodes == 1 and nodes["AMD Ryzen AI 7 350"]["ref_id"] == g.cpu["id"]
    assert ("A650-GA70-PU02", "has_component", "AMD Ryzen AI 7 350") in rel
    assert nodes["NVIDIA GeForce RTX 5070"]["type"] == "component"  # 끝 괄호 (105W)는 이름에서 뺀다
    assert ("A650-GA70-PU02", "has_component", "NVIDIA GeForce RTX 5070") in rel
    # 문서에서 뽑힌 GeForce RTX 5070이 같은 노드에 붙는다
    file_id = g.add_file("a650.pdf")
    g.graph.replace_page(file_id, 1, PageGraph(entities=[ExtractedEntity(type="component", name="GeForce RTX 5070"),
                                                          ExtractedEntity(type="organization", name="NVIDIA")],
                                                relations=[ExtractedRelation(source="GeForce RTX 5070", type="made_by", target="NVIDIA")]))
    assert ("NVIDIA GeForce RTX 5070", "made_by", "NVIDIA") in _rel(g)
    assert "GeForce RTX 5070" not in _nodes(g)


def test_value_nodes_shared_and_unit_converted(g):
    summary = g.graph.project_specs()
    nodes, rel = _nodes(g), _rel(g)
    assert ("A650-GA70-PU02", "has_spec", "메모리 용량 64GB") in rel and ("N5800", "has_spec", "메모리 용량 64GB") in rel
    assert nodes["메모리 용량 64GB"]["type"] == "spec_value"
    assert (nodes["메모리 용량 64GB"]["ref_type"], nodes["메모리 용량 64GB"]["ref_id"]) == ("spec_attribute", "ram_gb")
    assert "SSD 용량 1000GB" in nodes  # 1TB → GB 속성 단위
    assert {"카드리더 지원", "USB-C 단자 수 2개", "운영체제 Windows 11 Pro"} <= set(nodes)
    assert not any(name.startswith("단자 구성") for name in nodes)  # 40자를 넘는 서술 속성은 기본 none
    assert summary["has_spec"] == 7 and summary["value_nodes"] == 6
    # 상속된 값은 상위 모델 노드에만 (PU02의 값은 PU02만 직접 가진다)
    assert ("A650", "has_spec", "메모리 용량 64GB") not in rel
    detail = g.graph.get_entity(nodes["메모리 용량 64GB"]["id"])
    assert detail["spec_attribute"]["name"] == "메모리 용량" and detail["spec_attribute"]["unit"] == "GB"
    assert detail["spec_attribute"]["value_num"] == 64


def test_value_change_moves_relation_and_cleans_orphan(g):
    g.graph.project_specs()
    value = next(v for v in g.spec.get_product(g.ou01["id"])["specs"] if v["attribute_key"] == "ram_gb")
    g.spec.update_spec(value["id"], value_text="32")
    g.graph.project_specs()
    nodes, rel = _nodes(g), _rel(g)
    assert ("A650-GA70-OU01", "has_spec", "메모리 용량 32GB") in rel
    assert "메모리 용량 16GB" not in nodes  # 관계가 없어진 값 노드는 정리된다


def test_user_edits_survive_reprojection(g):
    g.graph.project_specs()
    nodes = _nodes(g)
    # 사양 관계 지우기, 사양 노드 이름 바꾸기·지우기
    pu02 = g.graph.get_entity(nodes["A650-GA70-PU02"]["id"])
    variant = next(r for r in pu02["relations"] if r["type"] == "variant_of")
    g.edit.execute("delete_relation", variant["id"], {"expected_revision": variant["revision"]})
    g.edit.execute("update_entity", nodes["N5800"]["id"], {"name": "N5800 노트북", "expected_revision": nodes["N5800"]["revision"]})
    value = nodes["카드리더 지원"]
    g.edit.execute("delete_entity", value["id"], {"expected_revision": value["revision"]})

    g.graph.project_specs()
    after, rel = _nodes(g), _rel(g)
    assert ("A650-GA70-PU02", "variant_of", "A650") not in rel
    assert "N5800 노트북" in after and after["N5800 노트북"]["ref_id"] == g.n5800["id"]
    assert "카드리더 지원" not in after
    with g.db.get_conn() as conn:
        assert conn.execute("SELECT lifecycle_state FROM graph_entity WHERE id=?", (value["id"],)).fetchone()[0] == "deleted"
        assert conn.execute("SELECT count(*) FROM graph_relation WHERE dst_id=? AND origin='spec'", (value["id"],)).fetchone()[0] == 0


def test_graph_mode_none_removes_value_nodes(g):
    g.graph.project_specs()
    assert "운영체제 Windows 11 Pro" in _nodes(g)
    g.spec.update_attribute("os", graph_mode="none")
    g.graph.project_specs()
    assert "운영체제 Windows 11 Pro" not in _nodes(g)
    with pytest.raises(ValueError):
        g.spec.update_attribute("os", graph_mode="bogus")


def test_spec_rows_unchanged_and_every_write_api_reprojects(g, monkeypatch):
    from app.routers import specs

    before = _counts(g)
    g.graph.project_specs()
    g.graph.project_specs()
    assert _counts(g) == before

    calls = []
    monkeypatch.setattr(specs, "spec_repo", g.spec)
    monkeypatch.setattr(specs, "reseed_spec_graph", lambda reason: calls.append(reason))
    app = FastAPI()
    app.include_router(specs.router)
    client = TestClient(app)
    product = client.post("/specs/products", json={"model": "X9000"}).json()
    client.put(f"/specs/products/{product['id']}", json={"name": "X9000 Pro"})
    component = client.post("/specs/components", json={"kind": "ssd", "model": "PM9C1b 1TB"}).json()
    client.put(f"/specs/components/{component['id']}", json={"vendor": "Samsung"})
    client.put(f"/specs/products/{product['id']}/components", json={"component_id": component["id"]})
    client.delete(f"/specs/products/{product['id']}/components/{component['id']}")
    value = client.post("/specs/values", json={"owner_type": "product", "owner_id": product["id"], "attribute_key": "ram_gb",
                                               "value_text": "8"}).json()
    client.put(f"/specs/values/{value['id']}", json={"value_text": "16"})
    client.delete(f"/specs/values/{value['id']}")
    client.post("/specs/attributes", json={"key": "fan_count", "name": "팬 수", "data_type": "number", "unit": "개"})
    client.put("/specs/attributes/fan_count", json={"graph_mode": "none"})
    client.delete("/specs/attributes/fan_count")
    client.post("/specs/attributes/defaults")
    client.delete(f"/specs/components/{component['id']}")
    client.delete(f"/specs/products/{product['id']}")
    assert len(calls) == 15, calls


def test_graph_search_product_line_and_value(g):
    g.graph.project_specs()
    line = service.search_graph("A650")
    assert any("A650-GA70-PU02 -[variant_of]-> A650" in r for r in line["relations"])
    assert not any("has_spec" in r for r in line["relations"])
    pu02 = service.search_graph("A650-GA70-PU02 GPU")
    assert pu02["spec_values"] == 1 and not any("has_spec" in r for r in pu02["relations"])
    value = service.search_graph("메모리 64GB 제품")
    assert [m["name"] for m in value["matched"] if m["type"] == "spec_value"] == ["메모리 용량 64GB"]
    holders = {r.split(" -[")[0] for r in value["relations"] if "-[has_spec]->" in r}
    assert holders == {"A650-GA70-PU02", "N5800"}


def test_view_hides_value_nodes_except_neighbors(g):
    g.graph.project_specs()
    overview = g.graph.view(limit=300)
    assert not any(n["type"] == "spec_value" for n in overview["nodes"])
    assert any(n["type"] == "spec_value" for n in g.graph.view(limit=300, spec_values="all")["nodes"])
    pu02 = _nodes(g)["A650-GA70-PU02"]["id"]
    focus = g.graph.view(entity_id=pu02, depth=2)
    names = {n["name"] for n in focus["nodes"]}
    assert "메모리 용량 64GB" in names  # 고른 노드의 이웃
    assert "N5800" not in names  # 사양 값 노드에서 더 펼치지 않는다
    assert "SSD 용량 1000GB" not in names  # 2단계 이웃의 사양 값은 보이지 않는다


def test_entity_api_has_spec_values_and_hierarchy(g, monkeypatch):
    from app.routers import graph as graph_router

    g.graph.project_specs()
    monkeypatch.setattr(graph_router, "graph_repo", g.graph)
    app = FastAPI()
    app.include_router(graph_router.router)
    client = TestClient(app)
    pu02 = _nodes(g)["A650-GA70-PU02"]["id"]
    body = client.get(f"/graph/entities/{pu02}").json()
    assert {v["attribute_key"] for v in body["spec"]["values"]} >= {"cpu_model", "gpu_model", "ram_gb"}
    assert [a["name"] for a in body["hierarchy"]["ancestors"]] == ["A650"]
    assert client.get("/graph/view", params={"spec_values": "bogus"}).status_code == 422


def test_flag_off_does_not_project(g, monkeypatch):
    from app.routers import specs

    monkeypatch.setattr(config, "GRAPH_SPEC_SEED_ENABLED", False)
    specs.reseed_spec_graph("테스트")
    assert _nodes(g) == {}


def test_number_text():
    assert (number_text(64.0), number_text(2.5), number_text(1000.0), number_text(0.125)) == ("64", "2.5", "1000", "0.125")


def test_migration_sets_default_graph_modes_once(tmp_path):
    path = tmp_path / "old.db"
    Database(str(path))
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE spec_attribute_new AS SELECT key, name, category, data_type, unit, description, sort_order, inheritable, created_at, updated_at FROM spec_attribute")
        conn.execute("DROP TABLE spec_attribute")
        conn.execute("ALTER TABLE spec_attribute_new RENAME TO spec_attribute")
        conn.executemany("INSERT INTO spec_attribute (key, name, category, data_type, unit, description, sort_order, inheritable, created_at, updated_at) VALUES (?,?,?,?,?,'',0,0,'','')",
                         [("cpu_model", "CPU 모델", "cpu", "text", ""), ("io_ports", "단자 구성", "io", "text", ""),
                          ("os", "운영체제", "os", "text", ""), ("ram_gb", "메모리 용량", "memory", "number", "GB")])
        conn.execute("INSERT INTO product (id, model) VALUES ('p', 'X1000')")
        conn.execute("INSERT INTO spec_value (owner_type, owner_id, attribute_key, value_text) VALUES ('product','p','io_ports',?)", ("가" * 41,))
    Database(str(path))
    with sqlite3.connect(path) as conn:
        modes = dict(conn.execute("SELECT key, graph_mode FROM spec_attribute").fetchall())
        conn.execute("UPDATE spec_attribute SET graph_mode='none' WHERE key='os'")
    assert modes == {"cpu_model": "entity", "io_ports": "none", "os": "value_node", "ram_gb": "value_node"}
    Database(str(path))  # 다시 시작해도 R&D가 바꾼 값을 덮지 않는다
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT graph_mode FROM spec_attribute WHERE key='os'").fetchone()[0] == "none"
