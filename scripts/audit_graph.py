"""지식 그래프 점검 (읽기 전용, 지시서 GR0). 결과를 표준 출력에 마크다운으로 낸다. 데이터를 고치지 않는다.

사용 예 (프로젝트 루트에서):
    .venv/Scripts/python.exe scripts/audit_graph.py                       # storage/mail.db
    .venv/Scripts/python.exe scripts/audit_graph.py --db 사본.db > 결과.md

점검 항목
1. 개체 종류별·출처별(creation_origin) 개수, 관계 종류별·출처별(origin) 개수
2. 상위 개념(concept) 개체, part_of 관계 (출처 포함)
3. 관계 종류의 허용 출발·도착 종류를 어긴 관계 (출처, 문서·페이지)
4. 식별자 규칙(GR3-3)을 어기는 개체 (출처 포함)
5. 사양 DB 모델명과 정식 이름 맞춤 키(GR3-4)가 같은데 종류가 다른 개체
6. 관계도 등장 위치도 없는 개체 수

두 스키마를 모두 읽는다: GR2 이전(개체 종류 테이블 없음)이면 기본 종류 규칙으로, 이후면 graph_entity_type을 읽는다.
운영 DB는 sqlite3 `mode=ro`로만 연다. 저장소(repository) 모듈을 임포트하지 않는다
(임포트하면 운영 DB를 열고 마이그레이션까지 한다).
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from graph_rag.rules import DEFAULT_VENDOR_PREFIXES, has_identifier, spec_match_keys  # noqa: E402  (순수 함수)

DEFAULT_DB = ROOT / "storage" / "mail.db"

# GR2 이전 DB의 식별자 규칙 (GR2 기본 종류 표의 requires_identifier)
LEGACY_IDENTIFIER_TYPES = {"product_line", "product", "component", "cert_number"}


def connect_readonly(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _cell(value) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ")


def _table(headers: list[str], rows: list[list]) -> list[str]:
    if not rows:
        return ["(없음)"]
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in rows]
    return lines


def _tables(conn) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}


def _columns(conn, table: str) -> set[str]:
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def entity_rules(conn, tables) -> tuple[str, dict[str, bool]]:
    """(스키마 이름, {종류: 식별자 필요 여부})."""
    if "graph_entity_type" in tables:
        rows = conn.execute("SELECT key, requires_identifier FROM graph_entity_type").fetchall()
        return "GR2 이후 (graph_entity_type)", {r["key"]: bool(r["requires_identifier"]) for r in rows}
    return "GR2 이전 (기본 종류 규칙)", {k: True for k in LEGACY_IDENTIFIER_TYPES}


def relation_rules(conn, tables) -> dict[str, tuple[set[str], set[str]]]:
    if "graph_relation_type" not in tables:
        return {}
    return {r["key"]: (set(json.loads(r["source_entity_types"])), set(json.loads(r["target_entity_types"])))
            for r in conn.execute("SELECT key, source_entity_types, target_entity_types FROM graph_relation_type")}


def audit(conn) -> list[str]:
    tables = _tables(conn)
    if "graph_entity" not in tables:
        return ["# 지식 그래프 점검", "", "graph_entity 테이블이 없습니다."]
    entity_cols = _columns(conn, "graph_entity")
    relation_cols = _columns(conn, "graph_relation")
    origin_col = "creation_origin" if "creation_origin" in entity_cols else "'(없음)'"
    name_col = "coalesce(display_name, name)" if "display_name" in entity_cols else "name"
    active_entity = "lifecycle_state='active'" if "lifecycle_state" in entity_cols else "1"
    active_relation = "r.lifecycle_state='active'" if "lifecycle_state" in relation_cols else "1"
    schema_name, identifier_types = entity_rules(conn, tables)
    rel_rules = relation_rules(conn, tables)

    out = ["# 지식 그래프 점검 (읽기 전용)", "", f"- 스키마: {schema_name}"]
    if "graph_entity_type" in tables:
        keys = [r[0] for r in conn.execute("SELECT key FROM graph_entity_type ORDER BY sort_order, key")]
        out.append(f"- 개체 종류: {', '.join(keys)}")
    out.append(f"- 관계 종류: {', '.join(sorted(rel_rules)) or '(테이블 없음)'}")

    # 1. 개수
    out += ["", "## 1. 개체 종류별·출처별 개수 (활성)", ""]
    rows = conn.execute(f"""SELECT type, {origin_col} AS origin, count(*) AS n FROM graph_entity
                            WHERE {active_entity} GROUP BY 1, 2 ORDER BY 1, 2""").fetchall()
    out += _table(["종류", "출처(creation_origin)", "개수"], [[r["type"], r["origin"], r["n"]] for r in rows])
    if "lifecycle_state" in entity_cols:
        states = conn.execute("SELECT lifecycle_state, count(*) FROM graph_entity GROUP BY 1 ORDER BY 1").fetchall()
        out += ["", "상태별: " + ", ".join(f"{s[0]} {s[1]}" for s in states)]
    out += ["", "## 1. 관계 종류별·출처별 개수 (활성)", ""]
    rows = conn.execute(f"""SELECT r.type, r.origin, count(*) AS n FROM graph_relation r
                            WHERE {active_relation} GROUP BY 1, 2 ORDER BY 1, 2""").fetchall()
    out += _table(["관계 종류", "출처(origin)", "개수"], [[r["type"], r["origin"], r["n"]] for r in rows])

    # 2. 상위 개념
    out += ["", "## 2. 상위 개념 개체와 part_of 관계", ""]
    rows = conn.execute(f"SELECT id, {name_col} AS name, {origin_col} AS origin FROM graph_entity WHERE type='concept'").fetchall()
    out += _table(["id", "이름", "출처"], [[r["id"], r["name"], r["origin"]] for r in rows])
    out.append("")
    rows = conn.execute("""SELECT r.id, s.name AS src, d.name AS dst, r.origin FROM graph_relation r
                           JOIN graph_entity s ON s.id=r.src_id JOIN graph_entity d ON d.id=r.dst_id
                           WHERE r.type='part_of' ORDER BY r.id""").fetchall()
    out += _table(["관계 id", "출발", "도착", "출처"], [[r["id"], r["src"], r["dst"], r["origin"]] for r in rows])

    # 3. 허용 종류 위반
    out += ["", "## 3. 허용 출발·도착 종류를 어긴 관계 (활성)", ""]
    file_join = "LEFT JOIN file f ON f.file_id = r.file_id" if "file" in tables else ""
    file_name = "f.original_name" if "file" in tables else "NULL"
    rows = conn.execute(f"""SELECT r.id, r.type, r.origin, r.page, {file_name} AS file_name,
                              s.type AS src_type, s.name AS src, d.type AS dst_type, d.name AS dst
                            FROM graph_relation r JOIN graph_entity s ON s.id=r.src_id JOIN graph_entity d ON d.id=r.dst_id
                            {file_join} WHERE {active_relation} ORDER BY r.id""").fetchall()
    bad = []
    for r in rows:
        rule = rel_rules.get(r["type"])
        if rule is None:
            bad.append([r["id"], r["type"], f"{r['src']}({r['src_type']})", f"{r['dst']}({r['dst_type']})", r["origin"],
                        r["file_name"], r["page"], "등록되지 않은 관계 종류"])
        elif r["src_type"] not in rule[0] or r["dst_type"] not in rule[1]:
            why = []
            if r["src_type"] not in rule[0]:
                why.append(f"출발 {r['src_type']} ∉ {sorted(rule[0])}")
            if r["dst_type"] not in rule[1]:
                why.append(f"도착 {r['dst_type']} ∉ {sorted(rule[1])}")
            bad.append([r["id"], r["type"], f"{r['src']}({r['src_type']})", f"{r['dst']}({r['dst_type']})", r["origin"],
                        r["file_name"], r["page"], "; ".join(why)])
    out.append(f"위반 {len(bad)}건 / 활성 관계 {len(rows)}건")
    out.append("")
    out += _table(["id", "종류", "출발", "도착", "출처", "문서", "페이지", "사유"], bad)

    # 4. 식별자 규칙
    out += ["", "## 4. 식별자 규칙을 어기는 개체 (활성)", "",
            f"식별자가 필요한 종류: {', '.join(sorted(k for k, v in identifier_types.items() if v)) or '없음'}", ""]
    aliases: dict[int, list[str]] = {}
    for row in conn.execute("SELECT entity_id, alias FROM graph_alias"):
        aliases.setdefault(row["entity_id"], []).append(row["alias"])
    entities = conn.execute(f"""SELECT id, type, {name_col} AS name, {origin_col} AS origin,
                                  {'ref_type' if 'ref_type' in entity_cols else 'NULL'} AS ref_type
                                FROM graph_entity WHERE {active_entity} ORDER BY type, id""").fetchall()
    violations = [[e["id"], e["type"], e["name"], e["origin"], e["ref_type"]]
                  for e in entities
                  if identifier_types.get(e["type"]) and not has_identifier([e["name"], *aliases.get(e["id"], [])])]
    out.append(f"위반 {len(violations)}건 (출처별: {dict(Counter(v[3] for v in violations)) or '-'})")
    out.append("")
    out += _table(["id", "종류", "이름", "출처", "사양 참조"], violations)

    # 5. 사양 DB 대조
    out += ["", "## 5. 사양 DB 모델명과 맞춤 키가 같은데 종류가 다른 개체", ""]
    expected: dict[str, set[str]] = {}
    if "product" in tables:
        parents = {r[0] for r in conn.execute("SELECT DISTINCT parent_id FROM product WHERE parent_id IS NOT NULL")}
        for row in conn.execute("SELECT id, model FROM product"):
            kind = "product_line" if row["id"] in parents else "product"
            for key in spec_match_keys(row["model"], DEFAULT_VENDOR_PREFIXES):
                expected.setdefault(key, set()).add(kind)
    if "component" in tables:
        for row in conn.execute("SELECT model FROM component"):
            for key in spec_match_keys(row["model"], DEFAULT_VENDOR_PREFIXES):
                expected.setdefault(key, set()).add("component")
    mismatched = []
    for e in entities:
        kinds: set[str] = set()
        for name in [e["name"], *aliases.get(e["id"], [])]:
            for key in spec_match_keys(name, DEFAULT_VENDOR_PREFIXES):
                kinds |= expected.get(key, set())
        if kinds and e["type"] not in kinds:
            mismatched.append([e["id"], e["type"], e["name"], "/".join(sorted(kinds)), e["origin"]])
    out += _table(["id", "현재 종류", "이름", "사양 DB 기준 종류", "출처"], mismatched)

    # 6. 고립 개체
    mention = "graph_mention" in tables
    isolated = conn.execute(f"""SELECT count(*) FROM graph_entity e WHERE {active_entity.replace('lifecycle_state', 'e.lifecycle_state')}
        AND NOT EXISTS (SELECT 1 FROM graph_relation r WHERE (r.src_id=e.id OR r.dst_id=e.id) AND {active_relation})
        {'AND NOT EXISTS (SELECT 1 FROM graph_mention m WHERE m.entity_id=e.id)' if mention else ''}""").fetchone()[0]
    out += ["", "## 6. 관계도 등장 위치도 없는 개체", "", f"{isolated}개"]
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="지식 그래프 점검 (읽기 전용)")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="점검할 SQLite DB 경로 (기본: storage/mail.db)")
    args = parser.parse_args(argv)
    if not args.db.exists():
        print(f"DB가 없습니다: {args.db}", file=sys.stderr)
        return 1
    with connect_readonly(args.db) as conn:
        lines = audit(conn)
    sys.stdout.reconfigure(encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
