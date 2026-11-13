"""H: 그래프를 만들 때 사양 DB 참조 (저장 구조, 심기, 추출 정식 이름, 검색 결과를 사양으로 잇기)."""
import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if not hasattr(sys.modules.get("parser"), "__path__"):
    sys.modules.pop("parser", None)

from types import SimpleNamespace  # noqa: E402

import config  # noqa: E402
from entity.file import create_file  # noqa: E402
from graph_rag import extractor, service  # noqa: E402
from graph_rag.types import (  # noqa: E402
    NON_EXTRACT_RELATIONS, RELATION_TYPES, ExtractedEntity, ExtractedRelation, PageGraph,
)
from parser.pdf.type import PageText  # noqa: E402
from repository.file_page_repository import FilePageRepository  # noqa: E402
from repository.file_repository import FileRepository  # noqa: E402
from repository.graph_repository import GraphRepository  # noqa: E402
from repository.repo_connect import Database  # noqa: E402
from repository.spec_repository import SpecRepository  # noqa: E402

OLD_RELATION_SQL = """
create table graph_relation (
    id         integer primary key autoincrement,
    src_id     integer not null references graph_entity(id) on delete cascade,
    dst_id     integer not null references graph_entity(id) on delete cascade,
    type       text not null,
    file_id    text references file(file_id) on delete cascade,
    page       integer,
    origin     text not null default 'extract' check (origin in ('extract', 'seed', 'manual')),
    created_at text not null default current_timestamp
)"""


def _old_graph_db(path: Path) -> list[tuple]:
    """CHECK에 spec이 없고 graph_entity에 ref 컬럼이 없는 예전 그래프 테이블. 넣은 관계 행을 돌려준다.

    지금 스키마로 DB를 만든 뒤 그래프 두 테이블만 예전 모양으로 바꾼다.
    """
    Database(str(path))
    with sqlite3.connect(path) as conn:
        conn.execute("pragma foreign_keys = off")
        conn.execute("drop table graph_relation")
        conn.execute("drop table graph_alias")
        conn.execute("drop table graph_mention")
        conn.execute("drop table graph_entity")
        conn.execute("""create table graph_entity (id integer primary key autoincrement, type text not null,
                        name text not null, norm text not null, created_at text not null default current_timestamp,
                        unique (type, norm))""")
        conn.execute(OLD_RELATION_SQL)
        conn.execute("""CREATE UNIQUE INDEX idx_graph_relation_unique
                        ON graph_relation(src_id, dst_id, type, ifnull(file_id, ''), ifnull(page, -1))""")
        conn.execute("insert into file (file_id, original_name, stored_path) values ('f1', 'guide.pdf', 'x/guide.pdf')")
        conn.executemany("insert into graph_entity (id, type, name, norm) values (?, ?, ?, ?)",
                         [(1, "product", "N5800", "n5800"), (2, "certification", "안전확인 신고", "안전확인신고"),
                          (3, "concept", "KC 인증", "kc인증")])
        conn.executemany(
            "insert into graph_relation (id, src_id, dst_id, type, file_id, page, origin, created_at) values (?,?,?,?,?,?,?,?)",
            [(7, 1, 2, "has_certification", "f1", 3, "extract", "2026-11-01 10:00:00"),
             (12, 2, 3, "part_of", None, None, "seed", "2026-11-01 10:00:01"),
             (40, 1, 3, "has_certification", None, None, "manual", "2026-11-02 09:00:00")],
        )
        return conn.execute("select id, src_id, dst_id, type, file_id, page, origin, created_at from graph_relation order by id").fetchall()


# ---------------------------------------------------------------- H1 저장 구조

def test_check_migration_keeps_rows_ids_and_indexes(tmp_path):
    path = tmp_path / "old.db"
    before = _old_graph_db(path)

    Database(str(path))
    Database(str(path))  # 두 번 열어도 같다

    with sqlite3.connect(path) as conn:
        after = conn.execute("select id, src_id, dst_id, type, file_id, page, origin, created_at from graph_relation order by id").fetchall()
        table_sql = conn.execute("select sql from sqlite_master where name = 'graph_relation'").fetchone()[0]
        indexes = {r[1] for r in conn.execute("pragma index_list(graph_relation)")}
        options = conn.execute("select distinct is_option from graph_relation").fetchall()
        entity_columns = [r[1] for r in conn.execute("pragma table_info(graph_entity)")]
        conn.execute("insert into graph_relation (src_id, dst_id, type, origin) values (1, 3, 'variant_of', 'spec')")
        with pytest.raises(sqlite3.IntegrityError):  # 유일 인덱스가 그대로 있다
            conn.execute("insert into graph_relation (src_id, dst_id, type, origin) values (2, 3, 'part_of', 'seed')")
        with pytest.raises(sqlite3.IntegrityError):  # CHECK도 그대로 있다
            conn.execute("insert into graph_relation (src_id, dst_id, type, origin) values (1, 2, 'x', 'guess')")
    assert after == before
    assert "'spec'" in table_sql and "graph_relation_new" not in table_sql
    assert {"idx_graph_relation_unique", "idx_graph_relation_dst", "idx_graph_relation_file"} <= indexes
    assert options == [(0,)]
    assert entity_columns.count("ref_type") == 1 and entity_columns.count("ref_id") == 1


def test_migration_copies_rows_even_with_dangling_file(tmp_path):
    """예전에 외래키 없이 남은 행이 있어도 서버 시작이 막히지 않고 그대로 옮긴다."""
    path = tmp_path / "old.db"
    _old_graph_db(path)
    with sqlite3.connect(path) as conn:  # 외래키 검사가 꺼진 연결로 파일만 지운 상태
        conn.execute("delete from file where file_id = 'f1'")

    Database(str(path))

    with sqlite3.connect(path) as conn:
        assert [r[0] for r in conn.execute("select id from graph_relation order by id")] == [7, 12, 40]


def test_variant_of_is_known_but_not_extracted():
    assert "variant_of" in RELATION_TYPES and "variant_of" in NON_EXTRACT_RELATIONS
    assert "variant_of" not in extractor.EXTRACT_PROMPT and "part_of" not in extractor.EXTRACT_PROMPT
    assert "variant_of" not in str(ExtractedRelation.model_json_schema())


def test_prune_keeps_entities_with_spec_ref(tmp_path):
    db = Database(str(tmp_path / "g.db"))
    graph = GraphRepository(db)
    with db.transaction() as conn:
        conn.execute("insert into graph_entity (type, name, norm, ref_type, ref_id) values ('product', 'A650', 'a650', 'product', 'p1')")
        conn.execute("insert into graph_entity (type, name, norm) values ('product', 'X1', 'x1')")
    assert graph.prune_orphans() == 1
    with db.get_conn() as conn:
        assert [r[0] for r in conn.execute("select name from graph_entity")] == ["A650"]


# ---------------------------------------------------------------- H2 심기

@pytest.fixture
def g(tmp_path, monkeypatch):
    """사양 DB와 문서 그래프가 같은 임시 DB를 쓴다 (운영과 같다)."""
    db = Database(str(tmp_path / "g.db"))
    ns = SimpleNamespace(db=db, spec=SpecRepository(db), graph=GraphRepository(db), files=FileRepository(db),
                         pages=FilePageRepository(db), tmp=tmp_path)
    monkeypatch.setattr(service, "graph_repo", ns.graph)
    monkeypatch.setattr(service, "page_repo", ns.pages)
    monkeypatch.setattr(service, "file_repo", ns.files)

    def add_file(name, texts):
        file = create_file(original_name=name, stored_path=str(tmp_path / name))
        ns.files.file_save(file)
        ns.pages.save_pages(file.file_id, [PageText(i + 1, t) for i, t in enumerate(texts)])
        return file.file_id

    ns.add_file = add_file
    a650 = ns.spec.create_product("A650", name="A650 Series")
    ns.a650 = a650
    ns.child = ns.spec.create_product("A650-GA70-PU02", name="Pro", parent_id=a650["id"])
    ns.n5800 = ns.spec.create_product("N5800", name="N5800 14세대 노트북")
    ns.ssd = ns.spec.create_component("ssd", "Samsung 980 500GB")
    ns.opt = ns.spec.create_component("ssd", "Samsung 990 PRO 1TB")
    ns.unlinked = ns.spec.create_component("ssd", "WD SN770 1TB")
    ns.spec.link_component(a650["id"], ns.ssd["id"])
    ns.spec.link_component(a650["id"], ns.opt["id"], is_option=True)
    return ns


def _entities(db):
    with db.get_conn() as conn:
        return {r["name"]: dict(r) for r in conn.execute("select id, type, name, ref_type, ref_id from graph_entity")}


def _relations(db, origin=None):
    with db.get_conn() as conn:
        rows = conn.execute(
            """select s.name as src, r.type, d.name as dst, r.origin, r.is_option from graph_relation r
               join graph_entity s on s.id = r.src_id join graph_entity d on d.id = r.dst_id
               """ + ("where r.origin = ?" if origin else "") + " order by s.name, r.type, d.name",
            (origin,) if origin else (),
        ).fetchall()
    return [tuple(r) for r in rows]


def test_seed_products_variants_and_linked_components_only(g):
    summary = g.graph.seed_specs()

    entities = _entities(g.db)
    assert {"A650", "A650-GA70-PU02", "N5800", "Samsung 980 500GB", "Samsung 990 PRO 1TB"} == set(entities)
    assert "WD SN770 1TB" not in entities  # 연결되지 않은 부품은 심지 않는다
    assert entities["A650"]["ref_type"] == "product" and entities["A650"]["ref_id"] == g.a650["id"]
    assert entities["Samsung 980 500GB"]["ref_type"] == "component"
    assert _relations(g.db) == [
        ("A650", "has_component", "Samsung 980 500GB", "spec", 0),
        ("A650", "has_component", "Samsung 990 PRO 1TB", "spec", 1),
        ("A650-GA70-PU02", "variant_of", "A650", "spec", 0),
    ]
    assert summary == {"products": 3, "components": 2, "variant_of": 1, "has_component": 2, "blocked": 0}
    # 모델명을 담은 제품 이름만 별칭이 된다 ("Pro"는 아무 질문에나 걸린다)
    assert [e["name"] for e in g.graph.find_entities("N5800 14세대 노트북 무게")] == ["N5800"]
    assert g.graph.find_entities("Windows 11 Pro 지원") == []


def test_seed_reuses_extracted_entity_and_is_idempotent(g):
    file_id = g.add_file("guide.pdf", ["N5800 인증"])
    g.graph.replace_page(file_id, 1, PageGraph(entities=[ExtractedEntity(type="product", name="N5800")]))
    before = _entities(g.db)["N5800"]["id"]

    g.graph.seed_specs()
    g.graph.seed_specs()

    entities = _entities(g.db)
    assert entities["N5800"]["id"] == before and entities["N5800"]["ref_id"] == g.n5800["id"]
    assert len(_relations(g.db, "spec")) == 3


def test_reextract_keeps_spec_relations_and_unlink_removes_them(g):
    g.graph.seed_specs()
    file_id = g.add_file("a650.pdf", ["A650 SSD Samsung 980 500GB"])
    g.graph.replace_page(file_id, 1, PageGraph(
        entities=[ExtractedEntity(type="product", name="A650"), ExtractedEntity(type="component", name="Samsung 980 500GB")],
        relations=[ExtractedRelation(source="A650", type="has_component", target="Samsung 980 500GB")],
    ))
    g.graph.delete_file(file_id)  # 다시 뽑기 전에 지운다
    g.graph.replace_page(file_id, 1, PageGraph())

    assert len(_relations(g.db, "spec")) == 3 and _relations(g.db, "extract") == []
    assert _entities(g.db)["A650"]["ref_id"] == g.a650["id"]

    g.spec.unlink_component(g.a650["id"], g.ssd["id"])
    g.graph.seed_specs()
    assert ("A650", "has_component", "Samsung 980 500GB", "spec", 0) not in _relations(g.db)
    # 문서에도 안 나오지만 사양 DB 대상을 가리키므로 개체는 남는다
    assert "Samsung 980 500GB" in _entities(g.db)


def test_deleted_spec_relation_is_not_reseeded(g):
    g.graph.seed_specs()
    with g.db.get_conn() as conn:
        relation_id = conn.execute("select id from graph_relation where type = 'variant_of'").fetchone()[0]
    g.graph.delete_relation(relation_id)

    summary = g.graph.seed_specs()

    assert all(r[1] != "variant_of" for r in _relations(g.db)) and summary["blocked"] == 1


def test_deleted_product_ref_is_cleared(g):
    g.graph.seed_specs()
    g.spec.delete_product(g.n5800["id"])
    g.graph.seed_specs()
    assert "N5800" not in _entities(g.db)  # 문서에도 안 나오고 관계도 없으면 정리된다


def test_router_changes_reseed_and_flag_off_skips(g, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import repository
    from app.routers import specs

    monkeypatch.setattr(specs, "spec_repo", g.spec)
    monkeypatch.setattr(repository, "graph_repo", g.graph)
    app = FastAPI()
    app.include_router(specs.router)
    client = TestClient(app)

    assert client.put(f"/specs/products/{g.n5800['id']}/components", json={"component_id": g.unlinked["id"]}).status_code == 200
    assert ("N5800", "has_component", "WD SN770 1TB", "spec", 0) in _relations(g.db)

    monkeypatch.setattr(config, "GRAPH_SPEC_SEED_ENABLED", False)
    client.delete(f"/specs/products/{g.n5800['id']}/components/{g.unlinked['id']}")
    assert ("N5800", "has_component", "WD SN770 1TB", "spec", 0) in _relations(g.db)  # 꺼져 있으면 다시 심지 않는다


# ---------------------------------------------------------------- H3 추출할 때 정식 이름

class FakeLLM:
    """페이지 텍스트에 따라 정해 둔 PageGraph를 돌려준다. 받은 메시지를 모은다."""

    def __init__(self, graphs: dict[str, PageGraph]):
        self.graphs = graphs
        self.calls = []

    def with_structured_output(self, schema):
        return self

    def invoke(self, messages):
        self.calls.append(messages)
        text = messages[-1]["content"]
        return next(g for key, g in self.graphs.items() if key in text).model_copy(deep=True)


def _use_fake(monkeypatch, llm):
    def fake(text, concepts=None, **kwargs):
        return extractor.extract_page_graph(text, llm=llm, concepts=concepts, **kwargs)

    monkeypatch.setattr(service, "extract_page_graph", fake)


def _mentions(db, name):
    with db.get_conn() as conn:
        return sorted(r[0] for r in conn.execute(
            """select f.original_name from graph_mention m join graph_entity e on e.id = m.entity_id
               join file f on f.file_id = m.file_id where e.name = ?""", (name,)))


def test_two_documents_with_different_notations_attach_to_one_entity(g, monkeypatch):
    g.graph.seed_specs()
    llm = FakeLLM({
        "A650 Pro": PageGraph(entities=[ExtractedEntity(type="product", name="A650-GA70-PU02", aliases=["A650 Pro"])]),
        "A650-GA70-PU02 KC": PageGraph(entities=[ExtractedEntity(type="product", name="A650-GA70-PU02")]),
    })
    _use_fake(monkeypatch, llm)
    first = g.add_file("proposal.pdf", ["A650 Pro 모델 사양서"])
    second = g.add_file("cert.pdf", ["A650-GA70-PU02 KC 안전확인"])

    service.index_file(first)
    service.index_file(second)

    entities = _entities(g.db)
    assert "A650 Pro" not in entities
    assert entities["A650-GA70-PU02"]["ref_id"] == g.child["id"]
    assert _mentions(g.db, "A650-GA70-PU02") == ["cert.pdf", "proposal.pdf"]
    system = llm.calls[0][0]["content"]
    assert "## 사양 DB의 정식 이름" in system and "목록의 이름을 name으로 쓰고 문서 표기는 aliases에 넣는다" in system
    assert "- product(제품): N5800 (다른 표기: N5800 14세대 노트북)" in system
    assert "다른 표기: Pro" not in system


def test_components_on_page_get_ref_and_others_not_listed(g, monkeypatch):
    llm = FakeLLM({"SN770": PageGraph(entities=[
        ExtractedEntity(type="component", name="WD SN770 1TB"),
        ExtractedEntity(type="product", name="Galaxy Book4"),  # 사양 DB에 없는 타사 모델
    ])})
    _use_fake(monkeypatch, llm)
    file_id = g.add_file("ssd.pdf", ["SSD: WD SN770 1TB, 비교 대상 Galaxy Book4"])

    service.index_file(file_id)

    entities = _entities(g.db)
    assert entities["WD SN770 1TB"]["ref_type"] == "component" and entities["WD SN770 1TB"]["ref_id"] == g.unlinked["id"]
    assert entities["Galaxy Book4"]["ref_id"] is None
    system = llm.calls[0][0]["content"]
    assert "- component(부품): WD SN770 1TB" in system
    assert "Samsung 980 500GB" not in system  # 그 페이지에 없는 부품은 넘기지 않는다


def test_keep_grounded_needs_name_or_alias_of_known_name():
    graph = PageGraph(entities=[
        ExtractedEntity(type="product", name="A650-GA70-PU02", aliases=["A650 Pro"]),   # 정식 이름, 별칭이 페이지에
        ExtractedEntity(type="product", name="N5800", aliases=["엔5800"]),               # 정식 이름, 별칭도 페이지에 없음
        ExtractedEntity(type="product", name="Z9999", aliases=["A650 Pro"]),            # 정식 이름이 아님
    ])
    kept = extractor._keep_grounded(graph, "A650 Pro 모델", {"a650ga70pu02", "n5800"})
    assert [(e.name, e.aliases) for e in kept.entities] == [("A650-GA70-PU02", ["A650 Pro"])]
    # 정식 이름 목록이 없으면 예전처럼 이름이 페이지에 있어야 한다
    assert extractor._keep_grounded(PageGraph(entities=[
        ExtractedEntity(type="product", name="A650-GA70-PU02", aliases=["A650 Pro"])]), "A650 Pro 모델").entities == []


def test_flag_off_keeps_old_prompt_and_no_refs(g, monkeypatch):
    monkeypatch.setattr(config, "GRAPH_SPEC_SEED_ENABLED", False)
    llm = FakeLLM({"N5800": PageGraph(entities=[ExtractedEntity(type="product", name="N5800")])})
    _use_fake(monkeypatch, llm)
    file_id = g.add_file("n5800.pdf", ["N5800 무게"])

    service.index_file(file_id)

    assert llm.calls[0][0]["content"] == extractor._system_prompt([])  # 예전 프롬프트 그대로 (상위 개념 없음)
    assert "사양 DB" not in llm.calls[0][0]["content"]
    assert _entities(g.db)["N5800"]["ref_id"] is None


# ---------------------------------------------------------------- H4 검색 결과를 사양으로 잇기

@pytest.fixture
def docs(g):
    """N5800 인증서(N5800 -[has_certification]-> 안전확인 신고)와 파생 모델 문서. 파생 모델 N5800-GB70-PU02를 등록하고 심는다."""
    g.variant = g.spec.create_product("N5800-GB70-PU02", parent_id=g.n5800["id"])
    cert = g.add_file("n5800_kc.pdf", ["N5800 안전확인 신고 인증서"])
    g.graph.replace_page(cert, 1, PageGraph(
        entities=[ExtractedEntity(type="product", name="N5800"),
                  ExtractedEntity(type="certification", name="안전확인 신고")],
        relations=[ExtractedRelation(source="N5800", type="has_certification", target="안전확인 신고")],
    ), link_specs=True)
    variant_doc = g.add_file("pu02_quote.pdf", ["N5800-GB70-PU02 견적"])
    g.graph.replace_page(variant_doc, 1, PageGraph(entities=[ExtractedEntity(type="product", name="N5800-GB70-PU02")]),
                         link_specs=True)
    g.graph.seed_specs()
    return g


def test_graph_search_matched_has_spec_ref(docs):
    result = service.search_graph("N5800 무게")
    assert result["matched"] == [{"name": "N5800", "type": "product", "ref_type": "product", "ref_id": docs.n5800["id"]}]


def test_n5800_and_variant_are_different_entities(docs):
    entities = _entities(docs.db)
    assert entities["N5800"]["id"] != entities["N5800-GB70-PU02"]["id"]
    assert entities["N5800-GB70-PU02"]["ref_id"] == docs.variant["id"]
    # 파생 모델만 물으면 상위 모델은 질문에 따로 나오지 않았으므로 matched에 넣지 않는다
    assert [m["name"] for m in service.search_graph("N5800-GB70-PU02 KC 인증")["matched"]] == ["N5800-GB70-PU02"]
    # 둘 다 적으면 둘 다
    assert {m["name"] for m in service.search_graph("N5800과 N5800-GB70-PU02 비교")["matched"]} == {"N5800", "N5800-GB70-PU02"}


def test_variant_question_gets_parent_documents_as_candidates_only(docs):
    result = service.search_graph("N5800-GB70-PU02 인증 자료")

    by_name = {d["original_name"]: d for d in result["documents"]}
    assert "via" not in by_name["pu02_quote.pdf"]
    assert by_name["n5800_kc.pdf"]["via"] == "상위 모델 N5800"
    assert result["documents"][-1]["original_name"] == "n5800_kc.pdf"  # 후보는 뒤에
    # 상위 모델의 인증 관계는 파생 모델 결과에 넣지 않는다
    assert all("안전확인 신고" not in r for r in result["relations"])
    assert "N5800-GB70-PU02 -[variant_of]-> N5800 (사양 DB)" in result["relations"]


def test_graph_search_tool_doc_mentions_ref_and_via():
    from tools.tool import graph_search

    assert "get_specs(owner_type=ref_type, owner_id=ref_id)" in graph_search.description
    assert "via" in graph_search.description and "그대로 적용된다고 쓰지 않습니다" in graph_search.description
