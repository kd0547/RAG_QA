"""GR1: 시스템이 만드는 상위 개념이 코드·DB·프롬프트 어디에도 없다."""
import json
import sqlite3
import sys
from pathlib import Path

if not hasattr(sys.modules.get("parser"), "__path__"):
    sys.modules.pop("parser", None)

from agent.prompt import render_prompt  # noqa: E402
from graph_rag import service  # noqa: E402
from graph_rag.defaults import DEFAULT_ENTITY_TYPES  # noqa: E402
from graph_rag.types import RELATION_TYPES, ExtractedEntity, PageGraph  # noqa: E402
from repository.graph_migration import remove_system_concepts  # noqa: E402
from repository.graph_repository import GraphRepository  # noqa: E402
from repository.repo_connect import Database  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _concept_db(path: Path) -> None:
    """옛 서버가 aliases.yaml로 심은 개념, 사람이 넣은 수동 관계·차단·속성까지 있는 DB."""
    Database(str(path))
    with sqlite3.connect(path) as conn:
        conn.execute("pragma foreign_keys = on")
        conn.executemany("INSERT INTO graph_entity (id, type, name, norm, creation_origin) VALUES (?,?,?,?,?)", [
            (1, "concept", "KC 인증", "kc인증", "seed"), (2, "certification", "안전확인 신고", "안전확인신고", "seed"),
            (3, "product", "N5800", "n5800", "manual"), (4, "concept", "조달 묶음", "조달묶음", "manual"),
        ])
        conn.execute("INSERT INTO graph_alias (entity_id, alias, alias_norm) SELECT id, name, norm FROM graph_entity")
        conn.execute("""INSERT INTO graph_relation_type (key,label,source_entity_types,target_entity_types,builtin)
                        VALUES ('part_of','상위 개념','["certification"]','["concept"]',1),
                               ('custom:x','사용자 관계','["concept","product"]','["certification"]',0)""")
        conn.executemany("INSERT INTO graph_relation (id, src_id, dst_id, type, origin, source_key) VALUES (?,?,?,?,?,?)", [
            (10, 2, 1, "part_of", "seed", "seed::-1"), (11, 2, 4, "part_of", "manual", "manual:11"),
            (12, 3, 2, "has_certification", "manual", "manual:12"), (13, 3, 1, "has_certification", "manual", "manual:13"),
        ])
        conn.execute("INSERT INTO graph_exclusion VALUES (2, 1, 'part_of', '*')")
        conn.execute("INSERT INTO graph_relation_block VALUES ('certification','적합성등록','part_of','concept','kc인증',CURRENT_TIMESTAMP)")
        conn.execute("""INSERT INTO graph_property_definition (key,label,value_type,allowed_entity_types)
                        VALUES ('custom:memo','메모','text','["concept","product"]')""")
        conn.execute("INSERT INTO graph_property_value (entity_id, property_id, value_text) VALUES (1, 1, '묶음 메모')")


def _counts(path: Path) -> dict:
    with sqlite3.connect(path) as conn:
        q = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
        return {
            "concepts": q("SELECT count(*) FROM graph_entity WHERE type='concept'"),
            "part_of": q("SELECT count(*) FROM graph_relation WHERE type='part_of'"),
            "part_of_type": q("SELECT count(*) FROM graph_relation_type WHERE key='part_of'"),
            "exclusions": q("SELECT count(*) FROM graph_exclusion WHERE type='part_of'"),
            "blocks": q("SELECT count(*) FROM graph_relation_block"),
            "values": q("SELECT count(*) FROM graph_property_value"),
            "relations": sorted(r[0] for r in conn.execute("SELECT id FROM graph_relation")),
            "events": [json.loads(r[0]) for r in conn.execute(
                "SELECT after_json FROM graph_edit_event WHERE action='migration' AND target_kind='schema'")],
            "custom_types": json.loads(q("SELECT source_entity_types FROM graph_relation_type WHERE key='custom:x'")),
            "memo_types": json.loads(q("SELECT allowed_entity_types FROM graph_property_definition WHERE key='custom:memo'")),
        }


def test_migration_removes_all_system_concepts_and_is_idempotent(tmp_path):
    path = tmp_path / "old.db"
    _concept_db(path)

    Database(str(path))  # 서버 시작
    first = _counts(path)
    Database(str(path))  # 다시 시작
    second = _counts(path)

    assert first == second
    assert (first["concepts"], first["part_of"], first["part_of_type"], first["exclusions"], first["blocks"], first["values"]) == (0, 0, 0, 0, 0, 0)
    # 사람이 넣은 수동 관계 중 개념과 무관한 것(12)은 남는다. 개념을 가리키던 13은 개념과 함께 지운다
    assert first["relations"] == [12]
    assert len(first["events"]) == 1 and first["events"][0]["entities"] == 2 and first["events"][0]["relations"] == 3
    assert first["custom_types"] == ["product"] and first["memo_types"] == ["product"]


def test_direct_call_twice_reports_zero_second_time(tmp_path):
    path = tmp_path / "g.db"
    db = Database(str(path))
    with db.transaction() as conn:
        assert not any(remove_system_concepts(conn).values())


def test_no_concept_type_relation_or_extract_field():
    assert "concept" not in {t["key"] for t in DEFAULT_ENTITY_TYPES} and "part_of" not in RELATION_TYPES
    assert "concept" not in ExtractedEntity.model_fields
    assert not (ROOT / "aliases.yaml").exists()


# 옛 프롬프트(v2·v3)에 있던 문구. 본문은 지웠지만 담당자가 이 문구를 붙여 넣은 프롬프트를 고를 수 있다
OLD_PROMPT_TEXT = (
    "**용어 별칭 (표준 이름 = 별칭)**\n$aliases\n\n"
    "| graph_search | 질문의 모델명·인증·부품·규격으로 관련 문서(file_id)와 페이지를 찾는다. "
    "상위 개념(예: KC 인증)은 속한 인증 종류로 펼쳐 준다 |\n"
    '- 상위 개념이 펼쳐졌으면 속한 종류마다 문서를 찾고, 찾지 못한 종류는 "문서 없음"으로 밝힌다.\n'
    "- 끝 줄\n"
)


def test_system_prompt_has_no_concepts_even_with_old_prompts():
    for text in (OLD_PROMPT_TEXT, OLD_PROMPT_TEXT.replace("\n", "\r\n")):
        rendered = render_prompt(text)
        assert "상위 개념" not in rendered and "용어 별칭" not in rendered and "$aliases" not in rendered
        assert "끝 줄" in rendered


def test_graph_search_has_no_expanded(tmp_path, monkeypatch):
    db = Database(str(tmp_path / "g.db"))
    graph = GraphRepository(db)
    monkeypatch.setattr(service, "graph_repo", graph)
    with db.transaction() as conn:
        conn.execute("INSERT INTO file (file_id, original_name, stored_path) VALUES ('f', 'a.pdf', 'a.pdf')")
    graph.replace_page("f", 1, PageGraph(entities=[ExtractedEntity(type="product", name="N5800")]))

    result = service.search_graph("N5800 KC인증")

    assert "expanded" not in result and [m["name"] for m in result["matched"]] == ["N5800"]


def test_code_has_no_system_concept_entry_points():
    sources = {p: p.read_text(encoding="utf-8") for p in [
        ROOT / "main.py", ROOT / "agent" / "agent.py", ROOT / "agent" / "prompt.py", ROOT / "graph_rag" / "extractor.py",
        ROOT / "graph_rag" / "service.py", ROOT / "repository" / "graph_repository.py", ROOT / "tools" / "tool.py",
    ]}
    for path, text in sources.items():
        for word in ("seed_concepts", "list_concepts", "concept_members", "_graph_concepts", "ALIASES", "aliases.yaml", "expanded"):
            assert word not in text, (path.name, word)
