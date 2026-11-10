"""제품·부품 사양 저장소.

- spec_attribute: 속성 사전. 사양 값은 반드시 이 키로 저장한다.
- product / component: 제품과 부품. 제품은 product_component로 부품과 이어진다.
  제품은 parent_id로 상위 모델에 매달린 하위 모델(파생 모델)을 가질 수 있다.
- spec_value: 제품 또는 부품(owner_type)의 사양 값 한 건. 같은 속성에 값이 여러 개(옵션)면 행이 여러 개다.
  number 속성은 value_text에서 숫자를 뽑아 value_num에 같이 둔다. 비교 코드는 value_num을 본다.
"""
from __future__ import annotations

import re
import sqlite3
import uuid
from datetime import datetime

from entity.spec import (
    ATTRIBUTE_CATEGORIES,
    COMPONENT_KINDS,
    DATA_TYPES,
    DEFAULT_ATTRIBUTES,
    PRODUCT_CATEGORIES,
    PRODUCT_STATUSES,
)
from repository.repo_connect import Database


class SpecNotFoundError(Exception):
    """대상이 없다."""


class SpecConflictError(Exception):
    """중복이거나, 다른 데이터가 참조하고 있어 지울 수 없다."""


_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,49}$")
_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")
_TRUE_WORDS = frozenset({"1", "true", "yes", "y", "o", "예", "있음", "지원", "가능", "포함"})
_FALSE_WORDS = frozenset({"0", "false", "no", "n", "x", "아니오", "아니요", "없음", "미지원", "불가", "제외"})
_CATEGORY_ORDER = {key: index for index, key in enumerate(ATTRIBUTE_CATEGORIES)}

OWNER_TYPES = ("product", "component")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _clean(text: str | None, *, field: str, max_length: int, required: bool = False) -> str:
    text = " ".join((text or "").split())
    if required and not text:
        raise ValueError(f"{field}을(를) 입력해 주세요.")
    if len(text) > max_length:
        raise ValueError(f"{field}은(는) {max_length}자 이하로 입력해 주세요.")
    return text


def _choice(value: str | None, choices: dict[str, str], *, field: str, default: str) -> str:
    value = (value or default).strip()
    if value not in choices:
        raise ValueError(f"{field} 값이 올바르지 않습니다: {value} (가능: {', '.join(choices)})")
    return value


def parse_value(data_type: str, value_text: str) -> float | None:
    """속성 자료형에 맞춰 value_text에서 비교용 숫자를 뽑는다. text면 None."""
    text = value_text.strip()
    if not text:
        raise ValueError("값을 입력해 주세요.")
    if data_type == "number":
        match = _NUM_RE.search(text.replace(",", ""))
        if match is None:
            raise ValueError(f"숫자를 읽을 수 없습니다: {value_text}")
        return float(match.group())
    if data_type == "bool":
        lowered = text.lower()
        if lowered in _TRUE_WORDS:
            return 1.0
        if lowered in _FALSE_WORDS:
            return 0.0
        raise ValueError(f"예/아니오 값을 읽을 수 없습니다: {value_text} (예, 아니오, 있음, 없음, O, X)")
    return None


def _attribute_values(key, name, category, data_type, unit, description, sort_order) -> tuple:
    """속성 입력을 검증해 INSERT 순서의 튜플로 돌려준다."""
    key = (key or "").strip().lower()
    if not _KEY_RE.match(key):
        raise ValueError("속성 키는 영문 소문자로 시작하고 영문 소문자·숫자·_ 만 써서 2~50자여야 합니다. 예: ram_max_gb")
    return (
        key,
        _clean(name, field="속성 이름", max_length=80, required=True),
        _choice(category, ATTRIBUTE_CATEGORIES, field="분류", default="other"),
        _choice(data_type, DATA_TYPES, field="자료형", default="text"),
        _clean(unit, field="단위", max_length=20),
        _clean(description, field="설명", max_length=300),
        int(sort_order or 0),
    )


def _insert_attribute(conn: sqlite3.Connection, values: tuple) -> None:
    try:
        conn.execute(
            "INSERT INTO spec_attribute (key, name, category, data_type, unit, description, sort_order) VALUES (?,?,?,?,?,?,?)",
            values,
        )
    except sqlite3.IntegrityError as exc:
        raise SpecConflictError(f"이미 있는 속성 키입니다: {values[0]}") from exc


class SpecImportError(Exception):
    """가져오기 입력에 고칠 곳이 있다. errors는 [{"row", "column", "message"}] 목록이다. 아무것도 저장하지 않는다."""

    def __init__(self, errors: list[dict]):
        super().__init__(f"가져오기 입력 {len(errors)}곳을 고쳐야 합니다.")
        self.errors = errors


def _row(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    data = dict(row)
    if "is_option" in data:
        data["is_option"] = bool(data["is_option"])
    return data


_SPEC_SELECT = """
    SELECT v.id, v.owner_type, v.owner_id, v.attribute_key, a.name AS attribute_name, a.category,
           a.data_type, a.unit, v.value_text, v.value_num, v.is_option, v.note,
           v.source_file_id, v.source_page, v.source_note, v.created_at, v.updated_at
    FROM spec_value v
    JOIN spec_attribute a ON a.key = v.attribute_key
"""


class SpecRepository:

    def __init__(self, db: Database):
        self.db = db

    # ---------- 속성 사전 ----------

    def list_attributes(self) -> list[dict]:
        with self.db.get_conn() as conn:
            rows = conn.execute(
                """
                SELECT a.*, (SELECT COUNT(*) FROM spec_value v WHERE v.attribute_key = a.key) AS usage_count
                FROM spec_attribute a
                """
            ).fetchall()
        attributes = [dict(r) for r in rows]
        attributes.sort(key=lambda a: (_CATEGORY_ORDER.get(a["category"], 99), a["sort_order"], a["name"]))
        return attributes

    def get_attribute(self, key: str) -> dict | None:
        with self.db.get_conn() as conn:
            return _row(conn.execute("SELECT * FROM spec_attribute WHERE key = ?", (key,)).fetchone())

    def create_attribute(
        self, key: str, name: str, category: str = "other", data_type: str = "text",
        unit: str = "", description: str = "", sort_order: int = 0,
    ) -> dict:
        values = _attribute_values(key, name, category, data_type, unit, description, sort_order)
        with self.db.transaction() as conn:
            _insert_attribute(conn, values)
        return {**self.get_attribute(values[0]), "usage_count": 0}

    def update_attribute(self, key: str, **fields) -> dict:
        """키는 바꾸지 못한다 (저장된 사양 값이 키를 참조한다). 자료형을 바꾸면 기존 값의 value_num을 다시 계산한다."""
        current = self.get_attribute(key)
        if current is None:
            raise SpecNotFoundError(f"속성을 찾을 수 없습니다: {key}")
        merged = {**current, **{k: v for k, v in fields.items() if v is not None}}
        name = _clean(merged["name"], field="속성 이름", max_length=80, required=True)
        category = _choice(merged["category"], ATTRIBUTE_CATEGORIES, field="분류", default="other")
        data_type = _choice(merged["data_type"], DATA_TYPES, field="자료형", default="text")
        unit = _clean(merged["unit"], field="단위", max_length=20)
        description = _clean(merged["description"], field="설명", max_length=300)
        sort_order = int(merged["sort_order"] or 0)

        with self.db.transaction() as conn:
            if data_type != current["data_type"]:
                rows = conn.execute("SELECT id, value_text FROM spec_value WHERE attribute_key = ?", (key,)).fetchall()
                for row in rows:
                    try:
                        value_num = parse_value(data_type, row["value_text"])
                    except ValueError as exc:
                        raise ValueError(f"자료형을 바꾸려면 기존 값이 맞아야 합니다. {exc}") from exc
                    conn.execute("UPDATE spec_value SET value_num = ? WHERE id = ?", (value_num, row["id"]))
            conn.execute(
                """
                UPDATE spec_attribute
                SET name = ?, category = ?, data_type = ?, unit = ?, description = ?, sort_order = ?, updated_at = ?
                WHERE key = ?
                """,
                (name, category, data_type, unit, description, sort_order, _now(), key),
            )
            usage = conn.execute("SELECT COUNT(*) FROM spec_value WHERE attribute_key = ?", (key,)).fetchone()[0]
        return {**self.get_attribute(key), "usage_count": usage}

    def delete_attribute(self, key: str) -> None:
        with self.db.transaction() as conn:
            usage = conn.execute("SELECT COUNT(*) FROM spec_value WHERE attribute_key = ?", (key,)).fetchone()[0]
            if usage:
                raise SpecConflictError(f"사양 값 {usage}건이 이 속성을 쓰고 있어 지울 수 없습니다. 값을 먼저 지우세요.")
            cursor = conn.execute("DELETE FROM spec_attribute WHERE key = ?", (key,))
            if cursor.rowcount == 0:
                raise SpecNotFoundError(f"속성을 찾을 수 없습니다: {key}")

    def add_default_attributes(self) -> int:
        """entity/spec.py의 기본 속성 중 없는 것만 넣는다. 넣은 개수를 돌려준다."""
        inserted = 0
        with self.db.transaction() as conn:
            for index, attribute in enumerate(DEFAULT_ATTRIBUTES):
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO spec_attribute (key, name, category, data_type, unit, description, sort_order)
                    VALUES (?,?,?,?,?,?,?)
                    """,
                    (attribute.key, attribute.name, attribute.category, attribute.data_type,
                     attribute.unit, attribute.description, index),
                )
                inserted += cursor.rowcount
        return inserted

    # ---------- 제품 ----------

    def list_products(self) -> list[dict]:
        with self.db.get_conn() as conn:
            rows = conn.execute(
                """
                SELECT p.*,
                       (SELECT COUNT(*) FROM spec_value v WHERE v.owner_type = 'product' AND v.owner_id = p.id) AS spec_count,
                       (SELECT COUNT(*) FROM product_component pc WHERE pc.product_id = p.id) AS component_count,
                       (SELECT COUNT(*) FROM product c WHERE c.parent_id = p.id) AS child_count
                FROM product p
                ORDER BY p.model
                """
            ).fetchall()
        return [dict(r) for r in rows]

    def get_product(self, product_id: str) -> dict | None:
        """제품 + 사양 값 목록 + 연결된 부품 목록."""
        with self.db.get_conn() as conn:
            product = _row(conn.execute("SELECT * FROM product WHERE id = ?", (product_id,)).fetchone())
            if product is None:
                return None
            product["specs"] = self._specs(conn, "product", product_id)
            product["components"] = [
                _row(r) for r in conn.execute(
                    """
                    SELECT c.id, c.kind, c.model, c.vendor, c.note, pc.is_option, pc.note AS link_note
                    FROM product_component pc
                    JOIN component c ON c.id = pc.component_id
                    WHERE pc.product_id = ?
                    ORDER BY c.kind, pc.is_option, c.model
                    """,
                    (product_id,),
                ).fetchall()
            ]
            product["spec_count"] = len(product["specs"])
            product["component_count"] = len(product["components"])
            # 상위 모델 경로 (최상위 → 바로 위). 화면의 위치 표시에 쓴다
            ancestors, parent_id = [], product["parent_id"]
            while parent_id and len(ancestors) < 20:  # 순환이 생겨도 멈춘다
                row = conn.execute("SELECT id, model, parent_id FROM product WHERE id = ?", (parent_id,)).fetchone()
                if row is None:
                    break
                ancestors.insert(0, {"id": row["id"], "model": row["model"]})
                parent_id = row["parent_id"]
            product["ancestors"] = ancestors
            product["children"] = [
                dict(r) for r in conn.execute(
                    "SELECT id, model, name, status FROM product WHERE parent_id = ? ORDER BY model", (product_id,),
                ).fetchall()
            ]
        return product

    def create_product(
        self, model: str, name: str = "", category: str = "notebook", status: str = "active", note: str = "",
        parent_id: str | None = None,
    ) -> dict:
        values = (
            str(uuid.uuid4()),
            _clean(model, field="모델명", max_length=50, required=True),
            _clean(name, field="제품 이름", max_length=100),
            _choice(category, PRODUCT_CATEGORIES, field="제품 종류", default="notebook"),
            _choice(status, PRODUCT_STATUSES, field="상태", default="active"),
            _clean(note, field="비고", max_length=500),
            parent_id or None,
        )
        with self.db.transaction() as conn:
            _check_parent(conn, None, values[6])
            try:
                conn.execute(
                    "INSERT INTO product (id, model, name, category, status, note, parent_id) VALUES (?,?,?,?,?,?,?)", values,
                )
            except sqlite3.IntegrityError as exc:
                raise SpecConflictError(f"이미 등록된 모델명입니다: {values[1]}") from exc
        return self.get_product(values[0])

    def update_product(self, product_id: str, **fields) -> dict:
        """넘긴 값만 바꾼다. parent_id는 넘기면 None·빈 값도 반영해 최상위 모델로 올린다."""
        current = self.get_product(product_id)
        if current is None:
            raise SpecNotFoundError("제품을 찾을 수 없습니다.")
        merged = {**current, **{k: v for k, v in fields.items() if v is not None}}
        parent_id = (fields["parent_id"] or None) if "parent_id" in fields else current["parent_id"]
        values = (
            _clean(merged["model"], field="모델명", max_length=50, required=True),
            _clean(merged["name"], field="제품 이름", max_length=100),
            _choice(merged["category"], PRODUCT_CATEGORIES, field="제품 종류", default="notebook"),
            _choice(merged["status"], PRODUCT_STATUSES, field="상태", default="active"),
            _clean(merged["note"], field="비고", max_length=500),
            parent_id,
            _now(),
            product_id,
        )
        with self.db.transaction() as conn:
            _check_parent(conn, product_id, parent_id)
            try:
                conn.execute(
                    "UPDATE product SET model = ?, name = ?, category = ?, status = ?, note = ?, parent_id = ?, updated_at = ?"
                    " WHERE id = ?",
                    values,
                )
            except sqlite3.IntegrityError as exc:
                raise SpecConflictError(f"이미 등록된 모델명입니다: {values[0]}") from exc
        return self.get_product(product_id)

    def delete_product(self, product_id: str) -> None:
        with self.db.transaction() as conn:
            children = conn.execute("SELECT COUNT(*) FROM product WHERE parent_id = ?", (product_id,)).fetchone()[0]
            if children:
                raise SpecConflictError(f"하위 모델 {children}개가 있어 지울 수 없습니다. 하위 모델을 먼저 지우거나 옮기세요.")
            conn.execute("DELETE FROM spec_value WHERE owner_type = 'product' AND owner_id = ?", (product_id,))
            cursor = conn.execute("DELETE FROM product WHERE id = ?", (product_id,))  # product_component는 cascade
            if cursor.rowcount == 0:
                raise SpecNotFoundError("제품을 찾을 수 없습니다.")

    # ---------- 부품 ----------

    def list_components(self, kind: str | None = None) -> list[dict]:
        with self.db.get_conn() as conn:
            rows = conn.execute(
                f"""
                SELECT c.*,
                       (SELECT COUNT(*) FROM spec_value v WHERE v.owner_type = 'component' AND v.owner_id = c.id) AS spec_count,
                       (SELECT COUNT(*) FROM product_component pc WHERE pc.component_id = c.id) AS product_count
                FROM component c
                {"WHERE c.kind = ?" if kind else ""}
                ORDER BY c.kind, c.model
                """,
                (kind,) if kind else (),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_component(self, component_id: str) -> dict | None:
        with self.db.get_conn() as conn:
            component = _row(conn.execute("SELECT * FROM component WHERE id = ?", (component_id,)).fetchone())
            if component is None:
                return None
            component["specs"] = self._specs(conn, "component", component_id)
            component["products"] = [
                _row(r) for r in conn.execute(
                    """
                    SELECT p.id, p.model, p.name, pc.is_option
                    FROM product_component pc JOIN product p ON p.id = pc.product_id
                    WHERE pc.component_id = ? ORDER BY p.model
                    """,
                    (component_id,),
                ).fetchall()
            ]
            component["spec_count"] = len(component["specs"])
            component["product_count"] = len(component["products"])
        return component

    def create_component(self, kind: str, model: str, vendor: str = "", note: str = "") -> dict:
        values = (
            str(uuid.uuid4()),
            _choice(kind, COMPONENT_KINDS, field="부품 종류", default="other"),
            _clean(model, field="부품 모델명", max_length=100, required=True),
            _clean(vendor, field="제조사", max_length=50),
            _clean(note, field="비고", max_length=500),
        )
        with self.db.transaction() as conn:
            try:
                conn.execute("INSERT INTO component (id, kind, model, vendor, note) VALUES (?,?,?,?,?)", values)
            except sqlite3.IntegrityError as exc:
                raise SpecConflictError(f"같은 종류에 이미 있는 부품입니다: {values[2]}") from exc
        return self.get_component(values[0])

    def update_component(self, component_id: str, **fields) -> dict:
        current = self.get_component(component_id)
        if current is None:
            raise SpecNotFoundError("부품을 찾을 수 없습니다.")
        merged = {**current, **{k: v for k, v in fields.items() if v is not None}}
        values = (
            _choice(merged["kind"], COMPONENT_KINDS, field="부품 종류", default="other"),
            _clean(merged["model"], field="부품 모델명", max_length=100, required=True),
            _clean(merged["vendor"], field="제조사", max_length=50),
            _clean(merged["note"], field="비고", max_length=500),
            _now(),
            component_id,
        )
        with self.db.transaction() as conn:
            try:
                conn.execute(
                    "UPDATE component SET kind = ?, model = ?, vendor = ?, note = ?, updated_at = ? WHERE id = ?", values,
                )
            except sqlite3.IntegrityError as exc:
                raise SpecConflictError(f"같은 종류에 이미 있는 부품입니다: {values[1]}") from exc
        return self.get_component(component_id)

    def delete_component(self, component_id: str) -> None:
        with self.db.transaction() as conn:
            used = conn.execute("SELECT COUNT(*) FROM product_component WHERE component_id = ?", (component_id,)).fetchone()[0]
            if used:
                raise SpecConflictError(f"제품 {used}개가 이 부품을 쓰고 있어 지울 수 없습니다. 제품에서 먼저 빼세요.")
            conn.execute("DELETE FROM spec_value WHERE owner_type = 'component' AND owner_id = ?", (component_id,))
            cursor = conn.execute("DELETE FROM component WHERE id = ?", (component_id,))
            if cursor.rowcount == 0:
                raise SpecNotFoundError("부품을 찾을 수 없습니다.")

    # ---------- 제품-부품 연결 ----------

    def link_component(self, product_id: str, component_id: str, is_option: bool = False, note: str = "") -> dict:
        """제품에 부품을 넣는다. 이미 있으면 옵션 여부와 비고만 바꾼다."""
        note = _clean(note, field="비고", max_length=300)
        with self.db.transaction() as conn:
            if conn.execute("SELECT 1 FROM product WHERE id = ?", (product_id,)).fetchone() is None:
                raise SpecNotFoundError("제품을 찾을 수 없습니다.")
            if conn.execute("SELECT 1 FROM component WHERE id = ?", (component_id,)).fetchone() is None:
                raise SpecNotFoundError("부품을 찾을 수 없습니다.")
            conn.execute(
                """
                INSERT INTO product_component (product_id, component_id, is_option, note) VALUES (?,?,?,?)
                ON CONFLICT(product_id, component_id) DO UPDATE SET is_option = excluded.is_option, note = excluded.note
                """,
                (product_id, component_id, int(is_option), note),
            )
        return self.get_product(product_id)

    def unlink_component(self, product_id: str, component_id: str) -> dict:
        with self.db.transaction() as conn:
            cursor = conn.execute(
                "DELETE FROM product_component WHERE product_id = ? AND component_id = ?", (product_id, component_id),
            )
            if cursor.rowcount == 0:
                raise SpecNotFoundError("제품에 연결된 부품이 아닙니다.")
        product = self.get_product(product_id)
        if product is None:
            raise SpecNotFoundError("제품을 찾을 수 없습니다.")
        return product

    # ---------- 사양 값 ----------

    def _specs(self, conn: sqlite3.Connection, owner_type: str, owner_id: str) -> list[dict]:
        rows = conn.execute(
            _SPEC_SELECT + " WHERE v.owner_type = ? AND v.owner_id = ? ORDER BY a.sort_order, a.name, v.is_option, v.id",
            (owner_type, owner_id),
        ).fetchall()
        specs = [_row(r) for r in rows]
        specs.sort(key=lambda s: (_CATEGORY_ORDER.get(s["category"], 99), s["attribute_name"], s["is_option"], s["id"]))
        return specs

    def get_spec(self, spec_id: int) -> dict | None:
        with self.db.get_conn() as conn:
            return _row(conn.execute(_SPEC_SELECT + " WHERE v.id = ?", (spec_id,)).fetchone())

    def add_spec(
        self, owner_type: str, owner_id: str, attribute_key: str, value_text: str,
        is_option: bool = False, note: str = "", source_file_id: str | None = None,
        source_page: int | None = None, source_note: str = "",
    ) -> dict:
        if owner_type not in OWNER_TYPES:
            raise ValueError(f"owner_type은 product 또는 component여야 합니다: {owner_type}")
        with self.db.transaction() as conn:
            if conn.execute(f"SELECT 1 FROM {owner_type} WHERE id = ?", (owner_id,)).fetchone() is None:
                raise SpecNotFoundError("제품 또는 부품을 찾을 수 없습니다.")
            attribute = conn.execute("SELECT data_type FROM spec_attribute WHERE key = ?", (attribute_key,)).fetchone()
            if attribute is None:
                raise ValueError(f"없는 속성입니다: {attribute_key}")
            value_text = _clean(value_text, field="값", max_length=300, required=True)
            value_num = parse_value(attribute["data_type"], value_text)
            try:
                cursor = conn.execute(
                    """
                    INSERT INTO spec_value
                    (owner_type, owner_id, attribute_key, value_text, value_num, is_option, note, source_file_id, source_page, source_note)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                    """,
                    (owner_type, owner_id, attribute_key, value_text, value_num, int(is_option),
                     _clean(note, field="비고", max_length=300), source_file_id or None, source_page,
                     _clean(source_note, field="출처 메모", max_length=200)),
                )
            except sqlite3.IntegrityError as exc:
                raise SpecConflictError(f"같은 속성에 같은 값이 이미 있습니다: {value_text}") from exc
            spec_id = cursor.lastrowid
        return self.get_spec(spec_id)

    def update_spec(self, spec_id: int, **fields) -> dict:
        current = self.get_spec(spec_id)
        if current is None:
            raise SpecNotFoundError("사양 값을 찾을 수 없습니다.")
        merged = {**current, **{k: v for k, v in fields.items() if k in fields and (v is not None or k in ("source_file_id", "source_page"))}}
        with self.db.transaction() as conn:
            attribute = conn.execute("SELECT data_type FROM spec_attribute WHERE key = ?", (merged["attribute_key"],)).fetchone()
            if attribute is None:
                raise ValueError(f"없는 속성입니다: {merged['attribute_key']}")
            value_text = _clean(merged["value_text"], field="값", max_length=300, required=True)
            value_num = parse_value(attribute["data_type"], value_text)
            try:
                conn.execute(
                    """
                    UPDATE spec_value
                    SET attribute_key = ?, value_text = ?, value_num = ?, is_option = ?, note = ?,
                        source_file_id = ?, source_page = ?, source_note = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (merged["attribute_key"], value_text, value_num, int(bool(merged["is_option"])),
                     _clean(merged["note"], field="비고", max_length=300), merged["source_file_id"] or None,
                     merged["source_page"], _clean(merged["source_note"], field="출처 메모", max_length=200),
                     _now(), spec_id),
                )
            except sqlite3.IntegrityError as exc:
                raise SpecConflictError(f"같은 속성에 같은 값이 이미 있습니다: {value_text}") from exc
        return self.get_spec(spec_id)

    def delete_spec(self, spec_id: int) -> None:
        with self.db.transaction() as conn:
            cursor = conn.execute("DELETE FROM spec_value WHERE id = ?", (spec_id,))
            if cursor.rowcount == 0:
                raise SpecNotFoundError("사양 값을 찾을 수 없습니다.")

    # ---------- 표 가져오기 ----------

    def find_owner(self, owner_type: str, model: str, kind: str | None = None) -> dict | None:
        """모델명(대소문자 무시)으로 제품 또는 부품을 찾는다. 가져오기 미리보기에서 열 머리글을 맞출 때 쓴다."""
        model = " ".join((model or "").split())
        if not model:
            return None
        with self.db.get_conn() as conn:
            return _row(_find_owner(conn, owner_type, model, kind))

    def import_values(
        self,
        owner_type: str,
        columns: list[dict],
        rows: list[dict],
        *,
        kind: str | None = None,
        replace: bool = True,
        source_note: str = "",
        source_page: int | None = None,
        source_file_id: str | None = None,
    ) -> dict:
        """미리보기에서 고친 표를 한 트랜잭션으로 저장한다.

        columns: [{"header": 모델명, "owner_id": 기존 id 또는 None, "create": 없으면 새로 등록할지, "skip": 열 건너뛰기,
                   "parent_model": 상위 모델명 (제품만, 선택), "name": 제품 이름 (제품만, 선택),
                   "category": 제품 종류 키 (제품만, 선택. 데스크톱 양식이면 desktop)}]
                 parent_model이 있으면 그 제품의 하위 모델로 옮긴다. 같은 표의 다른 열이거나 이미 등록된 모델이어야 한다.
                 비어 있으면 기존 상위 모델을 그대로 둔다. 자기 모델명을 적은 칸(병합 셀이 시리즈 열까지 덮은 경우)은 무시한다.
        rows:    [{"attribute_key": 키 또는 None, "new_attribute": {...} 또는 None, "cells": [열 순서대로 원문 문자열]}]
                 attribute_key도 new_attribute도 없는 행은 건너뛴다.
        replace: True면 표에 나온 (제품, 속성)의 기존 값을 지우고 표의 값으로 바꾼다. False면 없는 값만 더한다.
        값 하나라도 못 읽으면 SpecImportError를 던지고 아무것도 저장하지 않는다.
        """
        from parser.spec_table import split_cell  # 순환 import 방지 (spec_table이 parse_value를 쓴다)

        if owner_type not in OWNER_TYPES:
            raise ValueError(f"owner_type은 product 또는 component여야 합니다: {owner_type}")
        if owner_type == "component":
            kind = _choice(kind, COMPONENT_KINDS, field="부품 종류", default="other")
        source_note = _clean(source_note, field="출처 메모", max_length=200)
        errors: list[dict] = []
        summary = {"owners_created": 0, "parents_set": 0, "attributes_created": 0, "values_added": 0, "values_replaced": 0, "rows_skipped": 0}

        with self.db.transaction() as conn:
            # 1) 열 → 제품/부품 id
            owner_ids: list[str | None] = []
            for ci, column in enumerate(columns):
                if column.get("skip"):
                    owner_ids.append(None)
                    continue
                owner_id = column.get("owner_id")
                header = " ".join((column.get("header") or "").split())
                if owner_id:
                    if conn.execute(f"SELECT 1 FROM {owner_type} WHERE id = ?", (owner_id,)).fetchone() is None:
                        errors.append({"row": None, "column": ci, "message": f"'{header}' 열이 가리키는 항목이 없습니다. 미리보기를 다시 만드세요."})
                        owner_ids.append(None)
                        continue
                else:
                    existing = _find_owner(conn, owner_type, header, kind)
                    if existing is not None:
                        owner_id = existing["id"]
                    elif column.get("create", True):
                        try:
                            owner_id = _create_owner(conn, owner_type, header, kind)
                            summary["owners_created"] += 1
                        except ValueError as exc:
                            errors.append({"row": None, "column": ci, "message": str(exc)})
                            owner_ids.append(None)
                            continue
                    else:
                        owner_ids.append(None)
                        continue
                owner_ids.append(owner_id)

            # 1-1) 제품 정보: 이름과 상위 모델. 모든 열의 제품이 생긴 뒤에 맞춰야 앞 열이 뒤 열을 상위로 가리킬 수 있다
            if owner_type == "product":
                for ci, column in enumerate(columns):
                    owner_id = owner_ids[ci]
                    if owner_id is None:
                        continue
                    category = (column.get("category") or "").strip()
                    if category:
                        try:
                            conn.execute(
                                "UPDATE product SET category = ?, updated_at = ? WHERE id = ?",
                                (_choice(category, PRODUCT_CATEGORIES, field="제품 종류", default="notebook"), _now(), owner_id),
                            )
                        except ValueError as exc:
                            errors.append({"row": None, "column": ci, "message": str(exc)})
                    name = " ".join((column.get("name") or "").split())
                    if name:
                        try:
                            conn.execute(
                                "UPDATE product SET name = ?, updated_at = ? WHERE id = ?",
                                (_clean(name, field="제품 이름", max_length=100), _now(), owner_id),
                            )
                        except ValueError as exc:
                            errors.append({"row": None, "column": ci, "message": str(exc)})
                    parent_model = " ".join((column.get("parent_model") or "").split())
                    header = " ".join((column.get("header") or "").split())
                    if not parent_model or parent_model.lower() == header.lower():
                        continue
                    parent = _find_owner(conn, "product", parent_model, None)
                    if parent is None:
                        errors.append({
                            "row": None, "column": ci,
                            "message": f"'{header}'의 상위 모델 '{parent_model}'을(를) 찾을 수 없습니다. 같은 표에 열로 넣거나 먼저 등록하세요.",
                        })
                        continue
                    try:
                        _check_parent(conn, owner_id, parent["id"])
                    except (ValueError, SpecNotFoundError) as exc:
                        errors.append({"row": None, "column": ci, "message": f"'{header}': {exc}"})
                        continue
                    conn.execute("UPDATE product SET parent_id = ?, updated_at = ? WHERE id = ?", (parent["id"], _now(), owner_id))
                    summary["parents_set"] += 1

            # 2) 행 → 속성 키 (새 속성은 여기서 만든다)
            row_keys: list[str | None] = []
            for ri, row in enumerate(rows):
                key = (row.get("attribute_key") or "").strip() or None
                new_attribute = row.get("new_attribute")
                if key is None and new_attribute:
                    try:
                        values = _attribute_values(
                            new_attribute.get("key"), new_attribute.get("name"), new_attribute.get("category", "other"),
                            new_attribute.get("data_type", "text"), new_attribute.get("unit", ""),
                            new_attribute.get("description", ""), new_attribute.get("sort_order", 0),
                        )
                        if conn.execute("SELECT 1 FROM spec_attribute WHERE key = ?", (values[0],)).fetchone() is None:
                            _insert_attribute(conn, values)
                            summary["attributes_created"] += 1
                        key = values[0]
                    except (ValueError, SpecConflictError) as exc:
                        errors.append({"row": ri, "column": None, "message": str(exc)})
                elif key is not None and conn.execute("SELECT 1 FROM spec_attribute WHERE key = ?", (key,)).fetchone() is None:
                    errors.append({"row": ri, "column": None, "message": f"없는 속성입니다: {key}"})
                    key = None
                row_keys.append(key)

            # 3) 셀 → 값. 전부 검증한 뒤에 쓴다
            data_types = {r["key"]: r["data_type"] for r in conn.execute("SELECT key, data_type FROM spec_attribute").fetchall()}
            planned: dict[tuple[str, str], list[tuple[str, float | None, bool]]] = {}
            for ri, row in enumerate(rows):
                key = row_keys[ri]
                if key is None:
                    summary["rows_skipped"] += 1
                    continue
                for ci, raw in enumerate(row.get("cells") or []):
                    owner_id = owner_ids[ci] if ci < len(owner_ids) else None
                    if owner_id is None or not (raw or "").strip():
                        continue
                    for value in split_cell(raw):
                        try:
                            value_num = parse_value(data_types[key], value["value_text"])
                        except ValueError as exc:
                            errors.append({"row": ri, "column": ci, "message": str(exc)})
                            continue
                        planned.setdefault((owner_id, key), []).append((value["value_text"], value_num, value["is_option"]))

            if errors:
                raise SpecImportError(errors)

            # 4) 저장
            now = _now()
            for (owner_id, key), values in planned.items():
                if replace:
                    cursor = conn.execute(
                        "DELETE FROM spec_value WHERE owner_type = ? AND owner_id = ? AND attribute_key = ?",
                        (owner_type, owner_id, key),
                    )
                    summary["values_replaced"] += cursor.rowcount
                for value_text, value_num, is_option in values:
                    cursor = conn.execute(
                        """
                        INSERT OR IGNORE INTO spec_value
                        (owner_type, owner_id, attribute_key, value_text, value_num, is_option, note, source_file_id, source_page, source_note, created_at, updated_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (owner_type, owner_id, key, _clean(value_text, field="값", max_length=300, required=True), value_num,
                         int(is_option), "", source_file_id or None, source_page, source_note, now, now),
                    )
                    summary["values_added"] += cursor.rowcount

        summary["owners"] = [oid for oid in owner_ids if oid]
        return summary


def _check_parent(conn: sqlite3.Connection, product_id: str | None, parent_id: str | None) -> None:
    """상위 모델이 있는지, 자기 자신이나 자기 하위 모델을 상위로 고르지 않았는지 본다."""
    if parent_id is None:
        return
    if parent_id == product_id:
        raise ValueError("자기 자신을 상위 모델로 지정할 수 없습니다.")
    current = parent_id
    while current:
        row = conn.execute("SELECT parent_id FROM product WHERE id = ?", (current,)).fetchone()
        if row is None:
            raise SpecNotFoundError("상위 모델을 찾을 수 없습니다.")
        current = row["parent_id"]
        if product_id is not None and current == product_id:
            raise ValueError("하위 모델을 상위 모델로 지정할 수 없습니다.")


def _find_owner(conn: sqlite3.Connection, owner_type: str, model: str, kind: str | None) -> sqlite3.Row | None:
    if owner_type == "product":
        return conn.execute("SELECT * FROM product WHERE lower(model) = lower(?)", (model,)).fetchone()
    return conn.execute("SELECT * FROM component WHERE kind = ? AND lower(model) = lower(?)", (kind, model)).fetchone()


def _create_owner(conn: sqlite3.Connection, owner_type: str, model: str, kind: str | None) -> str:
    owner_id = str(uuid.uuid4())
    if owner_type == "product":
        conn.execute(
            "INSERT INTO product (id, model) VALUES (?, ?)",
            (owner_id, _clean(model, field="모델명", max_length=50, required=True)),
        )
    else:
        conn.execute(
            "INSERT INTO component (id, kind, model) VALUES (?, ?, ?)",
            (owner_id, kind, _clean(model, field="부품 모델명", max_length=100, required=True)),
        )
    return owner_id
