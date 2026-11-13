"""H: 그래프를 만들 때 사양 DB 참조 (저장 구조, 심기, 추출 정식 이름, 검색 결과를 사양으로 잇기)."""
import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if not hasattr(sys.modules.get("parser"), "__path__"):
    sys.modules.pop("parser", None)

from graph_rag import extractor  # noqa: E402
from graph_rag.types import NON_EXTRACT_RELATIONS, RELATION_TYPES, ExtractedRelation  # noqa: E402
from repository.graph_repository import GraphRepository  # noqa: E402
from repository.repo_connect import Database  # noqa: E402

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
