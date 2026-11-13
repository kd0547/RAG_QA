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
