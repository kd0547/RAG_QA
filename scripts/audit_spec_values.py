"""사양 DB 점검 (읽기 전용). 결과를 표준 출력에 마크다운으로 낸다. 데이터를 고치지 않는다.

사용 예 (프로젝트 루트에서):
    .venv/Scripts/python.exe scripts/audit_spec_values.py                 # storage/mail.db
    .venv/Scripts/python.exe scripts/audit_spec_values.py --db 사본.db > docs/dev_log/E-spec-audit.md

점검 항목 (지시서 E1-2)
1. 값 문자열의 단위가 속성 단위와 다른 값 (예: 단위가 GB인 속성에 1TB). 환산할 수 있는 것과 확인이 필요한 것을 나눈다
2. 이름이 비슷한 속성 쌍 (예: tbw / ssd_tbw)
3. number 속성인데 value_num이 NULL인 값
4. 값이 없는 제품·부품, 제품-부품 연결 수, 근거 문서가 적힌 값 수

운영 DB는 sqlite3 `mode=ro`로만 연다. 저장소(repository) 모듈을 임포트하지 않는다
(임포트하면 운영 DB를 열고 마이그레이션까지 한다).
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from entity.spec import DEFAULT_ATTRIBUTES  # noqa: E402  (상수만 있는 모듈)
from entity.spec_units import _key, read_number  # noqa: E402  (순수 함수)
from graph_rag.types import normalize  # noqa: E402  (순수 함수)

DEFAULT_DB = ROOT / "storage" / "mail.db"


def connect_readonly(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _cell(value) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ")


def _table(headers: list[str], rows: list[list]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in rows]
    return lines


def _owner_names(conn) -> dict[tuple[str, str], str]:
    names = {("product", r["id"]): r["model"] for r in conn.execute("SELECT id, model FROM product")}
    names |= {("component", r["id"]): f"{r['model']} ({r['kind']})" for r in conn.execute("SELECT id, model, kind FROM component")}
    return names


def unit_findings(conn, owners) -> tuple[list[list], list[list]]:
    """(환산할 수 있는 다른 단위, 단위 확인 필요). number 속성만 본다."""
    convertible, problems = [], []
    rows = conn.execute(
        """SELECT v.id, v.owner_type, v.owner_id, v.attribute_key, a.unit, a.category, v.value_text, v.value_num
           FROM spec_value v JOIN spec_attribute a ON a.key = v.attribute_key
           WHERE a.data_type = 'number' ORDER BY v.attribute_key, v.id"""
    ).fetchall()
    for row in rows:
        result = read_number(row["value_text"], row["unit"], row["category"])
        owner = owners.get((row["owner_type"], row["owner_id"]), row["owner_id"])
        if result.problem:
            problems.append([row["attribute_key"], row["unit"], owner, row["value_text"], row["value_num"], result.problem])
        elif result.unit and _key(result.unit) != _key(row["unit"]) and result.value != result.raw:
            convertible.append([row["attribute_key"], row["unit"], owner, row["value_text"], row["value_num"],
                                f"{result.raw:g}{result.unit} → {result.value:g}{row['unit']}"])
    return convertible, problems


def _tokens(key: str) -> list[str]:
    return [t for t in key.split("_") if t]


def _token_match(a: str, b: str) -> bool:
    return a == b or (min(len(a), len(b)) >= 3 and (a.startswith(b) or b.startswith(a)))


def similar_pairs(attributes: list[sqlite3.Row]) -> list[list]:
    """이름이 비슷한 속성 쌍. 기본 속성끼리는 설계로 나눈 것이라(ram_gb / ram_max_gb) 하나 이상이 기본 속성이 아닐 때만 본다."""
    defaults = {a.key: a for a in DEFAULT_ATTRIBUTES}
    alias_norms = {key: {normalize(x) for x in (a.aliases or ())} | {normalize(a.name), normalize(key)}
                   for key, a in defaults.items()}
    pairs: dict[tuple[str, str], list[str]] = defaultdict(list)
    for i, first in enumerate(attributes):
        for second in attributes[i + 1:]:
            a, b = first["key"], second["key"]
            if a in defaults and b in defaults:
                continue
            reasons = []
            if normalize(first["name"]) == normalize(second["name"]):
                reasons.append("이름이 공백·기호만 다름")
            for this, other in ((first, second), (second, first)):
                if other["key"] in defaults and this["key"] not in defaults:
                    hits = {normalize(this["key"]), normalize(this["name"])} & alias_norms[other["key"]]
                    if hits:
                        reasons.append(f"{this['key']}의 키·이름이 기본 속성 {other['key']}의 별칭과 같음")
            ta, tb = _tokens(a), _tokens(b)
            short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
            if short and all(any(_token_match(s, t) for t in long_) for s in short):
                reasons.append("키 단어가 겹침")
            if reasons:
                pairs[(a, b)] = reasons
    rows = []
    by_key = {a["key"]: a for a in attributes}
    for (a, b), reasons in sorted(pairs.items()):
        rows.append([
            f"{a} ({by_key[a]['name']}, {by_key[a]['data_type']}{', ' + by_key[a]['unit'] if by_key[a]['unit'] else ''})",
            f"{b} ({by_key[b]['name']}, {by_key[b]['data_type']}{', ' + by_key[b]['unit'] if by_key[b]['unit'] else ''})",
            by_key[a]["usage"], by_key[b]["usage"], "; ".join(dict.fromkeys(reasons)),
        ])
    return rows


def audit(conn: sqlite3.Connection, db_label: str) -> str:
    owners = _owner_names(conn)
    lines = [f"# 사양 DB 점검 결과", "", f"- 대상: `{db_label}` (읽기 전용으로 열었다. 데이터를 고치지 않았다)", ""]

    counts = {
        "속성": conn.execute("SELECT COUNT(*) FROM spec_attribute").fetchone()[0],
        "제품": conn.execute("SELECT COUNT(*) FROM product").fetchone()[0],
        "부품": conn.execute("SELECT COUNT(*) FROM component").fetchone()[0],
        "사양 값": conn.execute("SELECT COUNT(*) FROM spec_value").fetchone()[0],
        "제품-부품 연결": conn.execute("SELECT COUNT(*) FROM product_component").fetchone()[0],
        "근거 문서(source_file_id)가 적힌 값": conn.execute(
            "SELECT COUNT(*) FROM spec_value WHERE source_file_id IS NOT NULL AND source_file_id != ''").fetchone()[0],
    }
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(spec_attribute)")}
    if "inheritable" in columns:
        counts["상속 허용 속성(inheritable=1)"] = conn.execute(
            "SELECT COUNT(*) FROM spec_attribute WHERE inheritable = 1").fetchone()[0]
    lines += ["## 0. 개수", "", *_table(["항목", "개수"], [[k, v] for k, v in counts.items()]), ""]

    convertible, problems = unit_findings(conn, owners)
    lines += ["## 1. 값의 단위가 속성 단위와 다른 값", "",
              "숫자 속성(`number`)의 값 문자열을 비교 코드(`entity/spec_units.py read_number`)와 같은 규칙으로 읽었다.", "",
              f"### 1-1. 다른 단위지만 환산할 수 있음 ({len(convertible)}건)", "",
              "비교 코드는 이 값을 환산해 판정한다. 저장된 `value_num`은 첫 숫자 그대로라 환산 전 값이다.", ""]
    lines += (_table(["속성", "속성 단위", "대상", "값", "value_num", "읽은 값"], convertible) if convertible else ["없음"]) + [""]
    lines += [f"### 1-2. 단위 확인 필요 ({len(problems)}건)", "", "비교 코드는 이 값을 숫자로 쓰지 않는다 (판정 `unknown`).", ""]
    lines += (_table(["속성", "속성 단위", "대상", "값", "value_num", "사유"], problems) if problems else ["없음"]) + [""]

    attributes = conn.execute(
        """SELECT a.key, a.name, a.data_type, a.unit, a.category,
                  (SELECT COUNT(*) FROM spec_value v WHERE v.attribute_key = a.key) AS usage
           FROM spec_attribute a ORDER BY a.key"""
    ).fetchall()
    pairs = similar_pairs(attributes)
    lines += [f"## 2. 이름이 비슷한 속성 쌍 ({len(pairs)}쌍)", "",
              "기본 속성(`entity/spec.py DEFAULT_ATTRIBUTES`)끼리는 설계로 나눈 것이라 빼고, 하나 이상이 기본 속성이 아닌 쌍만 본다.", ""]
    lines += (_table(["속성 A", "속성 B", "A 값 수", "B 값 수", "이유"], pairs) if pairs else ["없음"]) + [""]

    null_rows = conn.execute(
        """SELECT v.owner_type, v.owner_id, v.attribute_key, v.value_text
           FROM spec_value v JOIN spec_attribute a ON a.key = v.attribute_key
           WHERE a.data_type = 'number' AND v.value_num IS NULL ORDER BY v.attribute_key, v.id"""
    ).fetchall()
    lines += [f"## 3. number 속성인데 value_num이 NULL인 값 ({len(null_rows)}건)", ""]
    lines += (_table(["속성", "대상", "값"], [[r["attribute_key"], owners.get((r["owner_type"], r["owner_id"]), r["owner_id"]),
                                               r["value_text"]] for r in null_rows]) if null_rows else ["없음"]) + [""]

    empty_products = conn.execute(
        """SELECT p.model, p.name FROM product p
           WHERE NOT EXISTS (SELECT 1 FROM spec_value v WHERE v.owner_type = 'product' AND v.owner_id = p.id)
           ORDER BY p.model""").fetchall()
    empty_components = conn.execute(
        """SELECT c.kind, c.model FROM component c
           WHERE NOT EXISTS (SELECT 1 FROM spec_value v WHERE v.owner_type = 'component' AND v.owner_id = c.id)
           ORDER BY c.kind, c.model""").fetchall()
    lines += [f"## 4. 값이 없는 제품 ({len(empty_products)}개)·부품 ({len(empty_components)}개)", ""]
    lines += (_table(["제품 모델", "이름"], [[r["model"], r["name"]] for r in empty_products]) if empty_products else ["제품: 없음"]) + [""]
    lines += (_table(["부품 종류", "부품 모델"], [[r["kind"], r["model"]] for r in empty_components]) if empty_components else ["부품: 없음"]) + [""]
    lines += [f"제품-부품 연결: {counts['제품-부품 연결']}건", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="사양 DB 점검 (읽기 전용)")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite DB 경로 (기본 storage/mail.db)")
    args = parser.parse_args(argv)
    path = Path(args.db)
    if not path.exists():
        print(f"DB가 없습니다: {path}", file=sys.stderr)
        return 1
    with connect_readonly(path) as conn:
        report = audit(conn, path.name)
    sys.stdout.reconfigure(encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
