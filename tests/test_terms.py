"""용어집: 입력 규칙, 질문 읽기, 그래프 검색 반영, 표 가져오기, API.

그래프는 문서·사양 DB로만 만들고 용어집은 그래프에 쓰지 않는다. 그래프 검색 때만 질문을 읽는 데 쓴다.
임시 SQLite DB를 쓴다.
"""
import io
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
if not hasattr(sys.modules.get("parser"), "__path__"):
    sys.modules.pop("parser", None)

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from entity.file import create_file  # noqa: E402
from graph_rag import service  # noqa: E402
from graph_rag.types import ExtractedEntity, PageGraph  # noqa: E402
from parser.term_table import build_template, grid_from_text, grid_from_xlsx, rows_from_grid, split_aliases  # noqa: E402
from repository.file_page_repository import FilePageRepository  # noqa: E402
from repository.file_repository import FileRepository  # noqa: E402
from repository.graph_repository import GraphRepository  # noqa: E402
from repository.repo_connect import Database  # noqa: E402
from repository.term_repository import (  # noqa: E402
    TermConflictError, TermError, TermImportError, TermNotFoundError, TermRepository,
)


@pytest.fixture
def env(tmp_path, monkeypatch):
    db = Database(str(tmp_path / "terms.db"))
    files, graph, terms = FileRepository(db), GraphRepository(db), TermRepository(db)
    monkeypatch.setattr(service, "file_repo", files)
    monkeypatch.setattr(service, "page_repo", FilePageRepository(db))
    monkeypatch.setattr(service, "graph_repo", graph)

    def add_file(name: str):
        file = create_file(original_name=name, stored_path=str(tmp_path / name))
        files.file_save(file)
        return file

    return db, graph, terms, add_file


def _entity(type_, name, *aliases):
    return ExtractedEntity(type=type_, name=name, aliases=list(aliases))


def _graph_rows(db):
    with db.get_conn() as conn:
        return (conn.execute("SELECT count(*) FROM graph_entity").fetchone()[0],
                conn.execute("SELECT count(*) FROM graph_alias").fetchone()[0])


# ------------------------------------------------------------ 입력 규칙

def test_create_update_delete_and_history(env):
    db, _, terms, _ = env
    term = terms.create("적합성 등록", ["전자파 인증", "KC 전파", "전자파인증", " "], "entity_type", "certification", "방송통신기자재")
    assert term["aliases"] == ["전자파 인증", "KC 전파"]  # 같은 표기(공백 차이)와 빈 표기는 한 번만
    assert term["target_text"] == "그래프:인증"

    updated = terms.update(term["id"], aliases=["전자파 인증"], description="")
    assert updated["aliases"] == ["전자파 인증"] and updated["description"] == ""
    assert updated["target_type"] == "entity_type"  # 주지 않은 항목은 그대로

    terms.delete(term["id"])
    with pytest.raises(TermNotFoundError):
        terms.get(term["id"])
    with db.get_conn() as conn:
        assert conn.execute("SELECT count(*) FROM term_alias").fetchone()[0] == 0
    assert [c["action"] for c in terms.changes()] == ["delete", "update", "create"]


def test_alias_belongs_to_one_term(env):
    _, _, terms, _ = env
    terms.create("적합성 등록", ["전자파 인증"])
    with pytest.raises(TermConflictError) as exc:
        terms.create("전파 인증", ["전자파인증"])
    assert exc.value.conflicts[0]["term_name"] == "적합성 등록"
    with pytest.raises(TermConflictError):
        terms.create("전자파 인증")  # 표준 이름도 다른 용어의 표기와 겹치면 안 된다


def test_rejects_short_aliases_and_unknown_targets(env):
    _, _, terms, _ = env
    with pytest.raises(TermError):
        terms.create("램", [])
    with pytest.raises(TermError):
        terms.create("메모리 용량", ["m"])
    with pytest.raises(TermError):
        terms.create("메모리 용량", [], "spec_attribute", "no_such_key")
    with pytest.raises(TermError):
        terms.create("메모리 용량", [], "somewhere", "x")


def test_graph_is_not_touched_by_glossary(env):
    db, _, terms, _ = env
    before = _graph_rows(db)
    terms.create("적합성 등록", ["전자파 인증"], "entity_type", "certification")
    terms.create("안전확인 신고", ["전기안전 인증"])
    assert _graph_rows(db) == before


# ------------------------------------------------------------ 질문 읽기

def test_find_in_query_prefers_longer_alias(env):
    _, _, terms, _ = env
    terms.create("KC 인증 서류", ["KC 서류"])
    terms.create("KC 인증", [])
    found = terms.find_in_query("N5800 KC인증 서류 보내주세요")
    assert [t["name"] for t in found] == ["KC 인증 서류"]
    assert found[0]["matched"] == "KC 인증 서류"

    both = terms.find_in_query("KC 인증 서류와 KC 인증 차이")
    assert [t["name"] for t in both] == ["KC 인증 서류", "KC 인증"]


def test_ascii_alias_needs_word_boundary(env):
    _, _, terms, _ = env
    terms.create("메모리 용량", ["RAM", "M.2"])
    assert terms.find_in_query("program 설치") == []
    assert [t["matched"] for t in terms.find_in_query("16GB RAM 이상")] == ["RAM"]
    assert [t["matched"] for t in terms.find_in_query("RAM이 몇 GB인가요")] == ["RAM"]
    assert terms.find_in_query("m.2 슬롯")[0]["name"] == "메모리 용량"


# ------------------------------------------------------------ 그래프 검색

def test_graph_search_finds_entity_by_synonym(env):
    _, graph, terms, add_file = env
    cert = add_file("적합성등록필증.pdf")
    graph.replace_page(cert.file_id, 1, PageGraph(entities=[_entity("product", "N5800"), _entity("certification", "적합성 등록")]))
    terms.create("적합성 등록", ["전자파 인증"], "entity_type", "certification", "방송통신기자재 적합성 등록")

    plain = service.search_graph("N5800 전자파 인증 자료")
    assert {m["name"] for m in plain["matched"]} == {"N5800", "적합성 등록"}
    via = next(m for m in plain["matched"] if m["name"] == "적합성 등록")
    assert via["via_term"] == "적합성 등록"
    assert plain["terms"] == [{
        "question_text": "전자파 인증", "term": "적합성 등록", "aliases": ["전자파 인증"],
        "graph_entities": ["적합성 등록"], "target": "그래프:인증", "description": "방송통신기자재 적합성 등록",
    }]
    assert plain["documents"][0]["original_name"] == "적합성등록필증.pdf"
    assert plain["documents"][0]["matched_terms"] == 2


def test_graph_search_target_type_limits_entities(env):
    _, graph, terms, add_file = env
    file = add_file("a.pdf")
    graph.replace_page(file.file_id, 1, PageGraph(entities=[
        _entity("certification", "KC 적합성"), _entity("organization", "KC 적합성"),
    ]))
    terms.create("KC 적합성", ["전파 인증"], "entity_type", "certification")
    result = service.search_graph("전파 인증")
    assert [m["type"] for m in result["matched"]] == ["certification"]


def test_graph_search_without_terms_is_unchanged(env):
    _, graph, _, add_file = env
    file = add_file("a.pdf")
    graph.replace_page(file.file_id, 1, PageGraph(entities=[_entity("product", "N5800")]))
    result = service.search_graph("N5800 무게")
    assert "terms" not in result and "via_term" not in result["matched"][0]


def test_graph_search_returns_terms_even_without_entities(env):
    _, _, terms, _ = env
    with pytest.raises(TermError):
        terms.create("메모리 용량", ["RAM"], "spec_attribute", "")  # 종류만 고르고 대상을 안 고르면 오류
    terms.create("메모리 용량", ["RAM"])
    result = service.search_graph("RAM 16GB 이상")
    assert result["matched"] == [] and result["terms"][0]["term"] == "메모리 용량"
    assert "terms의 표준 이름" in result["message"]


def test_spec_attribute_target_is_exposed(env):
    db, _, terms, _ = env
    with db.get_conn() as conn:
        conn.execute("INSERT INTO spec_attribute (key, name) VALUES ('ram_gb', '메모리 용량')")
        conn.commit()
    terms.create("메모리 용량", ["주기억장치"], "spec_attribute", "ram_gb")
    term = service.search_graph("주기억장치 16GB")["terms"][0]
    assert term["target"] == "사양:메모리 용량" and term["spec_attribute_key"] == "ram_gb"


# ------------------------------------------------------------ 표 가져오기

def test_parse_table_from_paste():
    grid = grid_from_text("표준 이름\t다른 표기\t연결 대상\t설명\n적합성 등록\t전자파 인증, KC 전파\t그래프:인증\t\n\t\t\t\n안전확인 신고\t전기안전\t\t")
    rows = rows_from_grid(grid)
    assert [(r["name"], r["aliases"], r["target"]) for r in rows] == [
        ("적합성 등록", ["전자파 인증", "KC 전파"], "그래프:인증"),
        ("안전확인 신고", ["전기안전"], ""),
    ]
    assert split_aliases("A\nB; a ,C") == ["A", "B", "C"]
    with pytest.raises(ValueError):
        rows_from_grid([["이름 없음", "x"], ["a", "b"]])


def test_template_round_trip(tmp_path):
    content = build_template([{"name": "적합성 등록", "aliases": ["전자파 인증", "KC 전파"], "target": "그래프:인증", "description": "메모"}])
    path = tmp_path / "t.xlsx"
    path.write_bytes(content)
    rows = rows_from_grid(grid_from_xlsx(path))
    assert rows[0]["name"] == "적합성 등록" and rows[0]["aliases"] == ["전자파 인증", "KC 전파"]
    assert rows[0]["target"] == "그래프:인증" and rows[0]["description"] == "메모"


def test_plan_marks_new_update_conflict_error(env):
    _, _, terms, _ = env
    terms.create("적합성 등록", ["전자파 인증"])
    terms.create("안전확인 신고", ["전기안전"])
    plan = terms.plan_import([
        {"name": "적합성 등록", "aliases": ["KC 전파", "전자파 인증"]},     # 기존 용어에 표기 추가
        {"name": "안전확인 신고", "aliases": ["전기안전"]},                  # 바뀌는 것 없음
        {"name": "전파 인증", "aliases": ["전기안전"]},                      # 다른 용어의 표기
        {"name": "전자파 인증"},                                             # 표준 이름이 다른 용어의 표기
        {"name": "새 용어", "aliases": ["KC 전파"]},                         # 같은 표 첫 행과 겹침
        {"name": "", "aliases": ["이름 없음"]},                              # 표준 이름 없음
        {"name": "규격", "target": "없는 대상"},                             # 모르는 연결 대상
        {"name": "건너뛸 용어", "skip": True},
    ])
    assert [r["status"] for r in plan["rows"]] == ["update", "unchanged", "conflict", "conflict", "conflict", "error", "error", "skip"]
    assert plan["rows"][0]["added_aliases"] == ["KC 전파"]


def test_apply_saves_nothing_when_blocked_and_only_adds(env):
    _, _, terms, _ = env
    original = terms.create("적합성 등록", ["전자파 인증"], description="기존 설명")
    rows = [
        {"name": "적합성 등록", "aliases": ["KC 전파"], "description": ""},
        {"name": "안전확인 신고", "aliases": ["전기안전"], "target": "그래프:인증"},
        {"name": "충돌", "aliases": ["전자파 인증"]},
    ]
    with pytest.raises(TermImportError) as exc:
        terms.apply_import(rows)
    assert [r["status"] for r in exc.value.rows] == ["update", "new", "conflict"]
    assert len(terms.list_terms()) == 1

    rows[2]["skip"] = True
    summary = terms.apply_import(rows, source="import:t.xlsx")
    assert summary == {"created": 1, "updated": 1, "unchanged": 0, "skipped": 1}
    merged = terms.get(original["id"])
    assert merged["aliases"] == ["전자파 인증", "KC 전파"]  # 엑셀에 없는 표기를 지우지 않는다
    assert merged["description"] == "기존 설명"  # 빈 칸은 기존 값을 지우지 않는다
    assert {c["source"] for c in terms.changes()} >= {"import:t.xlsx"}


# ------------------------------------------------------------ API

@pytest.fixture
def client(env, monkeypatch):
    from app.routers import terms as router_module

    _, graph, terms, _ = env
    monkeypatch.setattr(router_module, "term_repo", terms)
    monkeypatch.setattr(router_module, "graph_repo", graph)
    app = FastAPI()
    app.include_router(router_module.router)
    with TestClient(app) as c:
        yield c, terms


def test_api_crud_and_errors(client):
    c, _ = client
    created = c.post("/graph/terms", json={"name": "적합성 등록", "aliases": ["전자파 인증"]})
    assert created.status_code == 201
    term_id = created.json()["id"]
    assert c.post("/graph/terms", json={"name": "다른 용어", "aliases": ["전자파인증"]}).status_code == 409
    assert c.post("/graph/terms", json={"name": "x"}).status_code == 400
    assert c.patch(f"/graph/terms/{term_id}", json={"description": "메모"}).json()["description"] == "메모"
    assert [t["name"] for t in c.get("/graph/terms", params={"q": "전자파"}).json()] == ["적합성 등록"]
    assert c.get("/graph/terms/resolve", params={"q": "전자파 인증 자료"}).json()["terms"][0]["name"] == "적합성 등록"
    assert {t["key"] for t in c.get("/graph/terms/targets").json()["entity_type"]} >= {"certification", "product"}
    assert c.delete(f"/graph/terms/{term_id}").status_code == 204
    assert c.patch(f"/graph/terms/{term_id}", json={"description": "x"}).status_code == 404


def test_api_import_flow(client):
    c, terms = client
    terms.create("적합성 등록", ["전자파 인증"])
    template = c.get("/graph/terms/template")
    assert template.status_code == 200 and template.content[:2] == b"PK"

    preview = c.post("/graph/terms/import/parse", files={"file": ("t.xlsx", io.BytesIO(template.content))}).json()
    assert preview["source"] == "t.xlsx" and [r["status"] for r in preview["rows"]] == ["unchanged"]

    text = "표준 이름\t다른 표기\n안전확인 신고\t전기안전\n충돌\t전자파 인증"
    preview = c.post("/graph/terms/import/parse", data={"text": text}).json()
    assert [r["status"] for r in preview["rows"]] == ["new", "conflict"]
    rows = [{k: r[k] for k in ("line", "name", "aliases", "target", "description", "skip")} for r in preview["rows"]]
    blocked = c.post("/graph/terms/import/apply", json={"source": "붙여넣기", "rows": rows})
    assert blocked.status_code == 400 and blocked.json()["detail"]["rows"][1]["status"] == "conflict"

    rows[1]["aliases"] = []  # 미리보기에서 겹치는 표기를 지웠다
    assert [r["status"] for r in c.post("/graph/terms/import/check", json={"rows": rows}).json()["rows"]] == ["new", "new"]
    done = c.post("/graph/terms/import/apply", json={"source": "붙여넣기", "rows": rows})
    assert done.json() == {"created": 2, "updated": 0, "unchanged": 0, "skipped": 0}
    assert c.post("/graph/terms/import/parse", data={"text": ""}).status_code == 400


# ------------------------------------------------------------ 묶음 (2단계)

def _kc(terms):
    emc = terms.create("적합성 등록", ["전자파 인증"], "entity_type", "certification")
    safety = terms.create("안전확인 신고", ["전기안전 인증"])
    bundle = terms.create("KC 인증 자료", ["KC 인증", "KC 서류"], members=[emc["id"], safety["id"]])
    return emc, safety, bundle


def test_bundle_create_and_rules(env):
    _, _, terms, _ = env
    emc, safety, bundle = _kc(terms)
    assert bundle["kind"] == "bundle" and [m["name"] for m in bundle["members"]] == ["적합성 등록", "안전확인 신고"]
    assert terms.get(emc["id"])["bundles"] == [{"id": bundle["id"], "name": "KC 인증 자료"}]
    assert {t["name"]: t["kind"] for t in terms.list_terms()} == {"KC 인증 자료": "bundle", "안전확인 신고": "term", "적합성 등록": "term"}

    with pytest.raises(TermError):  # 구성 용어는 지우지 못한다
        terms.delete(emc["id"])
    with pytest.raises(TermError):  # 묶음 안에 묶음
        terms.create("인증 서류 전부", members=[bundle["id"]])
    with pytest.raises(TermError):  # 구성 용어가 묶음이 되면 묶음 안에 묶음
        terms.update(emc["id"], members=[safety["id"]])
    with pytest.raises(TermError):  # 자기 자신
        terms.update(bundle["id"], members=[bundle["id"]])

    unbundled = terms.update(bundle["id"], members=[])
    assert unbundled["kind"] == "term"
    terms.delete(emc["id"])  # 이제 어느 묶음에도 없다


def test_find_in_query_returns_bundle_members(env):
    _, _, terms, _ = env
    _kc(terms)
    [found] = terms.find_in_query("N5800 KC인증 자료 보내주세요")
    assert found["kind"] == "bundle" and found["matched"] == "KC 인증 자료"
    assert [m["name"] for m in found["members"]] == ["적합성 등록", "안전확인 신고"]
    assert found["members"][0]["alias_norms"] == ["적합성등록", "전자파인증"]


def test_graph_search_expands_bundle_into_members(env):
    _, graph, terms, add_file = env
    emc_doc, safety_doc, both_doc = add_file("적합등록.pdf"), add_file("안전확인.pdf"), add_file("인증 모음.pdf")
    graph.replace_page(emc_doc.file_id, 1, PageGraph(entities=[_entity("product", "N5800"), _entity("certification", "적합성 등록")]))
    graph.replace_page(safety_doc.file_id, 1, PageGraph(entities=[_entity("certification", "전기안전 인증")]))
    graph.replace_page(both_doc.file_id, 1, PageGraph(entities=[
        _entity("certification", "적합성 등록"), _entity("certification", "전기안전 인증")]))
    _kc(terms)

    result = service.search_graph("N5800 KC인증 자료")

    by_name = {m["name"]: m for m in result["matched"]}
    assert by_name["적합성 등록"]["via_term"] == "적합성 등록" and by_name["적합성 등록"]["via_bundle"] == "KC 인증 자료"
    assert by_name["전기안전 인증"]["via_term"] == "안전확인 신고"
    [term] = result["terms"]
    assert term["kind"] == "bundle" and term["term"] == "KC 인증 자료" and term["graph_entities"] == []
    assert [(m["term"], m["graph_entities"]) for m in term["members"]] == [
        ("적합성 등록", ["적합성 등록"]), ("안전확인 신고", ["전기안전 인증"])]
    # N5800 + 구성 용어 2개: 구성 용어를 모두 담은 문서와 N5800 문서가 앞에 온다
    assert [d["matched_terms"] for d in result["documents"]][:2] == [2, 2]
    assert {d["original_name"] for d in result["documents"][:2]} == {"적합등록.pdf", "인증 모음.pdf"}


def test_graph_search_bundle_member_missing_in_graph(env):
    _, _, terms, _ = env
    _kc(terms)
    result = service.search_graph("KC 서류 주세요")
    assert result["matched"] == []
    assert [m["graph_entities"] for m in result["terms"][0]["members"]] == [[], []]


def test_import_bundles_with_rows_in_same_table_and_existing_terms(env):
    _, _, terms, _ = env
    existing = terms.create("안전확인 신고", ["전기안전 인증"])
    rows = [
        {"name": "KC 인증 자료", "aliases": ["KC 인증"], "members": ["적합성 등록", "전기안전 인증"]},  # 종류를 비우면 묶음
        {"name": "적합성 등록", "aliases": ["전자파 인증"], "kind": "용어"},
        {"name": "없는 묶음", "kind": "묶음"},
        {"name": "모르는 구성", "members": ["없는 용어"]},
        {"name": "묶음 속 묶음", "members": ["KC 인증 자료"]},
        {"name": "용어인데 구성", "kind": "용어", "members": ["적합성 등록"]},
    ]
    plan = terms.plan_import(rows)
    assert [r["status"] for r in plan["rows"]] == ["new", "new", "error", "error", "error", "error"]
    assert [ref["name"] for ref in plan["rows"][0]["member_refs"]] == ["적합성 등록", "안전확인 신고"]

    summary = terms.apply_import(rows[:2])
    assert summary["created"] == 2
    bundle = next(t for t in terms.list_terms() if t["name"] == "KC 인증 자료")
    assert [m["name"] for m in bundle["members"]] == ["적합성 등록", "안전확인 신고"]
    assert terms.get(existing["id"])["bundles"][0]["name"] == "KC 인증 자료"

    # 다시 가져오면 바뀜 없음. 구성 용어를 더하기만 한다 (엑셀에 없는 구성 용어를 빼지 않는다)
    terms.create("시험성적서", [])
    again = terms.plan_import([{"name": "KC 인증 자료", "members": ["시험성적서"]}])
    assert again["rows"][0]["status"] == "update" and again["rows"][0]["changes"] == ["구성 추가: 시험성적서"]
    terms.apply_import([{"name": "KC 인증 자료", "members": ["시험성적서"]}])
    assert [m["name"] for m in terms.get(bundle["id"])["members"]] == ["적합성 등록", "안전확인 신고", "시험성적서"]


def test_import_rejects_member_becoming_bundle(env):
    _, _, terms, _ = env
    _kc(terms)
    plan = terms.plan_import([{"name": "적합성 등록", "members": ["안전확인 신고"]}])
    assert plan["rows"][0]["status"] == "error"


def test_template_round_trip_with_bundles(tmp_path):
    content = build_template([{"name": "KC 인증 자료", "aliases": ["KC 인증"], "kind": "묶음",
                               "members": ["적합성 등록", "안전확인 신고"], "target": "", "description": ""}])
    path = tmp_path / "b.xlsx"
    path.write_bytes(content)
    [row] = rows_from_grid(grid_from_xlsx(path))
    assert row["kind"] == "묶음" and row["members"] == ["적합성 등록", "안전확인 신고"]


def test_api_bundle_and_resolve(client):
    c, terms = client
    emc = terms.create("적합성 등록", ["전자파 인증"])
    safety = terms.create("안전확인 신고", [])
    created = c.post("/graph/terms", json={"name": "KC 인증 자료", "aliases": ["KC 인증"], "members": [emc["id"], safety["id"]]})
    assert created.status_code == 201 and created.json()["kind"] == "bundle"
    resolved = c.get("/graph/terms/resolve", params={"q": "KC 인증 서류"}).json()["terms"][0]
    assert [m["name"] for m in resolved["members"]] == ["적합성 등록", "안전확인 신고"]
    assert "alias_norms" not in resolved and all("graph_entities" in m for m in resolved["members"])
    assert c.delete(f"/graph/terms/{emc['id']}").status_code == 400
    assert c.patch(f"/graph/terms/{created.json()['id']}", json={"members": []}).json()["kind"] == "term"
