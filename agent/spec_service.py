"""사양 조회·비교 서비스 (지시서 E2). DB를 읽기만 하는 순수 함수들이고 LLM을 쓰지 않는다.

"RAM 16GB 이상", "TBW 350TB 이상" 같은 조건의 크기 비교와 단위 환산은 여기서 한다.
모델은 조건을 속성 키로 바꾸고 판정 결과를 옮겨 적기만 한다.

(가) resolve_items   모델명으로 제품·부품 찾기 (정규화 완전 일치 → 없으면 어절 단위 포함)
(나) effective_specs 유효 사양 (자기 값 > 허용된 상속 값, 연결된 부품 값)
(다) to_attribute_unit 단위 환산 (entity/spec_units.py)
(라) compare         조건별 판정 met / met_with_option / not_met / unknown
(마) search_items    조건으로 찾기 (그 종류의 모든 대상에 (라)를 돌려 met 순)

판정 규칙
- 값이 없음(행이 없음)과 명시적 미지원(bool 속성의 0)은 다르다: 앞은 unknown, 뒤는 not_met.
- 상위 모델의 값은 속성이 inheritable=1일 때만, 자기 값이 없을 때만 가장 가까운 상위 모델에서 가져온다.
  인증(cert) 속성은 inheritable과 관계없이 물려받지 않는다.
- 제품에 연결된 부품(product_component)의 값만 제품 사양에 넣는다. 옵션으로 연결된 부품의 값은 옵션이다.
- text 속성은 정규화해 같거나(==) 포함할 때(contains)만 met이다. 그 밖에는 not_met이 아니라 unknown이다
  (표기만 다른 같은 값일 수 있다).
"""
from __future__ import annotations

import logging
import re
import sqlite3
from contextlib import contextmanager

import repository
from entity.spec import ATTRIBUTE_CATEGORIES
from entity.spec_units import read_number, to_attribute_unit  # noqa: F401  (to_attribute_unit은 (다)로 다시 내보낸다)
from graph_rag.types import normalize

logger = logging.getLogger(__name__)

OPS = (">=", "<=", ">", "<", "==", "contains", "exists")
NUMERIC_OPS = (">=", "<=", ">", "<", "==")
VERDICTS = ("met", "met_with_option", "not_met", "unknown")
OWNER_TYPES = ("product", "component")
OWNER_LABELS = {"product": "제품", "component": "부품"}

_CATEGORY_ORDER = {key: index for index, key in enumerate(ATTRIBUTE_CATEGORIES)}
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
_TRUE_WORDS = frozenset({"1", "true", "yes", "y", "o", "예", "있음", "지원", "가능", "포함"})
_FALSE_WORDS = frozenset({"0", "false", "no", "n", "x", "아니오", "아니요", "없음", "미지원", "불가", "제외"})


@contextmanager
def _connect():
    conn = repository.spec_repo.db.get_conn()
    try:
        yield conn
    finally:
        conn.close()


# ------------------------------------------------------------------ (가) 대상 찾기

def _tokens(text: str | None) -> frozenset[str]:
    """어절 단위 비교 키. 하이픈으로 이은 모델명은 한 어절이다 (N5800 ≠ N5800-GB70-PU02, A5 규칙)."""
    return frozenset(t for t in (normalize(w) for w in re.split(r"[\s,]+", text or "")) if t)


def _items(conn: sqlite3.Connection, owner_type: str | None, kind: str | None) -> list[dict]:
    items: list[dict] = []
    if owner_type in (None, "product") and kind is None:
        rows = conn.execute(
            """SELECT p.id, p.model, p.name, p.category, p.status, p.parent_id, parent.model AS parent_model
               FROM product p LEFT JOIN product parent ON parent.id = p.parent_id ORDER BY p.model"""
        ).fetchall()
        children: dict[str, list[str]] = {}
        for row in rows:
            if row["parent_id"]:
                children.setdefault(row["parent_id"], []).append(row["model"])
        for row in rows:
            items.append({
                "owner_type": "product", "id": row["id"], "model": row["model"], "name": row["name"] or "",
                "category": row["category"], "vendor": "", "status": row["status"],
                "parent_id": row["parent_id"], "parent_model": row["parent_model"],
                "variants": sorted(children.get(row["id"], [])),
            })
    if owner_type in (None, "component"):
        sql = "SELECT id, kind, model, vendor FROM component" + (" WHERE kind = ?" if kind else "") + " ORDER BY kind, model"
        for row in conn.execute(sql, (kind,) if kind else ()).fetchall():
            items.append({
                "owner_type": "component", "id": row["id"], "model": row["model"], "name": "",
                "kind": row["kind"], "vendor": row["vendor"] or "", "status": None,
                "parent_id": None, "parent_model": None, "variants": [],
            })
    return items


def _public(item: dict) -> dict:
    keys = ("owner_type", "id", "model", "name", "kind" if item["owner_type"] == "component" else "category",
            "vendor", "status", "parent_model", "variants")
    return {k: item.get(k) for k in keys}


def _resolve(conn: sqlite3.Connection, query: str, owner_type: str | None, kind: str | None) -> list[dict]:
    """resolve_items의 본체 (점수 순, 개수 제한 없음)."""
    norm = normalize(query)
    if not norm:
        return []
    items = _items(conn, owner_type, kind)
    exact = [i for i in items if normalize(i["model"]) == norm or (i["name"] and normalize(i["name"]) == norm)]
    if exact:
        matched = exact
    else:
        query_tokens = _tokens(query)
        scored = []
        for item in items:
            best = 0
            for tokens in (_tokens(item["model"]), _tokens(item["name"])):
                if not tokens:
                    continue
                # 질문이 모델명의 일부("Samsung 980")이거나, 모델명 전체가 질문 안에 있을 때("Samsung 980 500GB 대체 모델")만
                if query_tokens <= tokens:
                    best = max(best, 2 * len(query_tokens) + (2 if tokens == query_tokens else 0))
                elif tokens <= query_tokens:
                    best = max(best, 2 * len(tokens) + 1)
            if best:
                scored.append((best, item))
        scored.sort(key=lambda pair: (-pair[0], pair[1]["model"]))
        matched = [item for _, item in scored]
    # 상위 모델과 그 파생 모델이 함께 맞으면 상위 모델만 돌려주고 파생 모델은 variants로 둔다
    product_ids = {i["id"] for i in matched if i["owner_type"] == "product"}
    return [i for i in matched if not (i["owner_type"] == "product" and i["parent_id"] in product_ids)]


def resolve_items(query: str, owner_type: str | None = None, kind: str | None = None, limit: int = 10) -> list[dict]:
    """모델명으로 제품·부품을 찾는다.

    - 정규화(graph_rag.types.normalize)해 모델명·제품 이름과 완전히 같은 것이 있으면 그것만 돌려준다.
    - 없으면 어절 단위로 찾는다: 질문의 어절이 모델명 어절에 모두 들어 있거나, 모델명 어절이 질문에 모두 들어 있을 때.
      하이픈으로 이은 모델명은 한 어절이라 'N5800'으로 'N5800-GB70-PU02'를 찾지 않는다 (A5 규칙).
    - 상위 모델을 물었으면 상위 모델을 돌려주고, 파생 모델은 variants에 모델명으로 싣는다.
    반환: [{owner_type, id, model, name, kind 또는 category, vendor, status, parent_model, variants}]
    """
    with _connect() as conn:
        found = _resolve(conn, query, owner_type, kind)
    return [_public(i) for i in found[:max(1, int(limit or 1))]]


def find_owner(owner_type: str, owner_id: str) -> dict | None:
    """id(없으면 정확한 모델명)로 대상 하나. 없으면 None."""
    if owner_type not in OWNER_TYPES:
        return None
    with _connect() as conn:
        items = _items(conn, owner_type, None)
    by_id = next((i for i in items if i["id"] == owner_id), None)
    if by_id is not None:
        return _public(by_id)
    norm = normalize(owner_id)
    by_model = [i for i in items if normalize(i["model"]) == norm]
    return _public(by_model[0]) if len(by_model) == 1 else None


# ------------------------------------------------------------------ (나) 유효 사양

_VALUE_SELECT = """
    SELECT v.id AS spec_value_id, v.attribute_key, a.name AS attribute_name, a.data_type, a.unit, a.category,
           a.inheritable, v.value_text, v.value_num, v.is_option, v.updated_at
    FROM spec_value v JOIN spec_attribute a ON a.key = v.attribute_key
    WHERE v.owner_type = ? AND v.owner_id = ?
"""


def _value(row: sqlite3.Row, *, inherited_from: str | None = None, via_component: str | None = None,
           option_link: bool = False) -> dict:
    return {
        "spec_value_id": row["spec_value_id"],
        "attribute_key": row["attribute_key"],
        "attribute_name": row["attribute_name"],
        "data_type": row["data_type"],
        "unit": row["unit"],
        "category": row["category"],
        "value_text": row["value_text"],
        "value_num": row["value_num"],
        "is_option": bool(row["is_option"]) or option_link,
        "inherited_from": inherited_from,
        "via_component": via_component,
        "updated_at": row["updated_at"],
    }


def _owner_row(conn: sqlite3.Connection, owner_type: str, owner_id: str) -> sqlite3.Row | None:
    if owner_type == "product":
        return conn.execute("SELECT id, model, parent_id FROM product WHERE id = ?", (owner_id,)).fetchone()
    if owner_type == "component":
        return conn.execute("SELECT id, model, NULL AS parent_id FROM component WHERE id = ?", (owner_id,)).fetchone()
    return None


def _effective(conn: sqlite3.Connection, owner_type: str, owner_id: str, attribute_keys: list[str] | None) -> dict | None:
    owner = _owner_row(conn, owner_type, owner_id)
    if owner is None:
        return None
    wanted = set(attribute_keys) if attribute_keys else None
    values = [_value(r) for r in conn.execute(_VALUE_SELECT, (owner_type, owner_id)).fetchall()]
    own_keys = {v["attribute_key"] for v in values}

    if owner_type == "product":
        # 상위 모델 경로 (가까운 것부터). 순환이 있어도 멈춘다
        ancestors, parent_id, seen = [], owner["parent_id"], {owner_id}
        while parent_id and parent_id not in seen and len(ancestors) < 20:
            seen.add(parent_id)
            row = conn.execute("SELECT id, model, parent_id FROM product WHERE id = ?", (parent_id,)).fetchone()
            if row is None:
                break
            ancestors.append(row)
            parent_id = row["parent_id"]
        taken = set(own_keys)  # 자기 값이 있거나 더 가까운 상위 모델에서 이미 가져온 속성
        for ancestor in ancestors:
            here: set[str] = set()
            for row in conn.execute(_VALUE_SELECT, ("product", ancestor["id"])).fetchall():
                key = row["attribute_key"]
                if key in taken or not row["inheritable"] or row["category"] == "cert":
                    continue
                here.add(key)
                values.append(_value(row, inherited_from=ancestor["model"]))
            taken |= here

        # 연결된 부품의 값만 (연결되지 않은 부품의 값은 제품 사양이 아니다)
        links = conn.execute(
            """SELECT c.id, c.model, pc.is_option FROM product_component pc JOIN component c ON c.id = pc.component_id
               WHERE pc.product_id = ? ORDER BY pc.is_option, c.kind, c.model""",
            (owner_id,),
        ).fetchall()
        for link in links:
            for row in conn.execute(_VALUE_SELECT, ("component", link["id"])).fetchall():
                values.append(_value(row, via_component=link["model"], option_link=bool(link["is_option"])))

    if wanted is not None:
        values = [v for v in values if v["attribute_key"] in wanted]
    values.sort(key=lambda v: (
        _CATEGORY_ORDER.get(v["category"], 99), v["attribute_name"],
        v["via_component"] is not None, v["inherited_from"] is not None, v["is_option"], v["spec_value_id"],
    ))
    known = {r["key"] for r in conn.execute("SELECT key FROM spec_attribute").fetchall()}
    present = {v["attribute_key"] for v in values}
    requested = list(dict.fromkeys(attribute_keys or []))
    return {
        "owner_type": owner_type, "id": owner_id, "model": owner["model"],
        "values": values,
        "missing_attributes": [k for k in requested if k in known and k not in present],
        "unknown_attributes": [k for k in requested if k not in known],
    }


def effective_specs(owner_type: str, owner_id: str, attribute_keys: list[str] | None = None) -> dict | None:
    """제품·부품의 유효 사양. 대상이 없으면 None.

    - 제품: 자기 값이 먼저다. 자기 값이 없는 속성 중 inheritable=1(인증 제외)인 것만 가장 가까운 상위 모델의 값을
      가져오고 inherited_from에 그 모델명을 적는다.
    - 제품에 연결된 부품의 값은 via_component(부품 모델명)와 함께 싣는다. 옵션 연결이면 그 값도 옵션이다.
    - 값마다 spec_value_id, attribute_key, attribute_name, data_type, unit, value_text, value_num, is_option,
      inherited_from, via_component (+ category, updated_at).
    - bool 속성의 0은 "미지원" 값이고, 행이 없으면 값이 없다 (missing_attributes).
    """
    with _connect() as conn:
        return _effective(conn, owner_type, owner_id, attribute_keys)


# ------------------------------------------------------------------ (라) 비교

def _bool_value(text: str | None, number: float | None) -> float | None:
    if number is not None:
        return float(number)
    word = (text or "").strip().lower()
    if word in _TRUE_WORDS:
        return 1.0
    if word in _FALSE_WORDS:
        return 0.0
    return None


def _numeric_test(op: str, left: float, right: float) -> bool:
    left, right = round(left, 9), round(right, 9)
    return {">=": left >= right, "<=": left <= right, ">": left > right, "<": left < right, "==": left == right}[op]


def _fmt(number: float | None) -> str:
    return "?" if number is None else f"{number:g}"


def _decide(outcomes: list[tuple[bool, bool | None]]) -> str:
    """[(옵션 여부, 만족 여부 또는 None=판정 불가)] → verdict."""
    base = [ok for option, ok in outcomes if not option]
    options = [ok for option, ok in outcomes if option]
    if True in base:
        return "met"
    if None in base:
        return "unknown"
    if True in options:
        return "met_with_option"
    if None in options:
        return "unknown"
    return "not_met"


_VERDICT_LABELS = {"met": "만족", "met_with_option": "옵션으로 만족", "not_met": "만족하지 않음", "unknown": "판정 불가"}


def _value_label(value: dict) -> str:
    tags = []
    if value["is_option"]:
        tags.append("옵션")
    if value["inherited_from"]:
        tags.append(f"상위 모델 {value['inherited_from']}")
    if value["via_component"]:
        tags.append(f"부품 {value['via_component']}")
    return value["value_text"] + (f" [{', '.join(tags)}]" if tags else "")


def _judge(condition: dict, values: list[dict], attribute: sqlite3.Row | None) -> dict:
    key = str(condition.get("attribute") or "").strip()
    op = str(condition.get("op") or "").strip()
    raw_value = condition.get("value")
    cond_unit = str(condition.get("unit") or "").strip()
    result = {"attribute": key, "op": op, "value": raw_value, "unit": cond_unit or None,
              "attribute_name": attribute["name"] if attribute else None,
              "values": [{k: v[k] for k in ("value_text", "is_option", "inherited_from", "via_component")} for v in values]}

    def done(verdict: str, reason: str) -> dict:
        return {**result, "verdict": verdict, "reason": reason}

    if attribute is None:
        return done("unknown", f"속성 키가 없습니다: {key}. list_spec_attributes로 키를 확인하세요.")
    if op not in OPS:
        return done("unknown", f"모르는 op입니다: {op} (가능: {', '.join(OPS)})")
    if not values:
        return done("unknown", "값 없음 (사양 DB에 이 속성의 값이 없습니다)")
    data_type, unit, category = attribute["data_type"], attribute["unit"], attribute["category"]
    shown = ", ".join(_value_label(v) for v in values)

    if data_type == "number":
        if op == "exists":
            verdict = _decide([(v["is_option"], True) for v in values])
            return done(verdict, f"값 있음: {shown}")
        if op == "contains":
            return done("unknown", "숫자 속성에는 contains를 쓸 수 없습니다 (>=, <=, >, <, ==)")
        text = str(raw_value if raw_value is not None else "").replace(",", "")
        match = _NUMBER.search(text)
        if match is None:
            return done("unknown", f"조건 값에서 숫자를 읽을 수 없습니다: {raw_value}")
        if cond_unit:
            target = to_attribute_unit(float(match.group()), cond_unit, unit, category)
            if target is None:
                return done("unknown", f"단위 확인 필요: 조건 단위 {cond_unit}를 속성 단위 {unit or '없음'}로 바꿀 수 없습니다")
        else:
            parsed = read_number(text, unit, category)
            if parsed.problem:
                return done("unknown", f"조건 값의 {parsed.problem}")
            target = parsed.value
        outcomes, notes = [], []
        for value in values:
            parsed = read_number(value["value_text"], unit, category)
            if parsed.problem:
                outcomes.append((value["is_option"], None))
                notes.append(f"{_value_label(value)}: {parsed.problem}")
                continue
            ok = _numeric_test(op, parsed.value, target)
            outcomes.append((value["is_option"], ok))
            notes.append(f"{_value_label(value)} = {_fmt(parsed.value)}{unit} {'✓' if ok else '✗'}")
        verdict = _decide(outcomes)
        return done(verdict, f"조건 {op} {_fmt(target)}{unit}: " + "; ".join(notes) + f" → {_VERDICT_LABELS[verdict]}")

    if data_type == "bool":
        if op == "exists":
            want = 1.0
        elif op == "==":
            want = _bool_value(str(raw_value), None)
            if want is None:
                return done("unknown", f"예/아니오 조건 값을 읽을 수 없습니다: {raw_value}")
        else:
            return done("unknown", f"예/아니오 속성에는 ==, exists만 쓸 수 있습니다 ({op})")
        outcomes = []
        for value in values:
            have = _bool_value(value["value_text"], value["value_num"])
            outcomes.append((value["is_option"], None if have is None else have == want))
        verdict = _decide(outcomes)
        label = "지원" if want == 1.0 else "미지원"
        reason = f"조건 {label}: {shown} → {_VERDICT_LABELS[verdict]}"
        if verdict == "not_met":
            reason += " (명시적 값)"
        return done(verdict, reason)

    # text: 정규화해 같거나 포함할 때만 met. 아니면 표기만 다를 수 있어 unknown
    if op == "exists":
        verdict = _decide([(v["is_option"], True) for v in values])
        return done(verdict, f"값 있음: {shown}")
    if op not in ("==", "contains"):
        return done("unknown", f"글자 속성에는 ==, contains, exists만 쓸 수 있습니다 ({op}). 값: {shown}")
    want = normalize(str(raw_value or ""))
    if not want:
        return done("unknown", "조건 값이 비었습니다")
    # 조건 값이 용어집 용어의 표기 하나와 같으면 그 용어의 다른 표기로도 맞춘다 ("스피커" ↔ "speakers")
    term = _glossary_term(str(raw_value), key)
    forms = [want, *(n for n in term["alias_norms"] if n != want)] if term else [want]
    outcomes = []
    via_term = False
    for value in values:
        have = normalize(value["value_text"])
        ok = have == want if op == "==" else want in have
        if not ok and term:
            ok = have in forms if op == "==" else any(form in have for form in forms)
            via_term = via_term or ok
        outcomes.append((value["is_option"], True if ok else None))
    verdict = _decide(outcomes)
    if verdict == "unknown":
        return done(verdict, f"조건 '{raw_value}'와 값 [{shown}]이 글자로 맞지 않습니다. 표기만 다른 같은 값일 수 있어 확인이 필요합니다")
    reason = f"조건 {op} '{raw_value}': {shown} → {_VERDICT_LABELS[verdict]}"
    if via_term:
        reason += f" (용어집 '{term['name']}'의 표기 {', '.join(term['aliases'])}로 맞춤)"
    return done(verdict, reason)


def _glossary_term(text: str, attribute_key: str) -> dict | None:
    """조건 값 전체가 용어집 용어의 표기 하나와 같을 때 그 용어 (모든 표기 포함). 아니면 None.

    묶음은 쓰지 않는다. 연결 대상이 다른 곳(다른 사양 속성, 그래프 종류)인 용어도 쓰지 않는다
    (연결 대상이 없거나 이 속성인 용어만). 근거는 여전히 사양 DB 값이다 — 용어집은 표기를 맞추는 데만 쓴다.
    """
    from repository.term_repository import TermRepository

    try:
        term = TermRepository(repository.spec_repo.db).forms_of(text)
    except Exception:
        logger.warning("용어집을 읽지 못해 글자 그대로 비교합니다", exc_info=True)
        return None
    if term is None or term["kind"] == "bundle":
        return None
    if term["target_type"] and not (term["target_type"] == "spec_attribute" and term["target_key"] == attribute_key):
        return None
    return term


def _compare(conn: sqlite3.Connection, owner_type: str, owner_id: str, conditions: list[dict],
             attributes: dict[str, sqlite3.Row]) -> dict | None:
    keys = [str(c.get("attribute") or "").strip() for c in conditions]
    specs = _effective(conn, owner_type, owner_id, [k for k in keys if k] or None)
    if specs is None:
        return None
    by_key: dict[str, list[dict]] = {}
    for value in specs["values"]:
        by_key.setdefault(value["attribute_key"], []).append(value)
    results = [_judge(c, by_key.get(k, []), attributes.get(k)) for c, k in zip(conditions, keys)]
    return {"owner_type": owner_type, "id": owner_id, "model": specs["model"], "results": results,
            "values": [v for v in specs["values"] if v["attribute_key"] in set(keys)]}


def _attributes(conn: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    return {r["key"]: r for r in conn.execute("SELECT key, name, data_type, unit, category FROM spec_attribute").fetchall()}


def _as_conditions(conditions) -> list[dict]:
    if isinstance(conditions, dict):
        conditions = [conditions]
    return [c for c in conditions or [] if isinstance(c, dict)]


def compare(owner_type: str, owner_id: str, conditions: list[dict]) -> dict | None:
    """조건 목록을 대상의 유효 사양과 비교한다. 대상이 없으면 None.

    조건: {"attribute": "ssd_tbw", "op": ">=", "value": "350", "unit": "TB"} (unit을 비우면 속성 단위, value에 단위를 붙여도 된다)
    op: >=, <=, >, <, ==, contains, exists
    반환: {owner_type, id, model, results: [조건마다 {attribute, attribute_name, op, value, unit, verdict, reason,
           values: [{value_text, is_option, inherited_from, via_component}]}], values: 판정에 쓴 유효 사양 값}
    verdict: met(기본 값이 만족) / met_with_option(옵션 값만 만족) / not_met(값이 있고 어느 것도 만족하지 않음,
             bool의 명시적 미지원) / unknown(값 없음, 속성 키 없음, 단위 환산 불가, 숫자를 읽을 수 없음, text 불일치)
    """
    conditions = _as_conditions(conditions)
    with _connect() as conn:
        return _compare(conn, owner_type, owner_id, conditions, _attributes(conn))


def summarize(results: list[dict]) -> dict:
    counts = {v: 0 for v in VERDICTS}
    for result in results:
        counts[result["verdict"]] += 1
    return counts


# ------------------------------------------------------------------ (마) 조건으로 찾기

def search_items(owner_type: str | None = None, kind: str | None = None, conditions: list[dict] | None = None,
                 query: str | None = None, limit: int = 20) -> dict:
    """후보 찾기. query가 있으면 (가)로 찾고, conditions가 있으면 그 대상들(없으면 그 종류의 모든 대상)에 (라)를 돌려
    met 개수가 많은 순으로 돌려준다.

    반환: {items: [{owner_type, id, model, name, kind/category, vendor, status, parent_model, variants,
                    (조건이 있으면) met, met_with_option, not_met, unknown, not_met_attributes, unknown_attributes}],
           total, limit}
    결과는 후보이고 근거가 아니다.
    """
    limit = min(max(1, int(limit or 20)), 200)
    conditions = _as_conditions(conditions)
    with _connect() as conn:
        if query and str(query).strip():
            candidates = _resolve(conn, str(query), owner_type, kind)
        else:
            candidates = _items(conn, owner_type, kind)
        if not conditions:
            return {"items": [_public(i) for i in candidates[:limit]], "total": len(candidates), "limit": limit}
        attributes = _attributes(conn)
        ranked = []
        for item in candidates:
            compared = _compare(conn, item["owner_type"], item["id"], conditions, attributes)
            if compared is None:
                continue
            counts = summarize(compared["results"])
            ranked.append({
                **_public(item), **counts,
                "not_met_attributes": [r["attribute"] for r in compared["results"] if r["verdict"] == "not_met"],
                "unknown_attributes": [r["attribute"] for r in compared["results"] if r["verdict"] == "unknown"],
                "option_attributes": [r["attribute"] for r in compared["results"] if r["verdict"] == "met_with_option"],
            })
    ranked.sort(key=lambda r: (-r["met"], -r["met_with_option"], r["not_met"], r["unknown"], r["model"]))
    return {"items": ranked[:limit], "total": len(ranked), "limit": limit, "conditions": len(conditions)}


def list_attributes(category: str | None = None, kind: str | None = None) -> list[dict]:
    """속성 사전 (키, 이름, 자료형, 단위, 분류, 상속 허용). kind를 주면 그 종류 부품이 값을 가진 속성만."""
    with _connect() as conn:
        sql = "SELECT a.key, a.name, a.data_type, a.unit, a.category, a.inheritable FROM spec_attribute a"
        params: list = []
        where = []
        if category:
            where.append("a.category = ?")
            params.append(category)
        if kind:
            where.append("""a.key IN (SELECT v.attribute_key FROM spec_value v JOIN component c
                            ON v.owner_type = 'component' AND c.id = v.owner_id WHERE c.kind = ?)""")
            params.append(kind)
        if where:
            sql += " WHERE " + " AND ".join(where)
        rows = conn.execute(sql, params).fetchall()
    attributes = [{**dict(r), "inheritable": bool(r["inheritable"])} for r in rows]
    attributes.sort(key=lambda a: (_CATEGORY_ORDER.get(a["category"], 99), a["key"]))
    return attributes
