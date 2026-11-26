"""용어집 저장소 (term, term_alias, term_member, term_edit_event 테이블).

용어집은 사람이 관리하는 회사 용어다. 표준 이름 하나에 다른 표기(마케팅·입찰서 표현, 사내 약어)를 묶는다.
문서 그래프에는 쓰지 않는다. 그래프 검색이 질문을 읽을 때만 쓴다 (graph_rag/service.py).

- 표기 하나(비교용 키 기준)는 용어 하나에만 속한다. 표준 이름도 표기의 하나다 (is_name=1).
- 묶음: 구성 용어(term_member)가 있는 용어. 이름 하나가 여러 용어를 합쳐 부르는 경우다
  (예: KC 인증 자료 = 적합성 등록 + 안전확인 신고). 묶음 안에 묶음은 넣지 않는다.
- 화면 입력과 표 가져오기가 같은 쓰기 함수를 쓰고, 바꿀 때마다 term_edit_event에 이력을 남긴다.
"""
from __future__ import annotations

import json
import re
import sqlite3
import unicodedata

from graph_rag.types import normalize
from repository.repo_connect import Database

# 비교용 키가 이보다 짧은 표기는 질문 안에 우연히 들어 있을 수 있어 받지 않는다 (그래프 별칭의 MIN_NORM_LEN과 같다)
MIN_ALIAS_LEN = 2
MAX_NAME_LEN = 80
MAX_ALIASES = 50
MAX_MEMBERS = 30
MAX_DESCRIPTION_LEN = 1000
MAX_IMPORT_ROWS = 2000

TARGET_TYPES = ("", "entity_type", "spec_attribute")
# 연결 대상을 글로 쓸 때의 앞말 ("그래프:인증", "사양:메모리 용량")
TARGET_PREFIXES = {"entity_type": "그래프", "spec_attribute": "사양"}
_PREFIX_ALIASES = {"그래프": "entity_type", "graph": "entity_type", "개체": "entity_type",
                   "사양": "spec_attribute", "spec": "spec_attribute", "속성": "spec_attribute"}
# 표 가져오기의 종류 칸
KIND_LABELS = {"term": "용어", "bundle": "묶음"}
_KIND_TEXT = {"용어": "term", "term": "term", "동의어": "term", "묶음": "bundle", "bundle": "bundle", "그룹": "bundle"}

# 영숫자로만 된 표기(ram, ssd, m2)는 앞뒤가 영숫자가 아닐 때만 질문에 나온 것으로 본다 ("program" 안의 "ram"은 아니다)
_ASCII_NORM = re.compile(r"[a-z0-9]+")
_ASCII_SEP = r"[\s\-_.·/]?"
_SNAPSHOT_KEYS = ("name", "aliases", "target_type", "target_key", "description", "members")


class TermError(ValueError):
    """용어 입력이 규칙에 맞지 않음 (화면에 그대로 보여줄 메시지)"""


class TermNotFoundError(LookupError):
    """없는 용어"""


class TermConflictError(TermError):
    """다른 용어가 이미 쓰는 표기. conflicts: [{"alias", "term_id", "term_name"}]"""

    def __init__(self, message: str, conflicts: list[dict]):
        super().__init__(message)
        self.conflicts = conflicts


class TermImportError(TermError):
    """가져오기 표에 저장할 수 없는 행이 있음. rows는 미리보기와 같은 형식 (아무것도 저장하지 않았다)"""

    def __init__(self, message: str, rows: list[dict]):
        super().__init__(message)
        self.rows = rows


# ------------------------------------------------------------ 입력 정리

def _clean_name(name: str) -> str:
    name = " ".join((name or "").split())
    if not name:
        raise TermError("표준 이름을 입력하세요.")
    if len(name) > MAX_NAME_LEN:
        raise TermError(f"표준 이름은 {MAX_NAME_LEN}자 이하로 입력하세요.")
    if len(normalize(name)) < MIN_ALIAS_LEN:
        raise TermError(f"표준 이름 '{name}'이 너무 짧습니다 (기호·공백을 빼고 {MIN_ALIAS_LEN}자 이상).")
    return name


def _clean_aliases(name: str, aliases) -> list[tuple[str, str]]:
    """[(표기, 비교용 키)]. 표준 이름과 같은 표기, 겹치는 표기는 뺀다. 짧거나 긴 표기는 오류."""
    name_norm = normalize(name)
    seen = {name_norm}
    result: list[tuple[str, str]] = []
    for raw in aliases or []:
        alias = " ".join((raw or "").split())
        if not alias:
            continue
        if len(alias) > MAX_NAME_LEN:
            raise TermError(f"다른 표기는 {MAX_NAME_LEN}자 이하로 입력하세요: '{alias[:20]}…'")
        norm = normalize(alias)
        if len(norm) < MIN_ALIAS_LEN:
            raise TermError(f"다른 표기 '{alias}'가 너무 짧습니다 (기호·공백을 빼고 {MIN_ALIAS_LEN}자 이상).")
        if norm in seen:
            continue
        seen.add(norm)
        result.append((alias, norm))
    if len(result) > MAX_ALIASES:
        raise TermError(f"다른 표기는 {MAX_ALIASES}개까지 넣을 수 있습니다.")
    return result


def _clean_description(description: str) -> str:
    description = (description or "").strip()
    if len(description) > MAX_DESCRIPTION_LEN:
        raise TermError(f"설명은 {MAX_DESCRIPTION_LEN}자 이하로 입력하세요.")
    return description


def _ascii_pattern(alias_norm: str) -> re.Pattern:
    body = _ASCII_SEP.join(re.escape(ch) for ch in alias_norm)
    return re.compile(rf"(?<![a-z0-9]){body}(?![a-z0-9])")


def _appears(alias_norm: str, query_loose: str, query_norm: str) -> bool:
    """표기가 질문에 나왔는지. 영숫자 표기는 앞뒤 경계를 본다, 나머지는 비교용 키가 들어 있는지만 본다."""
    if alias_norm not in query_norm:
        return False
    if _ASCII_NORM.fullmatch(alias_norm):
        return _ascii_pattern(alias_norm).search(query_loose) is not None
    return True


class TermRepository:

    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------ 읽기

    def list_terms(self, query: str | None = None) -> list[dict]:
        """용어 목록 (표준 이름 순). query가 있으면 표기·설명에 그 말이 든 용어만."""
        with self.db.get_conn() as conn:
            targets = _target_labels(conn)
            terms = [_term_dict(row, targets) for row in conn.execute("SELECT * FROM term ORDER BY name COLLATE NOCASE, id")]
            aliases = _aliases_by_term(conn)
            members, bundles = _links(conn)
        for term in terms:
            term["aliases"] = aliases.get(term["id"], [])
            term["members"] = members.get(term["id"], [])
            term["bundles"] = bundles.get(term["id"], [])
            term["kind"] = "bundle" if term["members"] else "term"
        if query and query.strip():
            q_norm, q_lower = normalize(query), query.strip().lower()
            terms = [t for t in terms
                     if (q_norm and any(q_norm in normalize(a) for a in [t["name"], *t["aliases"]]))
                     or q_lower in t["description"].lower()]
        return terms

    def get(self, term_id: int) -> dict:
        with self.db.get_conn() as conn:
            return _snapshot(conn, term_id)

    def targets(self) -> dict:
        """연결 대상으로 고를 수 있는 것: 그래프 개체 종류와 사양 속성."""
        with self.db.get_conn() as conn:
            entity_types = [{"key": r["key"], "label": r["label"]} for r in conn.execute(
                "SELECT key, label FROM graph_entity_type WHERE active = 1 ORDER BY sort_order, key")]
            attributes = [{"key": r["key"], "label": r["name"], "category": r["category"]} for r in conn.execute(
                "SELECT key, name, category FROM spec_attribute ORDER BY sort_order, key")]
        return {"entity_type": entity_types, "spec_attribute": attributes}

    def changes(self, term_id: int | None = None, limit: int = 50) -> list[dict]:
        sql = "SELECT * FROM term_edit_event"
        params: list = []
        if term_id is not None:
            sql += " WHERE term_id = ?"
            params.append(term_id)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self.db.get_conn() as conn:
            rows = [dict(r) for r in conn.execute(sql, params)]
        for row in rows:
            for key in ("before_json", "after_json"):
                row[key[:-5]] = json.loads(row.pop(key)) if row.get(key) else None
        return rows

    # ------------------------------------------------------------ 질문 읽기

    def find_in_query(self, query: str) -> list[dict]:
        """질문에 나온 용어. 긴 표기를 먼저 잡고, 이미 잡은 표기 안에만 들어 있는 짧은 표기는 쓰지 않는다.

        예: "KC 인증 서류"와 "KC 인증"이 둘 다 등록돼 있으면 "KC 인증 서류 보내줘"는 앞의 것만 찾는다.
        반환: [{"id", "name", "kind", "matched"(질문에 나온 표기), "aliases"(표준 이름 포함 전부), "alias_norms",
                "target_type", "target_key", "target_label", "target_text", "description",
                "members"(묶음이면 구성 용어. 각 항목도 aliases·alias_norms·target·description을 가진다)}] — 질문에 나온 순서
        """
        query_norm = normalize(query)
        if len(query_norm) < MIN_ALIAS_LEN:
            return []
        query_loose = unicodedata.normalize("NFKC", query or "").lower()
        with self.db.get_conn() as conn:
            rows = conn.execute(
                """SELECT a.term_id, a.alias, a.alias_norm FROM term_alias a
                   WHERE length(a.alias_norm) >= ? AND instr(?, a.alias_norm) > 0""",
                (MIN_ALIAS_LEN, query_norm),
            ).fetchall()
            candidates = sorted(
                (r for r in rows if _appears(r["alias_norm"], query_loose, query_norm)),
                key=lambda r: (-len(r["alias_norm"]), r["term_id"]),
            )
            rest = query_norm
            found: dict[int, sqlite3.Row] = {}
            for row in candidates:
                if row["term_id"] in found or row["alias_norm"] not in rest:
                    continue
                found[row["term_id"]] = row
                rest = rest.replace(row["alias_norm"], "\x00")
            if not found:
                return []
            member_rows = conn.execute(
                f"""SELECT bundle_id, member_id FROM term_member WHERE bundle_id IN ({",".join("?" * len(found))})
                    ORDER BY bundle_id, sort_order, member_id""",
                list(found),
            ).fetchall()
            details = _details(conn, [*found, *(r["member_id"] for r in member_rows)])
        result = []
        for term_id, row in found.items():
            term = dict(details[term_id])
            term["matched"] = row["alias"]
            term["members"] = [dict(details[r["member_id"]]) for r in member_rows if r["bundle_id"] == term_id]
            term["kind"] = "bundle" if term["members"] else "term"
            result.append(term)
        result.sort(key=lambda t: query_norm.find(normalize(t["matched"])))
        return result

    def forms_of(self, text: str) -> dict | None:
        """글 전체가 어떤 용어의 표기 하나와 같으면 그 용어와 모든 표기. 아니면 None.

        사양 값 비교(agent/spec_service.py)가 조건 "스피커"를 값 "Built in two speakers"와 맞출 때 쓴다.
        글 일부만 용어인 경우("스피커 2개")는 None이다 (나머지 조건을 건너뛰지 않게).
        반환: {"id", "name", "kind", "target_type", "target_key", "aliases", "alias_norms"}
        """
        norm = normalize(text)
        if len(norm) < MIN_ALIAS_LEN:
            return None
        with self.db.get_conn() as conn:
            row = conn.execute("SELECT term_id FROM term_alias WHERE alias_norm = ?", (norm,)).fetchone()
            if row is None:
                return None
            term = dict(_details(conn, [row["term_id"]])[row["term_id"]])
            is_bundle = conn.execute("SELECT 1 FROM term_member WHERE bundle_id = ? LIMIT 1", (row["term_id"],)).fetchone()
        term["kind"] = "bundle" if is_bundle else "term"
        return term

    # ------------------------------------------------------------ 화면 입력

    def create(self, name: str, aliases=(), target_type: str = "", target_key: str = "", description: str = "",
               members=None, source: str = "screen", created_by: str = "") -> dict:
        """members: 구성 용어 id 목록. 있으면 묶음이다."""
        with self.db.transaction() as conn:
            term_id = _insert(conn, name, aliases, target_type, target_key, description, source, created_by, members)
            return _snapshot(conn, term_id)

    def update(self, term_id: int, *, name: str | None = None, aliases=None, target_type: str | None = None,
               target_key: str | None = None, description: str | None = None, members=None,
               source: str = "screen", created_by: str = "") -> dict:
        """준 항목만 바꾼다. aliases·members를 주면 그 목록으로 통째로 바꾼다 (members=[]면 묶음을 푼다)."""
        with self.db.transaction() as conn:
            _update(conn, term_id, name=name, aliases=aliases, target_type=target_type, target_key=target_key,
                    description=description, members=members, source=source, created_by=created_by)
            return _snapshot(conn, term_id)

    def delete(self, term_id: int, created_by: str = "") -> None:
        """묶음의 구성 용어는 지우지 못한다 (묶음이 말없이 줄지 않게). 묶음을 지우면 구성 용어는 남는다."""
        with self.db.transaction() as conn:
            before = _snapshot(conn, term_id)
            if before["bundles"]:
                names = ", ".join(b["name"] for b in before["bundles"])
                raise TermError(f"묶음 '{names}'의 구성 용어라 지울 수 없습니다. 묶음에서 먼저 빼세요.")
            conn.execute("DELETE FROM term_member WHERE bundle_id = ?", (term_id,))
            conn.execute("DELETE FROM term_alias WHERE term_id = ?", (term_id,))
            conn.execute("DELETE FROM term WHERE id = ?", (term_id,))
            _event(conn, term_id, "delete", "screen", before, None, created_by)

    # ------------------------------------------------------------ 표 가져오기

    def plan_import(self, rows: list[dict]) -> dict:
        """가져올 행을 기존 용어와 대조한다. 저장하지 않는다.

        rows: [{"name", "aliases": [..], "target"(글), "description", "kind"("용어"/"묶음"/""), "members": [이름..],
                "skip"?, "line"?}]
        행마다 status를 단다:
        - new: 새 용어 / update: 기존 용어에 표기·구성 용어 추가, 설명·연결 대상 바꿈 / unchanged: 바뀌는 것 없음
        - conflict: 다른 용어가 이미 쓰는 표기, 같은 표의 다른 행과 겹침
        - error: 표준 이름 없음, 모르는 연결 대상·구성 용어, 묶음 안의 묶음 등 / skip: 사용자가 건너뛰기로 고른 행
        기존 용어는 더하기만 한다. 엑셀에 없는 표기·구성 용어를 지우지 않고, 빈 칸은 기존 값을 지우지 않는다.
        구성 용어는 같은 표의 행이나 이미 등록된 용어의 이름(또는 표기)으로 쓴다.
        """
        with self.db.get_conn() as conn:
            return _plan(conn, rows)

    def apply_import(self, rows: list[dict], source: str = "import", created_by: str = "") -> dict:
        """plan_import를 다시 해서 conflict·error 행이 하나라도 있으면 아무것도 저장하지 않고 TermImportError."""
        with self.db.transaction() as conn:
            plan = _plan(conn, rows)
            blocked = [r for r in plan["rows"] if r["status"] in ("conflict", "error")]
            if blocked:
                raise TermImportError(f"저장할 수 없는 행이 {len(blocked)}개 있습니다. 고치거나 건너뛰기를 고르세요.", plan["rows"])
            ids: dict[int, int] = {}  # 행 번호 → 용어 id (구성 용어를 잇는 데 쓴다)
            created = updated = 0
            # 1) 용어 자체 (표기·연결 대상·설명). 구성 용어는 모든 행의 용어가 생긴 뒤에 잇는다
            for row in plan["rows"]:
                if row["status"] == "new":
                    ids[row["index"]] = _insert(conn, row["name"], row["aliases"], row["target_type"], row["target_key"],
                                                row["description"], source, created_by)
                    created += 1
                    continue
                if row["status"] not in ("update", "unchanged"):
                    continue
                ids[row["index"]] = row["term_id"]
                if row["status"] == "unchanged":
                    continue
                current = _snapshot(conn, row["term_id"])
                changes: dict = {}
                if row["added_aliases"]:
                    changes["aliases"] = [*current["aliases"], *row["added_aliases"]]
                if row["target_type"] and (row["target_type"], row["target_key"]) != (current["target_type"], current["target_key"]):
                    changes.update(target_type=row["target_type"], target_key=row["target_key"])
                if row["description"] and row["description"] != current["description"]:
                    changes["description"] = row["description"]
                if changes:
                    _update(conn, row["term_id"], source=source, created_by=created_by, **changes)
                updated += 1
            # 2) 구성 용어 (기존 구성에 더한다)
            for row in plan["rows"]:
                if row["status"] not in ("new", "update") or not row["member_refs"]:
                    continue
                term_id = ids[row["index"]]
                current = [m["id"] for m in _snapshot(conn, term_id)["members"]]
                wanted = [ids[ref["row"]] if ref["row"] is not None else ref["term_id"] for ref in row["member_refs"]]
                merged = list(dict.fromkeys([*current, *wanted]))
                if merged != current:
                    _update(conn, term_id, members=merged, source=source, created_by=created_by)
        return {"created": created, "updated": updated,
                "unchanged": sum(r["status"] == "unchanged" for r in plan["rows"]),
                "skipped": sum(r["status"] == "skip" for r in plan["rows"])}


# ------------------------------------------------------------ 내부 함수 (conn을 받는다)

def _term_dict(row: sqlite3.Row, targets: dict) -> dict:
    term = {k: row[k] for k in ("id", "name", "target_type", "target_key", "description", "created_at", "updated_at")}
    term["target_label"] = targets.get((row["target_type"], row["target_key"]), "") if row["target_type"] else ""
    term["target_text"] = target_text(row["target_type"], row["target_key"], targets)
    return term


def target_text(target_type: str, target_key: str, targets: dict) -> str:
    """연결 대상을 글로: "그래프:인증", "사양:메모리 용량". 이름을 모르면 key를 쓴다."""
    if not target_type:
        return ""
    return f"{TARGET_PREFIXES[target_type]}:{targets.get((target_type, target_key)) or target_key}"


def _target_labels(conn) -> dict[tuple[str, str], str]:
    labels = {("entity_type", r["key"]): r["label"] for r in conn.execute("SELECT key, label FROM graph_entity_type")}
    labels.update({("spec_attribute", r["key"]): r["name"] for r in conn.execute("SELECT key, name FROM spec_attribute")})
    return labels


def _aliases_by_term(conn) -> dict[int, list[str]]:
    result: dict[int, list[str]] = {}
    for row in conn.execute("SELECT term_id, alias FROM term_alias WHERE is_name = 0 ORDER BY rowid"):
        result.setdefault(row["term_id"], []).append(row["alias"])
    return result


def _links(conn, term_id: int | None = None) -> tuple[dict[int, list[dict]], dict[int, list[dict]]]:
    """(묶음 id → 구성 용어 [{id, name}], 용어 id → 들어 있는 묶음 [{id, name}])"""
    sql = """SELECT m.bundle_id, b.name AS bundle_name, m.member_id, t.name AS member_name
             FROM term_member m JOIN term b ON b.id = m.bundle_id JOIN term t ON t.id = m.member_id"""
    params: list = []
    if term_id is not None:
        sql += " WHERE m.bundle_id = ? OR m.member_id = ?"
        params = [term_id, term_id]
    members: dict[int, list[dict]] = {}
    bundles: dict[int, list[dict]] = {}
    for row in conn.execute(sql + " ORDER BY m.bundle_id, m.sort_order, m.member_id", params):
        members.setdefault(row["bundle_id"], []).append({"id": row["member_id"], "name": row["member_name"]})
        bundles.setdefault(row["member_id"], []).append({"id": row["bundle_id"], "name": row["bundle_name"]})
    return members, bundles


def _details(conn, term_ids) -> dict[int, dict]:
    """용어 id → 용어와 모든 표기(표준 이름 먼저)·비교용 키. 질문 읽기 결과에 쓴다."""
    term_ids = list(dict.fromkeys(term_ids))
    if not term_ids:
        return {}
    marks = ",".join("?" * len(term_ids))
    targets = _target_labels(conn)
    details = {r["id"]: {**_term_dict(r, targets), "aliases": [], "alias_norms": []}
               for r in conn.execute(f"SELECT * FROM term WHERE id IN ({marks})", term_ids)}
    for row in conn.execute(
            f"SELECT term_id, alias, alias_norm FROM term_alias WHERE term_id IN ({marks}) ORDER BY is_name DESC, rowid",
            term_ids):
        details[row["term_id"]]["aliases"].append(row["alias"])
        details[row["term_id"]]["alias_norms"].append(row["alias_norm"])
    return details


def _snapshot(conn, term_id: int) -> dict:
    row = conn.execute("SELECT * FROM term WHERE id = ?", (term_id,)).fetchone()
    if row is None:
        raise TermNotFoundError("용어를 찾을 수 없습니다.")
    term = _term_dict(row, _target_labels(conn))
    term["aliases"] = [r["alias"] for r in conn.execute(
        "SELECT alias FROM term_alias WHERE term_id = ? AND is_name = 0 ORDER BY rowid", (term_id,))]
    members, bundles = _links(conn, term_id)
    term["members"] = members.get(term_id, [])
    term["bundles"] = bundles.get(term_id, [])
    term["kind"] = "bundle" if term["members"] else "term"
    return term


def _check_target(conn, target_type: str, target_key: str) -> tuple[str, str]:
    target_type, target_key = (target_type or "").strip(), (target_key or "").strip()
    if target_type not in TARGET_TYPES:
        raise TermError("연결 대상 종류는 그래프 개체 종류(entity_type)나 사양 속성(spec_attribute)이어야 합니다.")
    if not target_type:
        return "", ""
    if not target_key:
        raise TermError("연결 대상을 고르세요.")
    table = "graph_entity_type" if target_type == "entity_type" else "spec_attribute"
    if conn.execute(f"SELECT 1 FROM {table} WHERE key = ?", (target_key,)).fetchone() is None:
        what = "그래프 개체 종류" if target_type == "entity_type" else "사양 속성"
        raise TermError(f"없는 {what}입니다: {target_key}")
    return target_type, target_key


def _check_members(conn, term_id: int | None, members) -> list[int]:
    """구성 용어 id 목록을 검사한다: 있는 용어, 자기 자신 아님, 묶음 아님. 묶음이 될 용어는 다른 묶음의 구성 용어가 아니어야 한다."""
    ids = []
    for value in members or []:
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            raise TermError("구성 용어 id가 올바르지 않습니다.") from None
    ids = list(dict.fromkeys(ids))
    if not ids:
        return []
    if len(ids) > MAX_MEMBERS:
        raise TermError(f"구성 용어는 {MAX_MEMBERS}개까지 넣을 수 있습니다.")
    if term_id is not None and term_id in ids:
        raise TermError("자기 자신을 구성 용어로 넣을 수 없습니다.")
    marks = ",".join("?" * len(ids))
    names = {r["id"]: r["name"] for r in conn.execute(f"SELECT id, name FROM term WHERE id IN ({marks})", ids)}
    missing = [i for i in ids if i not in names]
    if missing:
        raise TermError("없는 용어를 구성 용어로 골랐습니다.")
    nested = [names[r["bundle_id"]] for r in conn.execute(
        f"SELECT DISTINCT bundle_id FROM term_member WHERE bundle_id IN ({marks})", ids)]
    if nested:
        raise TermError(f"묶음은 구성 용어가 될 수 없습니다: {', '.join(nested)}")
    if term_id is not None:
        parents = [r["name"] for r in conn.execute(
            "SELECT b.name FROM term_member m JOIN term b ON b.id = m.bundle_id WHERE m.member_id = ?", (term_id,))]
        if parents:
            raise TermError(f"묶음 '{', '.join(parents)}'의 구성 용어라 묶음이 될 수 없습니다 (묶음 안에 묶음은 넣지 않습니다).")
    return ids


def resolve_target(conn, text: str) -> tuple[str, str]:
    """연결 대상 글("그래프:인증", "사양:ram_gb", "인증")을 (종류, key)로. 빈 글이면 ("", ""). 모르면 TermError."""
    text = " ".join((text or "").split())
    if not text:
        return "", ""
    wanted = None
    prefix, sep, rest = text.partition(":")
    if sep and prefix.strip().lower() in _PREFIX_ALIASES:
        wanted, text = _PREFIX_ALIASES[prefix.strip().lower()], rest.strip()
    key = normalize(text)
    found = {(t, k) for (t, k), label in _target_labels(conn).items()
             if (wanted is None or t == wanted) and key in (normalize(k), normalize(label))}
    if not found:
        raise TermError(f"연결 대상 '{text}'를 찾지 못했습니다. 그래프 개체 종류나 사양 속성 이름을 쓰세요 (예: 그래프:인증, 사양:메모리 용량).")
    if len(found) > 1:
        raise TermError(f"연결 대상 '{text}'가 여러 곳에 있습니다. 앞에 '그래프:' 또는 '사양:'을 붙이세요.")
    return found.pop()


def _owners(conn, norms: list[str]) -> dict[str, sqlite3.Row]:
    """비교용 키 → 그 표기를 가진 용어 (term_id, 표기, 표준 이름)"""
    if not norms:
        return {}
    marks = ",".join("?" * len(norms))
    rows = conn.execute(
        f"""SELECT a.alias_norm, a.alias, a.is_name, t.id AS term_id, t.name AS term_name
            FROM term_alias a JOIN term t ON t.id = a.term_id WHERE a.alias_norm IN ({marks})""",
        norms,
    ).fetchall()
    return {r["alias_norm"]: r for r in rows}


def _check_free(conn, term_id: int | None, forms: list[tuple[str, str]]) -> None:
    """다른 용어가 이미 쓰는 표기가 있으면 TermConflictError."""
    owners = _owners(conn, [norm for _, norm in forms])
    conflicts = [{"alias": alias, "term_id": owners[norm]["term_id"], "term_name": owners[norm]["term_name"]}
                 for alias, norm in forms if norm in owners and owners[norm]["term_id"] != term_id]
    if conflicts:
        first = conflicts[0]
        raise TermConflictError(f"'{first['alias']}'는 이미 '{first['term_name']}' 용어의 표기입니다.", conflicts)


def _write_aliases(conn, term_id: int, name: str, forms: list[tuple[str, str]]) -> None:
    conn.execute("DELETE FROM term_alias WHERE term_id = ?", (term_id,))
    conn.execute("INSERT INTO term_alias (term_id, alias, alias_norm, is_name) VALUES (?, ?, ?, 1)", (term_id, name, normalize(name)))
    conn.executemany("INSERT INTO term_alias (term_id, alias, alias_norm, is_name) VALUES (?, ?, ?, 0)",
                     [(term_id, alias, norm) for alias, norm in forms])


def _write_members(conn, term_id: int, member_ids: list[int]) -> None:
    conn.execute("DELETE FROM term_member WHERE bundle_id = ?", (term_id,))
    conn.executemany("INSERT INTO term_member (bundle_id, member_id, sort_order) VALUES (?, ?, ?)",
                     [(term_id, member_id, order) for order, member_id in enumerate(member_ids)])


def _insert(conn, name, aliases, target_type, target_key, description, source, created_by, members=None) -> int:
    name = _clean_name(name)
    forms = _clean_aliases(name, aliases)
    target_type, target_key = _check_target(conn, target_type, target_key)
    description = _clean_description(description)
    member_ids = _check_members(conn, None, members)
    _check_free(conn, None, [(name, normalize(name)), *forms])
    term_id = conn.execute(
        "INSERT INTO term (name, target_type, target_key, description) VALUES (?, ?, ?, ?)",
        (name, target_type, target_key, description),
    ).lastrowid
    _write_aliases(conn, term_id, name, forms)
    _write_members(conn, term_id, member_ids)
    _event(conn, term_id, "create", source, None, _snapshot(conn, term_id), created_by)
    return term_id


def _update(conn, term_id, *, name=None, aliases=None, target_type=None, target_key=None, description=None,
            members=None, source="screen", created_by="") -> None:
    before = _snapshot(conn, term_id)
    name = _clean_name(name) if name is not None else before["name"]
    forms = _clean_aliases(name, aliases if aliases is not None else before["aliases"])
    if target_type is not None or target_key is not None:
        target_type, target_key = _check_target(
            conn, before["target_type"] if target_type is None else target_type,
            before["target_key"] if target_key is None else target_key)
    else:
        target_type, target_key = before["target_type"], before["target_key"]
    description = _clean_description(description) if description is not None else before["description"]
    member_ids = (_check_members(conn, term_id, members) if members is not None
                  else [m["id"] for m in before["members"]])
    _check_free(conn, term_id, [(name, normalize(name)), *forms])
    conn.execute(
        "UPDATE term SET name = ?, target_type = ?, target_key = ?, description = ?, updated_at = current_timestamp WHERE id = ?",
        (name, target_type, target_key, description, term_id),
    )
    _write_aliases(conn, term_id, name, forms)
    _write_members(conn, term_id, member_ids)
    after = _snapshot(conn, term_id)
    if _packed(before) != _packed(after):
        _event(conn, term_id, "update", source, before, after, created_by)


def _packed(value: dict | None) -> str | None:
    if value is None:
        return None
    data = {k: value[k] for k in _SNAPSHOT_KEYS}
    data["members"] = [m["name"] for m in value["members"]]
    return json.dumps(data, ensure_ascii=False)


def _event(conn, term_id, action, source, before, after, created_by) -> None:
    conn.execute(
        "INSERT INTO term_edit_event (term_id, action, source, before_json, after_json, created_by) VALUES (?, ?, ?, ?, ?, ?)",
        (term_id, action, (source or "screen")[:200], _packed(before), _packed(after), created_by or ""),
    )


def _plan(conn, rows: list[dict]) -> dict:
    if len(rows) > MAX_IMPORT_ROWS:
        raise TermError(f"한 번에 {MAX_IMPORT_ROWS}행까지 가져올 수 있습니다.")
    targets = _target_labels(conn)
    claimed: dict[str, int] = {}  # 비교용 키 → 그 표기를 처음 쓴 행 번호 (같은 표 안의 겹침, 구성 용어 찾기)
    planned = []
    for index, raw in enumerate(rows):
        row = {
            "index": index, "line": raw.get("line"), "skip": bool(raw.get("skip")),
            "name": " ".join((raw.get("name") or "").split()),
            "aliases": [" ".join(a.split()) for a in raw.get("aliases") or [] if a and a.strip()],
            "target": (raw.get("target") or "").strip(), "description": (raw.get("description") or "").strip(),
            "kind": (raw.get("kind") or "").strip(),
            "members": [" ".join(m.split()) for m in raw.get("members") or [] if m and m.strip()],
            "status": "new", "term_id": None, "term_name": None, "added_aliases": [], "changes": [], "messages": [],
            "target_type": "", "target_key": "", "member_refs": [],
        }
        planned.append(row)
        if row["skip"]:
            row["status"] = "skip"
            continue
        try:
            name = _clean_name(row["name"])
            forms = _clean_aliases(name, row["aliases"])
            row["target_type"], row["target_key"] = resolve_target(conn, row["target"])
            _clean_description(row["description"])
            kind = _KIND_TEXT.get(row["kind"].lower()) if row["kind"] else ("bundle" if row["members"] else "term")
            if kind is None:
                raise TermError(f"종류 '{row['kind']}'를 모릅니다. '용어' 또는 '묶음'으로 쓰세요.")
            if kind == "bundle" and not row["members"]:
                raise TermError("종류가 묶음이면 구성 용어를 쓰세요.")
            if kind == "term" and row["members"]:
                raise TermError("종류가 용어인데 구성 용어가 있습니다. 종류를 '묶음'으로 쓰세요.")
        except TermError as exc:
            row["status"], row["messages"] = "error", [str(exc)]
            continue

        name_norm = normalize(name)
        owners = _owners(conn, [name_norm, *(n for _, n in forms)])
        owner = owners.get(name_norm)
        if owner is not None and not owner["is_name"]:
            row["status"] = "conflict"
            row["messages"].append(f"표준 이름 '{name}'은 이미 '{owner['term_name']}' 용어의 다른 표기입니다.")
        elif owner is not None:
            row["status"], row["term_id"], row["term_name"] = "update", owner["term_id"], owner["term_name"]

        for alias, norm in forms:
            other = owners.get(norm)
            if other is not None and other["term_id"] != row["term_id"]:
                row["status"] = "conflict"
                row["messages"].append(f"'{alias}'는 이미 '{other['term_name']}' 용어의 표기입니다.")
            elif other is None:
                row["added_aliases"].append(alias)
        for norm in [name_norm, *(n for _, n in forms)]:
            if norm in claimed and claimed[norm] != index:
                row["status"] = "conflict"
                first = planned[claimed[norm]]
                row["messages"].append(f"같은 표의 {first['line'] or first['index'] + 1}행과 표기가 겹칩니다.")
                break
        for norm in [name_norm, *(n for _, n in forms)]:
            claimed.setdefault(norm, index)
        if row["status"] != "update":
            continue

        current = _snapshot(conn, row["term_id"])
        if row["added_aliases"]:
            row["changes"].append(f"표기 추가: {', '.join(row['added_aliases'])}")
        if row["target_type"] and (row["target_type"], row["target_key"]) != (current["target_type"], current["target_key"]):
            before = target_text(current["target_type"], current["target_key"], targets) or "없음"
            row["changes"].append(f"연결 대상: {before} → {target_text(row['target_type'], row['target_key'], targets)}")
        if row["description"] and row["description"] != current["description"]:
            row["changes"].append("설명 바뀜")

    _plan_members(conn, planned, claimed)

    for row in planned:
        if row["status"] == "update" and not row["changes"]:
            row["status"] = "unchanged"
    counts: dict[str, int] = {}
    for row in planned:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    return {"rows": planned, "counts": counts}


def _plan_members(conn, planned: list[dict], claimed: dict[str, int]) -> None:
    """구성 용어 이름을 같은 표의 행이나 등록된 용어로 잇는다 (member_refs: [{"row": 행 번호|None, "term_id": id|None, "name"}]).

    묶음 안에 묶음은 넣지 않는다: 구성 용어가 묶음이거나, 묶음이 될 행이 다른 묶음의 구성 용어면 오류.
    """
    db_owners = _owners(conn, list({normalize(m) for row in planned for m in row["members"]}))
    db_members, db_bundles = _links(conn)
    bundle_rows = {row["index"] for row in planned if row["members"] and row["status"] not in ("skip", "error")}
    member_of: dict[int, str] = {}  # 행 번호 → 그 행을 구성 용어로 쓰는 묶음 행 이름 (같은 표 안)
    for row in planned:
        if row["status"] in ("skip", "error") or not row["members"]:
            continue
        refs, problems = [], []
        for member in row["members"]:
            norm = normalize(member)
            if norm in claimed and planned[claimed[norm]]["status"] not in ("skip",):
                target = planned[claimed[norm]]
                if target["index"] == row["index"]:
                    problems.append("자기 자신을 구성 용어로 넣을 수 없습니다.")
                elif target["index"] in bundle_rows or (target["term_id"] and db_members.get(target["term_id"])):
                    problems.append(f"'{member}'는 묶음이라 구성 용어가 될 수 없습니다.")
                elif target["status"] in ("conflict", "error"):
                    problems.append(f"구성 용어 '{member}'의 행({target['line'] or target['index'] + 1}행)을 저장할 수 없습니다.")
                else:
                    refs.append({"row": target["index"], "term_id": target["term_id"], "name": target["name"]})
                    member_of[target["index"]] = row["name"]
            elif norm in db_owners:
                owner = db_owners[norm]
                if row["term_id"] == owner["term_id"]:
                    problems.append("자기 자신을 구성 용어로 넣을 수 없습니다.")
                elif db_members.get(owner["term_id"]):
                    problems.append(f"'{member}'는 묶음이라 구성 용어가 될 수 없습니다.")
                else:
                    refs.append({"row": None, "term_id": owner["term_id"], "name": owner["term_name"]})
            else:
                problems.append(f"구성 용어 '{member}'를 찾지 못했습니다 (같은 표나 용어집에 있어야 합니다).")
        if row["term_id"] and db_bundles.get(row["term_id"]):
            parents = ", ".join(b["name"] for b in db_bundles[row["term_id"]])
            problems.append(f"묶음 '{parents}'의 구성 용어라 묶음이 될 수 없습니다 (묶음 안에 묶음은 넣지 않습니다).")
        if problems:
            row["status"] = "error"
            row["messages"].extend(problems)
            continue
        row["member_refs"] = refs
        if row["status"] == "update":
            current = {m["id"] for m in db_members.get(row["term_id"], [])}
            added = [ref["name"] for ref in refs if ref["term_id"] is None or ref["term_id"] not in current]
            if added:
                row["changes"].append(f"구성 추가: {', '.join(added)}")
    for index, bundle_name in member_of.items():
        row = planned[index]
        if row["index"] in bundle_rows and row["status"] not in ("error", "skip"):
            row["status"] = "error"
            row["messages"].append(f"묶음 '{bundle_name}'의 구성 용어라 묶음이 될 수 없습니다 (묶음 안에 묶음은 넣지 않습니다).")
