"""사양 DB를 그래프로 투영한다 (지시서 GR4). 사양 데이터(product, component, spec_value, product_component)는 읽기만 한다.

무엇을 만드는가 (GR4-1)
- 하위 모델이 있는 product → 제품군(product_line) 노드, 없는 product → 제품(product) 노드. parent_id → variant_of
- component 전부 → 부품 노드. product_component → has_component(is_option)
- 속성의 그래프 방식(spec_attribute.graph_mode)
  - entity: 값이 가리키는 대상 노드(예: cpu_model → 부품)와 관계(graph_relation_type, 기본 has_component)
  - value_node: 사양 값 노드(<속성 이름> <값 표기>)와 has_spec. 같은 속성·같은 값은 한 노드
  - none: 노드를 만들지 않는다
- 투영 관계의 origin은 spec. 대상이 직접 가진 값만 (상속 값은 상위 모델 노드에 있다)

동기화 (GR4-6)
- 매번 origin='spec' 관계만 지우고 다시 넣는다. 사람이 지운 관계(graph_exclusion·graph_relation_block)는 되살리지 않는다
- 노드는 ref(ref_type, ref_id, ref_value)로 찾는다. 사람이 바꾼 이름·종류(type_locked)를 덮지 않는다.
  사람이 지운 사양 노드(lifecycle_state='deleted')는 되살리지 않고 그 노드로 가는 관계도 만들지 않는다
- 종류는 매번 트리로 다시 정한다 (하위 모델이 생기면 제품 → 제품군). 사용 중지된 종류의 노드는 새로 만들지 않는다
"""
from __future__ import annotations

import logging
import time

from entity.spec_units import read_number
from graph_rag.rules import DEFAULT_VENDOR_PREFIXES, spec_match_keys, strip_trailing_parens, without_vendor
from graph_rag.types import normalize

logger = logging.getLogger(__name__)

SUMMARY_KEYS = ("product_lines", "products", "components", "value_nodes", "variant_of", "has_component", "has_spec",
                "entity_relations", "skipped", "blocked")
VALUE_NODE_TYPE = "spec_value"
VALUE_REF_TYPE = "spec_attribute"


def number_text(value: float) -> str:
    """정규 표기: 불필요한 소수점을 뺀다 (64.0 → 64, 2.50 → 2.5)."""
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.6f}".rstrip("0").rstrip(".")


def value_notation(attribute, row) -> str:
    """사양 값 노드의 값 표기 (GR4-4). 숫자는 속성 단위로 환산해 단위를 붙이고, 예/아니오는 지원/미지원, 텍스트는 그대로."""
    text = (row["value_text"] or "").strip()
    data_type = attribute["data_type"]
    if data_type == "number":
        unit = attribute["unit"] or ""
        read = read_number(text, unit, attribute["category"])
        if read.problem is None and read.value is not None:
            return f"{number_text(read.value)}{unit}"
        return text
    if data_type == "bool":
        number = row["value_num"]
        if number is None:
            word = text.lower()
            number = 1.0 if word in ("예", "있음", "o", "yes", "y", "true", "1", "지원") else 0.0 if word else None
        if number is None:
            return text
        return "지원" if number else "미지원"
    return text


class _Projection:
    def __init__(self, conn, vendors):
        self.conn = conn
        self.vendors = vendors
        self.summary = dict.fromkeys(SUMMARY_KEYS, 0)
        self.types = {r["key"]: bool(r["active"]) for r in conn.execute("SELECT key, active FROM graph_entity_type")}
        self.relation_types = {r["key"] for r in conn.execute("SELECT key FROM graph_relation_type WHERE active=1")}
        self.by_ref: dict[tuple, dict] = {}
        for row in conn.execute("""SELECT * FROM graph_entity WHERE ref_id IS NOT NULL AND lifecycle_state != 'merged'
                                   ORDER BY id"""):
            self.by_ref.setdefault((row["ref_type"], row["ref_id"], row["ref_value"] or ""), dict(row))
        self._loose: dict[str, dict[str, int]] = {}  # 종류 → 맞춤 키 → ref 없는 활성 개체 id
        self._typed: dict[str, dict[str, int]] = {}  # 종류 → 맞춤 키 → 활성 개체 id (ref 무관)

    # ------------------------------------------------------------ 찾기·만들기

    def _key_index(self, entity_type: str, loose_only: bool) -> dict[str, int]:
        cache = self._loose if loose_only else self._typed
        if entity_type not in cache:
            index: dict[str, int] = {}
            ref_filter = "AND e.ref_id IS NULL" if loose_only else ""
            for row in self.conn.execute(f"""SELECT e.id, a.alias FROM graph_entity e JOIN graph_alias a ON a.entity_id=e.id
                                             WHERE e.type=? AND e.lifecycle_state='active' {ref_filter} ORDER BY e.id""",
                                         (entity_type,)):
                for key in [normalize(row["alias"]), *spec_match_keys(row["alias"], self.vendors)]:
                    if key:
                        index.setdefault(key, row["id"])
            cache[entity_type] = index
        return cache[entity_type]

    def _forget(self):
        self._loose.clear()
        self._typed.clear()

    def _alias(self, entity_id: int, alias: str) -> None:
        alias = (alias or "").strip()
        alias_norm = normalize(alias)
        if len(alias_norm) >= 2:
            self.conn.execute("INSERT OR IGNORE INTO graph_alias (entity_id, alias, alias_norm) VALUES (?, ?, ?)",
                              (entity_id, alias, alias_norm))

    def _absorb(self, source_id: int, target_id: int) -> None:
        """같은 종류·이름의 ref 없는 개체를 사양 노드로 합친다 (종류를 바꿀 때 유일 키가 겹치는 경우)."""
        conn = self.conn
        conn.execute("INSERT OR IGNORE INTO graph_alias (entity_id, alias, alias_norm, hidden) "
                     "SELECT ?, alias, alias_norm, hidden FROM graph_alias WHERE entity_id=?", (target_id, source_id))
        conn.execute("INSERT OR IGNORE INTO graph_mention SELECT ?, file_id, page FROM graph_mention WHERE entity_id=?",
                     (target_id, source_id))
        conn.execute("DELETE FROM graph_mention WHERE entity_id=?", (source_id,))
        for row in conn.execute("SELECT * FROM graph_relation WHERE src_id=? OR dst_id=?", (source_id, source_id)).fetchall():
            src = target_id if row["src_id"] == source_id else row["src_id"]
            dst = target_id if row["dst_id"] == source_id else row["dst_id"]
            duplicate = conn.execute("SELECT 1 FROM graph_relation WHERE src_id=? AND dst_id=? AND type=? AND source_key=? AND id!=?",
                                     (src, dst, row["type"], row["source_key"], row["id"])).fetchone()
            if src == dst or duplicate:
                conn.execute("UPDATE graph_relation SET lifecycle_state='deleted' WHERE id=?", (row["id"],))
            else:
                conn.execute("UPDATE graph_relation SET src_id=?, dst_id=? WHERE id=?", (src, dst, row["id"]))
        conn.execute("UPDATE graph_property_value SET entity_id=? WHERE entity_id=?", (target_id, source_id))
        conn.execute("""INSERT OR IGNORE INTO graph_exclusion SELECT CASE WHEN src_id=? THEN ? ELSE src_id END,
                        CASE WHEN dst_id=? THEN ? ELSE dst_id END, type, source_key FROM graph_exclusion
                        WHERE src_id=? OR dst_id=?""", (source_id, target_id, source_id, target_id, source_id, source_id))
        # 병합 흔적은 이름 키를 비켜 둔다 (같은 종류·같은 norm 유일 키)
        conn.execute("""UPDATE graph_entity SET lifecycle_state='merged', merged_into_id=?, manual_retained=1,
                        norm = norm || ':merged:' || id, updated_at=CURRENT_TIMESTAMP WHERE id=?""", (target_id, source_id))
        conn.execute("""INSERT INTO graph_edit_event (target_kind,target_id,action,before_json,after_json,correlation_id)
                        VALUES ('entity', ?, 'merge', NULL, ?, 'spec-projection')""",
                     (str(source_id), f'{{"merged_into": {target_id}, "by": "spec-projection"}}'))
        self._forget()

    def _retype(self, node: dict, kind: str) -> None:
        if node["type_locked"] or node["type"] == kind:
            return
        if not self.types.get(kind):
            self.summary["skipped"] += 1
            return
        other = self.conn.execute("SELECT * FROM graph_entity WHERE type=? AND norm=? AND id!=?",
                                  (kind, node["norm"], node["id"])).fetchone()
        if other is not None:
            if other["ref_id"] is None and other["lifecycle_state"] == "active":
                self._absorb(other["id"], node["id"])
            else:
                self.summary["skipped"] += 1
                return
        self.conn.execute("UPDATE graph_entity SET type=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (kind, node["id"]))
        node["type"] = kind
        self._forget()

    def _create(self, kind: str, name: str, ref: tuple, disambiguator: str = "") -> int | None:
        ref_type, ref_id, ref_value = ref
        base = (name or "").strip()
        for candidate in (base, f"{base} ({disambiguator})" if disambiguator else None, f"{base} ({(ref_id or '')[:8]})"):
            if not candidate or len(normalize(candidate)) < 2:
                continue
            norm = normalize(candidate)
            if self.conn.execute("SELECT 1 FROM graph_entity WHERE type=? AND norm=?", (kind, norm)).fetchone():
                continue
            cur = self.conn.execute("""INSERT INTO graph_entity (type, name, norm, creation_origin, ref_type, ref_id, ref_value)
                                       VALUES (?, ?, ?, 'spec', ?, ?, ?)""",
                                    (kind, candidate, norm, ref_type, ref_id, ref_value or None))
            self._alias(cur.lastrowid, candidate)
            row = dict(self.conn.execute("SELECT * FROM graph_entity WHERE id=?", (cur.lastrowid,)).fetchone())
            if ref_id is not None:
                self.by_ref[(ref_type, ref_id, ref_value or "")] = row
            self._forget()
            return cur.lastrowid
        self.summary["skipped"] += 1
        return None

    def node(self, kind: str, name: str, ref: tuple, adopt_types: tuple[str, ...] = (), disambiguator: str = "",
             managed_name: str | None = None) -> int | None:
        """ref로 사양 노드를 찾는다. 없으면 ref 없는 같은 이름 개체를 데려오고, 그것도 없으면 만든다.

        managed_name: 투영이 관리하는 이름(사양 값 노드). 사람이 이름을 고치지 않았으면 이 이름으로 맞춘다.
        """
        node = self.by_ref.get(ref)
        if node is not None:
            if node["lifecycle_state"] == "deleted":
                self.summary["skipped"] += 1
                return None
            self._retype(node, kind)
            self._alias(node["id"], name)
            if managed_name and not node["display_name"] and not node["manual_retained"] and node["name"] != managed_name:
                norm = normalize(managed_name)
                if not self.conn.execute("SELECT 1 FROM graph_entity WHERE type=? AND norm=? AND id!=?",
                                         (node["type"], norm, node["id"])).fetchone():
                    self.conn.execute("UPDATE graph_entity SET name=?, norm=? WHERE id=?", (managed_name, norm, node["id"]))
                    node.update(name=managed_name, norm=norm)
            return node["id"]
        if not self.types.get(kind):
            self.summary["skipped"] += 1
            return None
        keys = [normalize(name), *spec_match_keys(name, self.vendors)]
        for adopt_type in adopt_types:
            index = self._key_index(adopt_type, loose_only=True)
            entity_id = next((index[k] for k in keys if k in index), None)
            if entity_id is None:
                continue
            ref_type, ref_id, ref_value = ref
            self.conn.execute("""UPDATE graph_entity SET ref_type=?, ref_id=?, ref_value=?,
                                 creation_origin=CASE WHEN creation_origin='extract' THEN 'spec' ELSE creation_origin END
                                 WHERE id=?""", (ref_type, ref_id, ref_value or None, entity_id))
            row = dict(self.conn.execute("SELECT * FROM graph_entity WHERE id=?", (entity_id,)).fetchone())
            self.by_ref[ref] = row
            self._forget()
            self._retype(row, kind)
            self._alias(entity_id, name)
            return entity_id
        return self._create(kind, name, ref, disambiguator)

    # ------------------------------------------------------------ 관계

    def put(self, src: int | None, dst: int | None, rel_type: str, counter: str, is_option=False, source_key: str = "") -> None:
        if src is None or dst is None or src == dst:
            return
        if rel_type not in self.relation_types:
            self.summary["skipped"] += 1
            return
        if self._blocked(src, dst, rel_type, source_key or "spec::-1"):
            self.summary["blocked"] += 1
            return
        cur = self.conn.execute("""INSERT OR IGNORE INTO graph_relation (src_id, dst_id, type, origin, is_option, source_key)
                                   VALUES (?, ?, ?, 'spec', ?, ?)""", (src, dst, rel_type, int(bool(is_option)), source_key))
        self.summary[counter] += cur.rowcount

    def _blocked(self, src: int, dst: int, rel_type: str, source_key: str) -> bool:
        if self.conn.execute("SELECT 1 FROM graph_exclusion WHERE src_id=? AND dst_id=? AND type=? AND source_key IN ('*', ?)",
                             (src, dst, rel_type, source_key)).fetchone():
            return True
        s = self.conn.execute("SELECT type, norm FROM graph_entity WHERE id=?", (src,)).fetchone()
        d = self.conn.execute("SELECT type, norm FROM graph_entity WHERE id=?", (dst,)).fetchone()
        return self.conn.execute("""SELECT 1 FROM graph_relation_block WHERE src_type=? AND src_norm=? AND type=?
                                    AND dst_type=? AND dst_norm=?""", (s["type"], s["norm"], rel_type, d["type"], d["norm"])).fetchone() is not None

    # ------------------------------------------------------------ 투영

    def run(self) -> dict:
        conn = self.conn
        conn.execute("DELETE FROM graph_relation WHERE origin = 'spec'")
        conn.execute("""UPDATE graph_entity SET ref_type=NULL, ref_id=NULL, ref_value=NULL
                        WHERE ref_type='product' AND ref_id NOT IN (SELECT id FROM product)""")
        conn.execute("""UPDATE graph_entity SET ref_type=NULL, ref_id=NULL, ref_value=NULL
                        WHERE ref_type='component' AND ref_id NOT IN (SELECT id FROM component)""")
        conn.execute("""UPDATE graph_entity SET ref_type=NULL, ref_id=NULL, ref_value=NULL
                        WHERE ref_type=? AND ref_id NOT IN (SELECT key FROM spec_attribute)""", (VALUE_REF_TYPE,))

        products = conn.execute("SELECT id, model, name, parent_id FROM product ORDER BY model").fetchall()
        parents = {p["parent_id"] for p in products if p["parent_id"]}
        product_nodes: dict[str, int] = {}
        for product in products:
            kind = "product_line" if product["id"] in parents else "product"
            node_id = self.node(kind, product["model"], ("product", product["id"], ""), ("product", "product_line"))
            if node_id is None:
                continue
            product_nodes[product["id"]] = node_id
            name = (product["name"] or "").strip()
            # 제품 이름은 모델명을 담을 때만 별칭으로 쓴다 ("Home", "Pro" 같은 이름은 아무 질문에나 걸린다)
            if name and normalize(product["model"]) in normalize(name):
                self._alias(node_id, name)
        for product in products:
            if product["parent_id"]:
                self.put(product_nodes.get(product["id"]), product_nodes.get(product["parent_id"]), "variant_of", "variant_of")

        component_nodes: dict[str, int] = {}
        component_keys: dict[str, str | None] = {}
        for component in conn.execute("SELECT id, kind, model FROM component ORDER BY kind, model").fetchall():
            node_id = self.node("component", component["model"], ("component", component["id"], ""), ("component", "product"),
                                disambiguator=component["kind"])
            if node_id is not None:
                component_nodes[component["id"]] = node_id
            for key in spec_match_keys(component["model"], self.vendors):
                component_keys[key] = None if key in component_keys and component_keys[key] != component["id"] else component["id"]
        for link in conn.execute("SELECT product_id, component_id, is_option FROM product_component").fetchall():
            self.put(product_nodes.get(link["product_id"]), component_nodes.get(link["component_id"]), "has_component",
                     "has_component", link["is_option"])

        attributes = {r["key"]: r for r in conn.execute("SELECT * FROM spec_attribute")}
        owners = {"product": product_nodes, "component": component_nodes}
        value_nodes: set[int] = set()
        for row in conn.execute("SELECT * FROM spec_value ORDER BY id").fetchall():
            attribute = attributes.get(row["attribute_key"])
            owner = owners.get(row["owner_type"], {}).get(row["owner_id"])
            if attribute is None or owner is None:
                continue
            mode = attribute["graph_mode"] or "value_node"
            source_key = f"spec:value:{row['id']}"
            if mode == "none":
                continue
            if mode == "entity":
                target = self._value_target(attribute, row, component_keys, component_nodes)
                self.put(owner, target, attribute["graph_relation_type"] or "has_component", "entity_relations",
                         row["is_option"], source_key)
                continue
            notation = value_notation(attribute, row)
            if len(normalize(notation)) < 1:
                continue
            name = f"{attribute['name']} {notation}"
            node_id = self.node(VALUE_NODE_TYPE, name, (VALUE_REF_TYPE, attribute["key"], normalize(notation)),
                                disambiguator=attribute["key"], managed_name=name)
            if node_id is not None:
                value_nodes.add(node_id)
                self.put(owner, node_id, "has_spec", "has_spec", row["is_option"], source_key)

        self.summary["product_lines"] = sum(1 for p in products if p["id"] in product_nodes and p["id"] in parents)
        self.summary["products"] = sum(1 for p in products if p["id"] in product_nodes and p["id"] not in parents)
        self.summary["components"] = len(component_nodes)
        self.summary["value_nodes"] = len(value_nodes)
        return self.summary

    def _value_target(self, attribute, row, component_keys, component_nodes) -> int | None:
        """대상을 가리키는 값(GR4-3)의 도착 노드. 사양 DB 부품 → 같은 종류의 기존 노드 → 새 노드."""
        target_type = attribute["graph_entity_type"] or "component"
        raw = (row["value_text"] or "").strip()
        name = strip_trailing_parens(raw)
        if len(normalize(name)) < 2:
            self.summary["skipped"] += 1
            return None
        keys = [normalize(name), *spec_match_keys(name, self.vendors)]
        if target_type == "component":
            component_id = next((component_keys[k] for k in keys if component_keys.get(k)), None)
            if component_id is not None and component_id in component_nodes:
                node_id = component_nodes[component_id]
                for alias in (raw, without_vendor(name, self.vendors)):
                    self._alias(node_id, alias)
                return node_id
        index = self._key_index(target_type, loose_only=False)
        node_id = next((index[k] for k in keys if k in index), None)
        if node_id is None:
            if not self.types.get(target_type):
                self.summary["skipped"] += 1
                return None
            node_id = self._create(target_type, name, (None, None, None))
            if node_id is None:
                return None
        for alias in (raw, without_vendor(name, self.vendors)):
            self._alias(node_id, alias)
        self._forget()
        return node_id


def project_specs(conn, vendors=DEFAULT_VENDOR_PREFIXES) -> dict:
    """한 트랜잭션 안에서 부른다. 투영 요약과 걸린 시간(seconds)을 돌려준다."""
    started = time.perf_counter()
    summary = _Projection(conn, vendors).run()
    # 관계가 하나도 없게 된 사양 값 노드를 정리한다 (사람이 고친 노드는 남는다)
    conn.execute(f"""DELETE FROM graph_entity
        WHERE type_locked=0 AND manual_retained=0 AND lifecycle_state='active'
          AND (ref_type='{VALUE_REF_TYPE}' OR (ref_id IS NULL AND creation_origin='spec'))
          AND NOT EXISTS (SELECT 1 FROM graph_relation r WHERE r.src_id=graph_entity.id OR r.dst_id=graph_entity.id)
          AND NOT EXISTS (SELECT 1 FROM graph_mention m WHERE m.entity_id=graph_entity.id)
          AND NOT EXISTS (SELECT 1 FROM graph_property_value p WHERE p.entity_id=graph_entity.id)
          AND NOT EXISTS (SELECT 1 FROM graph_entity e WHERE e.merged_into_id=graph_entity.id)""")
    summary["seconds"] = round(time.perf_counter() - started, 3)
    return summary
