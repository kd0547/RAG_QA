"""GR3: 문서 추출 결과를 저장 전에 검사하고(정식 종류 우선·종류·식별자·관계), 관계 끝을 자동으로 만들지 않는다."""
import json
import sys

import pytest

if not hasattr(sys.modules.get("parser"), "__path__"):
    sys.modules.pop("parser", None)

import config  # noqa: E402
from entity.file import create_file  # noqa: E402
from graph_rag import extractor, service  # noqa: E402
from graph_rag.defaults import DEFAULT_RELATION_TYPES  # noqa: E402
from graph_rag.rules import DEFAULT_VENDOR_PREFIXES  # noqa: E402
from graph_rag.schema import default_schema  # noqa: E402
from graph_rag.types import ExtractedEntity as E, ExtractedRelation as R, PageGraph  # noqa: E402
from graph_rag.validate import validate_page_graph  # noqa: E402
from parser.pdf.type import PageText  # noqa: E402
from repository.file_page_repository import FilePageRepository  # noqa: E402
from repository.file_repository import FileRepository  # noqa: E402
from repository.graph_repository import GraphRepository  # noqa: E402
from repository.repo_connect import Database  # noqa: E402

CAPTURE_PAGE = ("A650 Series 노트북. AMD Ryzen™ AI 7 350 프로세서 (Radeon 그래픽, XDNA NPU, Ryzen AI). "
                "NVIDIA GeForce RTX 5070 Laptop GPU: Blackwell 아키텍처, 5세대 Tensor 코어, 4세대 RT 코어. "
                "GeForce RTX 5070은 NVIDIA가 만든다. A650")
CAPTURE_GRAPH = PageGraph(
    entities=[
        E(type="product", name="A650"),
        E(type="product", name="AMD Ryzen™ AI 7 350 프로세서"),  # 부품인데 제품으로 뽑음
        E(type="component", name="Radeon"), E(type="component", name="XDNA"), E(type="component", name="Ryzen"),
        E(type="component", name="GeForce RTX 5070"),
        E(type="component", name="Blackwell 아키텍처"), E(type="component", name="Tensor 코어"), E(type="component", name="RT 코어"),
        E(type="organization", name="NVIDIA"),
    ],
    relations=[
        R(source="GeForce RTX 5070", type="issued_by", target="NVIDIA"),  # 발급 기관이 아니다
        R(source="GeForce RTX 5070", type="made_by", target="NVIDIA"),
        R(source="A650", type="has_component", target="GeForce RTX 5070"),
        R(source="A650", type="has_component", target="Tensor 코어"),
        R(source="A650", type="has_component", target="AMD Ryzen™ AI 7 350 프로세서"),
    ],
)


class FakeLLM:
    def __init__(self, graph):
        self.graph = graph
        self.calls = []

    def with_structured_output(self, schema):
        self.schema = schema
        return self

    def invoke(self, messages):
        self.calls.append(messages)
        return self.graph.model_dump()


@pytest.fixture
def g(tmp_path, monkeypatch):
    db = Database(str(tmp_path / "rules.db"))
    files, pages, graph = FileRepository(db), FilePageRepository(db), GraphRepository(db)
    for name, repo in (("file_repo", files), ("page_repo", pages), ("graph_repo", graph)):
        monkeypatch.setattr(service, name, repo)
    monkeypatch.setattr(config, "GRAPH_SPEC_SEED_ENABLED", False)  # 사양 노드는 아래에서 직접 만든다 (GR4 투영 전)
    with db.transaction() as conn:
        conn.execute("INSERT INTO product (id, model) VALUES ('p1', 'A650'), ('p2', 'A650-GA70-PU02')")
        conn.execute("UPDATE product SET parent_id='p1' WHERE id='p2'")
        conn.execute("INSERT INTO component (id, kind, model) VALUES ('c1', 'cpu', 'AMD Ryzen AI 7 350'), ('c2', 'gpu', 'NVIDIA GeForce RTX 5070')")
        for type_, name, ref_type, ref_id in (("product_line", "A650", "product", "p1"),
                                               ("component", "AMD Ryzen AI 7 350", "component", "c1"),
                                               ("component", "NVIDIA GeForce RTX 5070", "component", "c2")):
            from graph_rag.types import normalize
            cur = conn.execute("INSERT INTO graph_entity (type, name, norm, ref_type, ref_id, creation_origin) VALUES (?,?,?,?,?,'spec')",
                               (type_, name, normalize(name), ref_type, ref_id))
            conn.execute("INSERT INTO graph_alias (entity_id, alias, alias_norm) VALUES (?,?,?)", (cur.lastrowid, name, normalize(name)))

    def add_file(name, texts):
        file = create_file(original_name=name, stored_path=str(tmp_path / name))
        files.file_save(file)
        pages.save_pages(file.file_id, [PageText(page=i + 1, text=t) for i, t in enumerate(texts)])
        return file.file_id

    g = type("G", (), {})()
    g.db, g.graph, g.add_file = db, graph, add_file
    return g


def _entity(g, name):
    with g.db.get_conn() as conn:
        row = conn.execute("SELECT * FROM effective_graph_entity WHERE name=?", (name,)).fetchone()
    return dict(row) if row else None


def _names(g):
    with g.db.get_conn() as conn:
        return {r["name"]: r["type"] for r in conn.execute("SELECT name, type FROM effective_graph_entity")}


def _relations(g):
    with g.db.get_conn() as conn:
        return {(r["s"], r["type"], r["d"]) for r in conn.execute(
            """SELECT s.name AS s, r.type, d.name AS d FROM effective_graph_relation r
               JOIN effective_graph_entity s ON s.id=r.src_id JOIN effective_graph_entity d ON d.id=r.dst_id""")}


def test_capture_page_is_cleaned_before_saving(g, monkeypatch):
    llm = FakeLLM(CAPTURE_GRAPH)
    monkeypatch.setattr(service, "extract_page_graph", lambda text, **kw: extractor.extract_page_graph(text, llm=llm, **kw))
    file_id = g.add_file("a650_guide.pdf", [CAPTURE_PAGE])

    summary = service.index_file(file_id)

    names = _names(g)
    for noise in ("Radeon", "XDNA", "Ryzen", "Blackwell 아키텍처", "Tensor 코어", "RT 코어"):
        assert noise not in names, noise
    relations = _relations(g)
    assert ("NVIDIA GeForce RTX 5070", "issued_by", "NVIDIA") not in relations
    assert ("NVIDIA GeForce RTX 5070", "made_by", "NVIDIA") in relations  # 문서의 GeForce RTX 5070이 사양 부품 노드에 붙는다
    assert ("A650", "has_component", "NVIDIA GeForce RTX 5070") in relations
    assert ("A650", "has_component", "AMD Ryzen AI 7 350") in relations
    # 제품으로 뽑힌 Ryzen 프로세서는 부품 노드에 붙고, 문서의 A650은 제품군 노드에 붙는다
    assert "AMD Ryzen™ AI 7 350 프로세서" not in names and names["AMD Ryzen AI 7 350"] == "component"
    assert names["A650"] == "product_line" and list(names.values()).count("product") == 0
    with g.db.get_conn() as conn:
        mentioned = {r[0] for r in conn.execute(
            "SELECT e.name FROM graph_mention m JOIN graph_entity e ON e.id=m.entity_id WHERE m.file_id=?", (file_id,))}
        aliases = {r[0] for r in conn.execute(
            "SELECT a.alias FROM graph_alias a JOIN graph_entity e ON e.id=a.entity_id WHERE e.name='AMD Ryzen AI 7 350'")}
    assert {"A650", "AMD Ryzen AI 7 350", "NVIDIA GeForce RTX 5070", "NVIDIA"} <= mentioned
    assert "AMD Ryzen™ AI 7 350 프로세서" in aliases
    assert summary["dropped"] == {"type": 0, "identifier": 6, "relation_endpoint": 1, "relation_type": 1}


def test_relation_to_unknown_name_does_not_create_entity(g):
    g.add_file("x.pdf", ["x"])
    with g.db.get_conn() as conn:
        file_id = conn.execute("SELECT file_id FROM file").fetchone()[0]
    result = g.graph.replace_page(file_id, 1, PageGraph(
        entities=[E(type="product", name="N5800")],
        relations=[R(source="N5800", type="has_component", target="Ghost 9000")]))
    assert "Ghost 9000" not in _names(g)
    assert result["relations"] == 0 and result["dropped"]["relation_endpoint"] == 1


def test_reversed_relation_is_flipped(g):
    file_id = g.add_file("x.pdf", ["x"])
    result = g.graph.replace_page(file_id, 1, PageGraph(
        entities=[E(type="component", name="GeForce RTX 5070"), E(type="organization", name="NVIDIA")],
        relations=[R(source="NVIDIA", type="made_by", target="GeForce RTX 5070")]))
    assert ("NVIDIA GeForce RTX 5070", "made_by", "NVIDIA") in _relations(g)
    assert result["relations"] == 1


def test_changed_allowed_types_apply_to_next_extraction(g):
    file_id = g.add_file("x.pdf", ["x"])
    page = PageGraph(entities=[E(type="product", name="N5800"), E(type="standard", name="KN 32")],
                     relations=[R(source="N5800", type="complies_with", target="KN 32")])
    assert g.graph.replace_page(file_id, 1, page)["relations"] == 1
    with g.db.transaction() as conn:  # 사용자가 규격 준수의 출발 종류에서 제품을 뺐다 (편집 API는 GR5)
        conn.execute("UPDATE graph_relation_type SET source_entity_types=?, revision=2 WHERE key='complies_with'",
                     (json.dumps(["certification"]),))
    result = g.graph.replace_page(file_id, 1, page)
    assert result["relations"] == 0 and result["dropped"]["relation_type"] == 1


def test_identifier_rule_and_inactive_type(g):
    file_id = g.add_file("x.pdf", ["x"])
    with g.db.transaction() as conn:
        conn.execute("UPDATE graph_entity_type SET active=0 WHERE key='standard'")
    result = g.graph.replace_page(file_id, 1, PageGraph(entities=[
        E(type="product", name="Alpha"), E(type="product", name="Beta", aliases=["Beta 300"]),
        E(type="certification", name="안전확인 신고"), E(type="standard", name="KN 32"),
        E(type="spec_value", name="메모리 용량 64GB")]))
    names = _names(g)
    assert "Alpha" not in names and names["Beta"] == "product" and names["안전확인 신고"] == "certification"
    assert "KN 32" not in names and "메모리 용량 64GB" not in names
    assert result["dropped"] == {"type": 2, "identifier": 1, "relation_endpoint": 0, "relation_type": 0}


def test_user_changed_node_type_is_followed(g):
    file_id = g.add_file("x.pdf", ["x"])
    with g.db.transaction() as conn:
        conn.execute("UPDATE graph_entity SET type='product' WHERE name='A650'")  # 사용자가 A650을 제품으로 바꿨다
    g.graph.replace_page(file_id, 1, PageGraph(entities=[E(type="product_line", name="A650")]))
    assert _names(g)["A650"] == "product"


def test_a5_model_and_variant_stay_different(g):
    file_id = g.add_file("x.pdf", ["x"])
    g.graph.replace_page(file_id, 1, PageGraph(entities=[E(type="product", name="N5800"), E(type="product", name="N5800-GB70-PU02")]))
    names = _names(g)
    assert names["N5800"] == names["N5800-GB70-PU02"] == "product"


def test_validate_is_pure_and_counts_self_loops():
    graph = PageGraph(entities=[E(type="component", name="RTX 5070", aliases=["GeForce RTX 5070"])],
                      relations=[R(source="RTX 5070", type="has_component", target="GeForce RTX 5070")])
    kept, dropped = validate_page_graph(graph, default_schema())
    assert kept.relations == [] and dropped["relation_endpoint"] == 1
    assert graph.relations  # 입력은 그대로


def test_default_relation_table_and_prompt_rules():
    by_key = {r["key"]: r for r in DEFAULT_RELATION_TYPES}
    assert set(by_key) == {"variant_of", "has_component", "has_spec", "has_certification", "has_number",
                           "issued_by", "made_by", "complies_with"}
    assert by_key["made_by"]["target"] == ["organization"] and by_key["has_spec"]["extract"] == 0
    assert "made_by" in by_key["issued_by"]["description"]
    for rule in ("브랜드·제품군 이름만 있는 표현, 기술·기능 이름, 아키텍처 이름은 개체로 뽑지 않는다.",
                 "회사가 제품·부품을 만들었으면 made_by, 인증·번호를 발급했으면 issued_by다.",
                 "관계의 출발과 도착은 위 표에 적힌 종류만 된다."):
        assert rule in extractor.EXTRACT_PROMPT
    assert "has_spec" not in extractor.EXTRACT_PROMPT and "variant_of" not in extractor.EXTRACT_PROMPT
    assert not hasattr(extractor, "_add_relation_endpoints")
    assert config.GRAPH_VENDOR_PREFIXES == DEFAULT_VENDOR_PREFIXES


def test_existing_unedited_builtin_relations_are_updated_but_edited_ones_kept(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    Database(str(path))
    with sqlite3.connect(path) as conn:
        conn.execute("""UPDATE graph_relation_type SET source_entity_types='["product"]', description='옛 설명' WHERE key='has_component'""")
        conn.execute("""UPDATE graph_relation_type SET source_entity_types='["product"]', description='사용자 설명', revision=3
                        WHERE key='has_certification'""")
    db = Database(str(path))
    with db.get_conn() as conn:
        rows = {r["key"]: dict(r) for r in conn.execute("SELECT * FROM graph_relation_type")}
    assert json.loads(rows["has_component"]["source_entity_types"]) == ["product", "product_line"]
    assert rows["has_certification"]["description"] == "사용자 설명"
    assert rows["made_by"]["extract"] == 1 and rows["has_spec"]["extract"] == 0
