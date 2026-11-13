"""문서 그래프 저장소 (graph_entity, graph_alias, graph_mention, graph_relation, graph_relation_block 테이블).

문서에서 뽑은 개체·관계는 (file_id, page) 단위로 통째로 갈아끼운다. 페이지 검수로 텍스트가 바뀌면
그 페이지만 다시 뽑아 replace_page()를 부른다. 어느 페이지에도 안 나오고 관계도 없는 개체는 치운다.

관계의 출처(origin)
- extract: 문서에서 뽑음. 그 페이지를 다시 뽑으면 갈아끼운다.
- seed: aliases.yaml의 상위 개념 연결. 서버 시작 때 다시 넣는다.
- manual: 그래프 화면에서 사람이 넣음. 다시 뽑아도 유지한다.
사람이 화면에서 지운 관계는 graph_relation_block에 남겨 다시 뽑아도 되살리지 않는다.
"""
from __future__ import annotations

import re
import sqlite3

from graph_rag.types import ENTITY_TYPES, RELATION_TYPES, PageGraph, normalize
from repository.repo_connect import Database

# 이보다 짧은 표기는 검색어 안에 우연히 들어 있을 수 있어 개체로 쓰지 않는다 (예: "PC", "KC"는 2자라 허용)
MIN_NORM_LEN = 2
# 검색어 단어로 시작하는 개체 표기도 찾는 최소 길이 (예: "N5800" -> "N5800 14세대")
MIN_PARTIAL_LEN = 3

# 어절 끝에서 뗄 조사. 긴 것부터 본다 ("에서"를 "에"보다 먼저)
_PARTICLES = ("에서", "부터", "까지", "으로", "의", "은", "는", "이", "가", "을", "를", "에", "로", "과", "와", "도")
# 영숫자 식별자: N5800, N5800-GB70-PU02, R-R-TGE-N5800, v1.3
_IDENTIFIER = re.compile(r"[A-Za-z0-9]+(?:[-_.][A-Za-z0-9]+)*")


def _query_tokens(query: str) -> list[str]:
    """접두 일치에 쓸 검색어 단어 (정규화, MIN_PARTIAL_LEN자 이상).

    (a) 영숫자 식별자, (b) 공백·쉼표로 나눈 어절, (c) 어절 끝 조사 하나를 뗀 것.
    한글 접미사를 무조건 지우지 않는다. (c)는 후보를 더할 뿐이다.
    """
    words = [w for w in re.split(r"[\s,]+", query) if w]
    candidates = list(_IDENTIFIER.findall(query)) + words
    for word in words:
        for particle in _PARTICLES:
            if word.endswith(particle) and len(word) > len(particle):
                candidates.append(word[: -len(particle)])
                break
    tokens = {normalize(t) for t in candidates}
    return sorted(t for t in tokens if len(t) >= MIN_PARTIAL_LEN)


_RELATION_COLUMNS = """r.id, r.type, r.origin, r.page, r.file_id, f.original_name,
                       s.id AS source_id, s.type AS source_type, s.name AS source_name,
                       d.id AS target_id, d.type AS target_type, d.name AS target_name"""
_RELATION_JOINS = """FROM graph_relation r
                     JOIN graph_entity s ON s.id = r.src_id
                     JOIN graph_entity d ON d.id = r.dst_id
                     LEFT JOIN file f ON f.file_id = r.file_id"""


class GraphNotFoundError(LookupError):
    """없는 개체·관계"""


class GraphEditError(ValueError):
    """그래프 편집 요청이 규칙에 맞지 않음 (화면에 그대로 보여줄 메시지)"""


class GraphRepository:

    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------ 추출 결과 쓰기

    def seed_concepts(self, concepts: dict[str, list[str]]) -> int:
        """aliases.yaml의 '상위 개념: [인증 종류, ...]'를 concept 개체와 part_of 관계로 넣는다.

        매번 seed 관계를 지우고 다시 넣어 yaml 수정이 반영되게 한다. 화면에서 지운 연결은 넣지 않는다.
        넣은 part_of 관계 수를 돌려준다.
        """
        count = 0
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM graph_relation WHERE origin = 'seed'")
            for concept, members in (concepts or {}).items():
                concept_id = _upsert_entity(conn, "concept", str(concept))
                if concept_id is None:
                    continue
                for member in members or []:
                    member_id = _upsert_entity(conn, "certification", str(member))
                    if member_id is None or member_id == concept_id or _is_blocked(conn, member_id, concept_id, "part_of"):
                        continue
                    conn.execute(
                        "INSERT OR IGNORE INTO graph_relation (src_id, dst_id, type, origin) VALUES (?, ?, 'part_of', 'seed')",
                        (member_id, concept_id),
                    )
                    count += 1
            _prune_orphans(conn)
        return count

    def seed_specs(self) -> dict:
        """사양 DB의 제품과 제품-부품 연결을 그래프에 심는다 (지시서 H2). 서버 시작 때와 제품·연결이 바뀔 때 부른다.

        - 제품은 전부: product.model → product 개체(ref_type='product'), 제품 이름은 모델명을 담을 때만 별칭으로.
          parent_id → variant_of(파생 모델 → 상위 모델).
        - 부품은 제품에 연결된 것만: product_component → has_component(옵션 여부는 is_option). 연결되지 않은 부품은 심지 않는다.
        - 심은 관계의 origin은 spec. 매번 spec 관계만 지우고 다시 넣는다. 문서에서 뽑은 관계·사람이 넣은 관계는 건드리지 않고,
          화면에서 지운 관계(graph_relation_block)는 되살리지 않는다.
        - 같은 이름(정규화)의 개체가 이미 있으면 새로 만들지 않고 그 개체에 ref_type·ref_id를 단다.
        - 사양 DB에서 사라진 대상을 가리키는 ref는 지운다 (문서에도 안 나오고 관계도 없으면 개체가 정리된다).
        넣은 개수를 돌려준다.
        """
        summary = {"products": 0, "components": 0, "variant_of": 0, "has_component": 0, "blocked": 0}
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM graph_relation WHERE origin = 'spec'")
            conn.execute("""UPDATE graph_entity SET ref_type = NULL, ref_id = NULL
                            WHERE ref_type = 'product' AND ref_id NOT IN (SELECT id FROM product)""")
            conn.execute("""UPDATE graph_entity SET ref_type = NULL, ref_id = NULL
                            WHERE ref_type = 'component' AND ref_id NOT IN (SELECT id FROM component)""")

            products = conn.execute("SELECT id, model, name, parent_id FROM product ORDER BY model").fetchall()
            product_entities: dict[str, int] = {}
            for product in products:
                entity_id = _link_spec_entity(conn, "product", product["model"], "product", product["id"])
                if entity_id is None:
                    continue
                product_entities[product["id"]] = entity_id
                summary["products"] += 1
                name = (product["name"] or "").strip()
                # 제품 이름은 모델명을 담을 때만 별칭으로 쓴다 ("Home", "Pro" 같은 이름은 아무 질문에나 걸린다)
                if name and normalize(product["model"]) in normalize(name):
                    _add_alias(conn, entity_id, name)

            def put(src: int, dst: int, rel_type: str, is_option: bool = False) -> None:
                if src == dst:
                    return
                if _is_blocked(conn, src, dst, rel_type):
                    summary["blocked"] += 1
                    return
                cur = conn.execute(
                    "INSERT OR IGNORE INTO graph_relation (src_id, dst_id, type, origin, is_option) VALUES (?, ?, ?, 'spec', ?)",
                    (src, dst, rel_type, int(is_option)),
                )
                summary[rel_type] += cur.rowcount

            for product in products:
                if product["parent_id"] and product["id"] in product_entities and product["parent_id"] in product_entities:
                    put(product_entities[product["id"]], product_entities[product["parent_id"]], "variant_of")

            links = conn.execute(
                """SELECT pc.product_id, pc.is_option, c.id AS component_id, c.model
                   FROM product_component pc JOIN component c ON c.id = pc.component_id
                   ORDER BY c.model"""
            ).fetchall()
            linked_components: set[str] = set()
            for link in links:
                if link["product_id"] not in product_entities:
                    continue
                component_entity = _link_spec_entity(conn, "component", link["model"], "component", link["component_id"])
                if component_entity is None:
                    continue
                linked_components.add(link["component_id"])
                put(product_entities[link["product_id"]], component_entity, "has_component", bool(link["is_option"]))
            summary["components"] = len(linked_components)
            _prune_orphans(conn)
        return summary

    def spec_names(self) -> dict[str, list[dict]]:
        """추출 프롬프트에 넘길 사양 DB의 정식 이름 (지시서 H3). 제품은 전부, 부품은 전부(페이지별로 거르는 것은 호출부).

        {"product": [{"name": 모델명, "aliases": [제품 이름]}], "component": [{"name": 모델명, "kind": 종류}]}
        """
        with self.db.get_conn() as conn:
            products = conn.execute("SELECT model, name FROM product ORDER BY model").fetchall()
            components = conn.execute("SELECT model, kind FROM component ORDER BY kind, model").fetchall()
        return {
            "product": [{"name": p["model"], "aliases": [p["name"]] if (p["name"] or "").strip() else []} for p in products],
            "component": [{"name": c["model"], "kind": c["kind"]} for c in components],
        }

    def replace_page(self, file_id: str, page: int, graph: PageGraph) -> dict:
        """한 페이지에서 뽑은 개체·관계로 그 페이지의 그래프를 갈아끼운다. 사람이 넣은 관계는 그대로 둔다."""
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM graph_mention WHERE file_id = ? AND page = ?", (file_id, page))
            conn.execute(
                "DELETE FROM graph_relation WHERE file_id = ? AND page = ? AND origin = 'extract'", (file_id, page)
            )

            ids_by_norm: dict[str, int] = {}
            entity_ids: set[int] = set()
            pending: list[tuple[int, int, str]] = []  # (src, dst, type)
            for entity in graph.entities:
                entity_id = _upsert_entity(conn, entity.type, entity.name)
                if entity_id is None:
                    continue
                entity_ids.add(entity_id)
                ids_by_norm.setdefault(normalize(entity.name), entity_id)
                if entity.concept:
                    # 추출기가 고른 상위 개념. 이 페이지에서 나온 연결이라 페이지를 다시 뽑으면 같이 바뀐다
                    concept = conn.execute(
                        "SELECT id FROM graph_entity WHERE type = 'concept' AND norm = ?", (normalize(entity.concept),)
                    ).fetchone()
                    if concept is not None:
                        pending.append((entity_id, concept[0], "part_of"))
                for alias in entity.aliases:
                    alias_norm = normalize(alias)
                    if len(alias_norm) < MIN_NORM_LEN:
                        continue
                    conn.execute(
                        "INSERT OR IGNORE INTO graph_alias (entity_id, alias, alias_norm) VALUES (?, ?, ?)",
                        (entity_id, alias.strip(), alias_norm),
                    )
                    ids_by_norm.setdefault(alias_norm, entity_id)

            conn.executemany(
                "INSERT OR IGNORE INTO graph_mention (entity_id, file_id, page) VALUES (?, ?, ?)",
                [(entity_id, file_id, page) for entity_id in entity_ids],
            )

            for relation in graph.relations:
                src = ids_by_norm.get(normalize(relation.source))
                dst = ids_by_norm.get(normalize(relation.target))
                if src is not None and dst is not None:  # entities에 없는 이름을 가리키는 관계는 버린다
                    pending.append((src, dst, relation.type))

            relations = 0
            for src, dst, rel_type in pending:
                if src == dst or _is_blocked(conn, src, dst, rel_type):
                    continue
                cur = conn.execute(
                    "INSERT OR IGNORE INTO graph_relation (src_id, dst_id, type, file_id, page, origin) VALUES (?, ?, ?, ?, ?, 'extract')",
                    (src, dst, rel_type, file_id, page),
                )
                relations += cur.rowcount
            _prune_orphans(conn)
        return {"entities": len(entity_ids), "relations": relations}

    def delete_file(self, file_id: str) -> None:
        """다시 뽑기 전에 파일 하나에서 뽑은 그래프를 지운다. 사람이 넣은 관계는 남긴다.

        파일 행을 지우면 외래키로 등장 위치와 그 파일을 근거로 한 관계가 모두 지워진다.
        """
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM graph_mention WHERE file_id = ?", (file_id,))
            conn.execute("DELETE FROM graph_relation WHERE file_id = ? AND origin = 'extract'", (file_id,))
            _prune_orphans(conn)

    def prune_orphans(self) -> int:
        """파일 삭제 뒤에 부른다. 지운 개체 수를 돌려준다."""
        with self.db.transaction() as conn:
            return _prune_orphans(conn)

    # ------------------------------------------------------------ 화면에서 편집

    def add_relation(
        self,
        source_id: int,
        rel_type: str,
        target_id: int | None = None,
        new_target: tuple[str, str] | None = None,
        file_id: str | None = None,
        page: int | None = None,
    ) -> dict:
        """사람이 관계를 넣는다. 도착 개체는 기존 개체(target_id) 또는 새 개체(new_target=(종류, 이름))다.

        새 개체는 같은 종류에 같은 표기가 있으면 그 개체를 쓴다. 같은 관계를 전에 지웠다면 차단을 푼다.
        """
        if rel_type not in RELATION_TYPES:
            raise GraphEditError(f"없는 관계 종류입니다: {rel_type}")
        if (target_id is None) == (new_target is None):
            raise GraphEditError("도착 개체를 하나만 지정하세요 (기존 개체 또는 새 개체).")
        with self.db.transaction() as conn:
            source = _entity_row(conn, source_id)
            if new_target is not None:
                target_type, target_name = new_target
                if target_type not in ENTITY_TYPES:
                    raise GraphEditError(f"없는 개체 종류입니다: {target_type}")
                target_id = _upsert_entity(conn, target_type, target_name)
                if target_id is None:
                    raise GraphEditError(f"개체 이름은 기호를 빼고 {MIN_NORM_LEN}자 이상이어야 합니다.")
            target = _entity_row(conn, target_id)
            if source["id"] == target["id"]:
                raise GraphEditError("같은 개체끼리는 연결할 수 없습니다.")
            if rel_type == "part_of" and target["type"] != "concept":
                raise GraphEditError("상위 개념(part_of) 관계의 도착 개체는 상위 개념이어야 합니다.")
            if file_id is not None and conn.execute("SELECT 1 FROM file WHERE file_id = ?", (file_id,)).fetchone() is None:
                raise GraphEditError("근거 문서를 찾을 수 없습니다.")

            _unblock(conn, source, target, rel_type)
            existing = conn.execute(
                """SELECT id FROM graph_relation
                   WHERE src_id = ? AND dst_id = ? AND type = ? AND ifnull(file_id, '') = ifnull(?, '') AND ifnull(page, -1) = ifnull(?, -1)""",
                (source["id"], target["id"], rel_type, file_id, page),
            ).fetchone()
            if existing is not None:
                # 같은 근거로 뽑힌 관계가 이미 있으면 사람이 확인한 관계로 바꾼다 (다시 뽑아도 유지)
                conn.execute("UPDATE graph_relation SET origin = 'manual' WHERE id = ?", (existing[0],))
                relation_id = existing[0]
            else:
                relation_id = conn.execute(
                    "INSERT INTO graph_relation (src_id, dst_id, type, file_id, page, origin) VALUES (?, ?, ?, ?, ?, 'manual')",
                    (source["id"], target["id"], rel_type, file_id, page),
                ).lastrowid
            return _relation(conn, relation_id)

    def delete_relation(self, relation_id: int) -> int:
        """관계를 지운다. 같은 두 개체 사이의 같은 종류 관계는 근거 페이지가 달라도 모두 지우고,
        다시 뽑거나 aliases.yaml을 다시 넣어도 되살아나지 않게 차단한다. 지운 관계 수를 돌려준다."""
        with self.db.transaction() as conn:
            row = conn.execute("SELECT src_id, dst_id, type FROM graph_relation WHERE id = ?", (relation_id,)).fetchone()
            if row is None:
                raise GraphNotFoundError("관계를 찾을 수 없습니다.")
            _block(conn, row["src_id"], row["dst_id"], row["type"])
            cur = conn.execute(
                "DELETE FROM graph_relation WHERE src_id = ? AND dst_id = ? AND type = ?",
                (row["src_id"], row["dst_id"], row["type"]),
            )
            _prune_orphans(conn)
            return cur.rowcount

    def update_relation(self, relation_id: int, rel_type: str | None = None, reverse: bool = False) -> dict:
        """관계 종류를 바꾸거나 방향을 뒤집는다. 원래 관계는 지우고 차단한 뒤 사람이 넣은 관계로 새로 만든다.
        근거 문서·페이지는 그대로 옮긴다."""
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT src_id, dst_id, type, file_id, page FROM graph_relation WHERE id = ?", (relation_id,)
            ).fetchone()
            if row is None:
                raise GraphNotFoundError("관계를 찾을 수 없습니다.")
            new_type = rel_type or row["type"]
            if new_type not in RELATION_TYPES:
                raise GraphEditError(f"없는 관계 종류입니다: {new_type}")
            src, dst = (row["dst_id"], row["src_id"]) if reverse else (row["src_id"], row["dst_id"])
            if new_type == row["type"] and (src, dst) == (row["src_id"], row["dst_id"]):
                return _relation(conn, relation_id)
            if new_type == "part_of" and _entity_row(conn, dst)["type"] != "concept":
                raise GraphEditError("상위 개념(part_of) 관계의 도착 개체는 상위 개념이어야 합니다.")

            _block(conn, row["src_id"], row["dst_id"], row["type"])
            conn.execute(
                "DELETE FROM graph_relation WHERE src_id = ? AND dst_id = ? AND type = ?",
                (row["src_id"], row["dst_id"], row["type"]),
            )
            _unblock(conn, _entity_row(conn, src), _entity_row(conn, dst), new_type)
            conn.execute(
                "INSERT OR IGNORE INTO graph_relation (src_id, dst_id, type, file_id, page, origin) VALUES (?, ?, ?, ?, ?, 'manual')",
                (src, dst, new_type, row["file_id"], row["page"]),
            )
            conn.execute(
                """UPDATE graph_relation SET origin = 'manual'
                   WHERE src_id = ? AND dst_id = ? AND type = ? AND ifnull(file_id, '') = ifnull(?, '') AND ifnull(page, -1) = ifnull(?, -1)""",
                (src, dst, new_type, row["file_id"], row["page"]),
            )
            new_id = conn.execute(
                """SELECT id FROM graph_relation
                   WHERE src_id = ? AND dst_id = ? AND type = ? AND ifnull(file_id, '') = ifnull(?, '') AND ifnull(page, -1) = ifnull(?, -1)""",
                (src, dst, new_type, row["file_id"], row["page"]),
            ).fetchone()[0]
            return _relation(conn, new_id)

    def rename_entity(self, entity_id: int, name: str) -> dict:
        """개체 표시 이름을 바꾼다. 옛 이름은 별칭으로 남아 다시 뽑아도 같은 개체로 묶인다."""
        name = (name or "").strip()
        norm = normalize(name)
        if len(norm) < MIN_NORM_LEN:
            raise GraphEditError(f"개체 이름은 기호를 빼고 {MIN_NORM_LEN}자 이상이어야 합니다.")
        with self.db.transaction() as conn:
            entity = _entity_row(conn, entity_id)
            other = conn.execute(
                """SELECT e.id, e.name FROM graph_alias a JOIN graph_entity e ON e.id = a.entity_id
                   WHERE a.alias_norm = ? AND e.type = ? AND e.id != ? LIMIT 1""",
                (norm, entity["type"], entity_id),
            ).fetchone()
            if other is not None:
                raise GraphEditError(f"같은 종류에 '{other['name']}' 개체가 이미 그 이름을 씁니다. 합치기를 사용하세요.")
            conn.execute("UPDATE graph_entity SET name = ?, norm = ? WHERE id = ?", (name, norm, entity_id))
            conn.execute(
                "INSERT OR IGNORE INTO graph_alias (entity_id, alias, alias_norm) VALUES (?, ?, ?)", (entity_id, name, norm)
            )
        return self.get_entity(entity_id)

    def merge_entities(self, source_id: int, target_id: int) -> dict:
        """source 개체를 target에 합친다. 별칭·등장 위치·관계를 target으로 옮기고 source는 지운다.

        source의 이름이 target의 별칭이 되므로, 같은 종류면 다시 뽑아도 target으로 묶인다.
        """
        if source_id == target_id:
            raise GraphEditError("같은 개체끼리는 합칠 수 없습니다.")
        with self.db.transaction() as conn:
            source = _entity_row(conn, source_id)
            target = _entity_row(conn, target_id)
            if source["type"] == "concept" and target["type"] != "concept":
                raise GraphEditError("상위 개념은 상위 개념끼리만 합칠 수 있습니다.")
            conn.execute(
                """INSERT OR IGNORE INTO graph_alias (entity_id, alias, alias_norm)
                   SELECT ?, alias, alias_norm FROM graph_alias WHERE entity_id = ?""",
                (target_id, source_id),
            )
            conn.execute(
                """INSERT OR IGNORE INTO graph_mention (entity_id, file_id, page)
                   SELECT ?, file_id, page FROM graph_mention WHERE entity_id = ?""",
                (target_id, source_id),
            )
            # 관계는 끝점을 target으로 바꿔 복사한다. 합친 뒤 자기 자신을 가리키게 되는 관계는 버린다
            conn.execute(
                """INSERT OR IGNORE INTO graph_relation (src_id, dst_id, type, file_id, page, origin, is_option, created_at)
                   SELECT CASE WHEN src_id = :s THEN :t ELSE src_id END,
                          CASE WHEN dst_id = :s THEN :t ELSE dst_id END,
                          type, file_id, page, origin, is_option, created_at
                   FROM graph_relation
                   WHERE (src_id = :s OR dst_id = :s)
                     AND (CASE WHEN src_id = :s THEN :t ELSE src_id END) != (CASE WHEN dst_id = :s THEN :t ELSE dst_id END)""",
                {"s": source_id, "t": target_id},
            )
            # 사양 DB 대상 표시는 target에 없을 때만 옮긴다 (target이 이미 다른 대상을 가리키면 그대로 둔다)
            conn.execute(
                """UPDATE graph_entity SET ref_type = (SELECT ref_type FROM graph_entity WHERE id = :s),
                                           ref_id = (SELECT ref_id FROM graph_entity WHERE id = :s)
                   WHERE id = :t AND ref_id IS NULL""",
                {"s": source_id, "t": target_id},
            )
            conn.execute("DELETE FROM graph_entity WHERE id = ?", (source_id,))  # 별칭·등장·관계는 외래키로 같이 지워진다
            _prune_orphans(conn)
        return self.get_entity(target_id)

    # ------------------------------------------------------------ 검색

    def find_entities(self, query: str, limit: int = 20) -> list[dict]:
        """검색어에 들어 있는 개체를 찾는다.

        - 개체 표기(이름·별칭)가 검색어 안에 들어 있으면 찾는다: "KC인증 자료 보내줘" -> KC 인증
        - 검색어의 단어(3자 이상)로 시작하는 개체 표기도 찾되, 그 단어가 표기의 한 어절과 정확히 같을 때만 쓴다:
          "N5800" -> "N5800 14세대" (어절 "N5800"), "N5800-GB70-PU02"는 한 어절이라 제외.
          (중간 일치는 "R-R-TGE-N5800"처럼 다른 개체까지 잡아서 쓰지 않는다)
        - 어절 끝 조사 하나를 뗀 것도 검색어 단어로 쓴다: "N5800의 사양" -> "N5800"
        """
        query_norm = normalize(query)
        if len(query_norm) < MIN_NORM_LEN:
            return []
        tokens = _query_tokens(query)

        conditions = ["(length(a.alias_norm) >= ? AND instr(?, a.alias_norm) > 0)"]
        params: list = [MIN_NORM_LEN, query_norm]
        for token in tokens:
            conditions.append("a.alias_norm LIKE ?")
            params.append(f"{token}%")
        # SQL은 후보를 넉넉히 뽑고(별칭 원문 포함), 접두 일치는 아래에서 어절 단위로 다시 거른다
        sql = f"""
            SELECT e.id, e.type, e.name, a.alias, a.alias_norm
            FROM graph_alias a JOIN graph_entity e ON e.id = a.entity_id
            WHERE {' OR '.join(conditions)}
        """
        with self.db.get_conn() as conn:
            rows = conn.execute(sql, params).fetchall()

        token_set = set(tokens)
        best: dict[int, tuple[int, sqlite3.Row]] = {}
        for row in rows:
            alias_norm = row["alias_norm"]
            contained = len(alias_norm) >= MIN_NORM_LEN and alias_norm in query_norm
            if not contained:
                alias_words = {normalize(word) for word in row["alias"].split()}
                if not token_set & alias_words:
                    continue
            match_len = len(alias_norm)
            if row["id"] not in best or match_len > best[row["id"]][0]:
                best[row["id"]] = (match_len, row)
        ranked = sorted(best.values(), key=lambda item: (-item[0], item[1]["id"]))
        return [{"id": r["id"], "type": r["type"], "name": r["name"]} for _, r in ranked[:limit]]

    def concept_members(self, concept_ids: list[int]) -> list[dict]:
        """상위 개념에 속한 인증 종류 (part_of의 src)."""
        if not concept_ids:
            return []
        marks = ",".join("?" * len(concept_ids))
        with self.db.get_conn() as conn:
            rows = conn.execute(
                f"""SELECT DISTINCT e.id, e.type, e.name, r.dst_id AS concept_id
                    FROM graph_relation r JOIN graph_entity e ON e.id = r.src_id
                    WHERE r.type = 'part_of' AND r.dst_id IN ({marks})
                    ORDER BY e.id""",
                concept_ids,
            ).fetchall()
            return [dict(r) for r in rows]

    def relations_of(self, entity_ids: list[int], group_id: str | None = None, limit: int = 40) -> list[dict]:
        """개체에 붙은 관계 (양방향). part_of는 concept_members()가 따로 다룬다.

        group_id를 주면 그 그룹 문서를 근거로 한 관계와 근거 문서 없이 사람이 넣은 관계만 본다.
        """
        if not entity_ids:
            return []
        marks = ",".join("?" * len(entity_ids))
        group_sql = "AND (f.group_id = ? OR r.file_id IS NULL)" if group_id else ""
        params: list = [*entity_ids, *entity_ids]
        if group_id:
            params.append(group_id)
        with self.db.get_conn() as conn:
            rows = conn.execute(
                f"""SELECT {_RELATION_COLUMNS} {_RELATION_JOINS}
                    WHERE r.type != 'part_of' AND (r.src_id IN ({marks}) OR r.dst_id IN ({marks})) {group_sql}
                    ORDER BY r.id
                    LIMIT ?""",
                (*params, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def mentions_of(self, entity_ids: list[int], group_id: str | None = None) -> list[dict]:
        """개체가 나온 페이지와 그 파일 정보."""
        if not entity_ids:
            return []
        marks = ",".join("?" * len(entity_ids))
        group_sql = "AND f.group_id = ?" if group_id else ""
        params: list = list(entity_ids)
        if group_id:
            params.append(group_id)
        with self.db.get_conn() as conn:
            rows = conn.execute(
                f"""SELECT m.entity_id, e.name AS entity_name, m.file_id, m.page,
                           f.original_name, f.stored_path, f.group_id
                    FROM graph_mention m
                    JOIN graph_entity e ON e.id = m.entity_id
                    JOIN file f ON f.file_id = m.file_id
                    WHERE m.entity_id IN ({marks}) {group_sql}
                    ORDER BY f.original_name, m.page""",
                params,
            ).fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------ 화면·프롬프트용 조회

    def list_concepts(self) -> list[dict]:
        """상위 개념과 그에 속한 인증 종류 이름. 시스템 프롬프트 힌트에 쓴다."""
        with self.db.get_conn() as conn:
            rows = conn.execute(
                """SELECT DISTINCT c.id AS concept_id, c.name AS concept, e.id AS member_id, e.name AS member
                   FROM graph_entity c
                   JOIN graph_relation r ON r.dst_id = c.id AND r.type = 'part_of'
                   JOIN graph_entity e ON e.id = r.src_id
                   WHERE c.type = 'concept'
                   ORDER BY c.id, e.id"""
            ).fetchall()
        concepts: dict[str, list[str]] = {}
        for row in rows:
            concepts.setdefault(row["concept"], []).append(row["member"])
        return [{"name": name, "members": members} for name, members in concepts.items()]

    def list_entities(self, entity_type: str | None = None, q: str | None = None, limit: int = 100, offset: int = 0) -> list[dict]:
        conditions, params = [], []
        if entity_type:
            conditions.append("e.type = ?")
            params.append(entity_type)
        if q and normalize(q):
            conditions.append("e.id IN (SELECT entity_id FROM graph_alias WHERE alias_norm LIKE ?)")
            params.append(f"%{normalize(q)}%")
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        with self.db.get_conn() as conn:
            rows = conn.execute(
                f"""SELECT e.id, e.type, e.name,
                           (SELECT count(*) FROM graph_mention m WHERE m.entity_id = e.id) AS mention_count,
                           (SELECT count(*) FROM graph_relation r WHERE r.src_id = e.id OR r.dst_id = e.id) AS relation_count
                    FROM graph_entity e {where}
                    ORDER BY e.type, e.name
                    LIMIT ? OFFSET ?""",
                (*params, limit, offset),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_entity(self, entity_id: int) -> dict | None:
        """개체 하나의 별칭, 모든 관계(상위 개념 포함, 출처·id 포함), 나온 문서 페이지."""
        with self.db.get_conn() as conn:
            row = conn.execute("SELECT id, type, name FROM graph_entity WHERE id = ?", (entity_id,)).fetchone()
            if row is None:
                return None
            aliases = [r["alias"] for r in conn.execute(
                "SELECT alias FROM graph_alias WHERE entity_id = ? ORDER BY alias", (entity_id,)
            )]
            relations = [dict(r) for r in conn.execute(
                f"""SELECT {_RELATION_COLUMNS} {_RELATION_JOINS}
                    WHERE r.src_id = ? OR r.dst_id = ?
                    ORDER BY r.type, s.name, d.name, r.id""",
                (entity_id, entity_id),
            )]
        entity = dict(row)
        entity["aliases"] = aliases
        entity["relations"] = relations
        entity["mentions"] = [
            {k: m[k] for k in ("file_id", "page", "original_name")} for m in self.mentions_of([entity_id])
        ]
        return entity

    def view(
        self,
        entity_id: int | None = None,
        depth: int = 1,
        types: list[str] | None = None,
        file_id: str | None = None,
        limit: int = 150,
    ) -> dict:
        """그래프 화면용 노드·엣지.

        - entity_id가 있으면 그 개체에서 depth 단계까지 이어진 개체 (중심 개체는 종류 필터와 상관없이 넣는다)
        - 없으면 관계가 많은 개체부터 limit개. file_id를 주면 그 문서에 나오거나 그 문서를 근거로 한 개체만
        엣지는 고른 노드끼리의 관계만 돌려준다.
        """
        type_set = set(types or []) or None
        with self.db.get_conn() as conn:
            truncated = False
            if entity_id is not None:
                _entity_row(conn, entity_id)
                ids: list[int] = [entity_id]
                seen = {entity_id}
                frontier = [entity_id]
                for _ in range(max(1, depth)):
                    if not frontier or len(ids) >= limit:
                        break
                    marks = ",".join("?" * len(frontier))
                    rows = conn.execute(
                        f"""SELECT r.src_id, r.dst_id, s.type AS src_type, d.type AS dst_type
                            FROM graph_relation r
                            JOIN graph_entity s ON s.id = r.src_id JOIN graph_entity d ON d.id = r.dst_id
                            WHERE r.src_id IN ({marks}) OR r.dst_id IN ({marks})
                            ORDER BY r.id""",
                        (*frontier, *frontier),
                    ).fetchall()
                    next_frontier = []
                    for row in rows:
                        for other, other_type in ((row["src_id"], row["src_type"]), (row["dst_id"], row["dst_type"])):
                            if other in seen or (type_set and other_type not in type_set):
                                continue
                            if len(ids) >= limit:
                                truncated = True
                                break
                            seen.add(other)
                            ids.append(other)
                            next_frontier.append(other)
                    frontier = next_frontier
            else:
                conditions, params = [], []
                if type_set:
                    conditions.append(f"e.type IN ({','.join('?' * len(type_set))})")
                    params.extend(sorted(type_set))
                if file_id:
                    conditions.append(
                        """(e.id IN (SELECT entity_id FROM graph_mention WHERE file_id = ?)
                            OR e.id IN (SELECT src_id FROM graph_relation WHERE file_id = ?)
                            OR e.id IN (SELECT dst_id FROM graph_relation WHERE file_id = ?))"""
                    )
                    params.extend([file_id] * 3)
                where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
                rows = conn.execute(
                    f"""SELECT e.id,
                               (SELECT count(*) FROM graph_relation r WHERE r.src_id = e.id OR r.dst_id = e.id) AS degree,
                               (SELECT count(*) FROM graph_mention m WHERE m.entity_id = e.id) AS mentions
                        FROM graph_entity e {where}
                        ORDER BY degree DESC, mentions DESC, e.id
                        LIMIT ?""",
                    (*params, limit + 1),
                ).fetchall()
                truncated = len(rows) > limit
                ids = [r["id"] for r in rows[:limit]]

            if not ids:
                return {"nodes": [], "edges": [], "truncated": False}
            marks = ",".join("?" * len(ids))
            nodes = [dict(r) for r in conn.execute(
                f"""SELECT e.id, e.type, e.name,
                           (SELECT count(*) FROM graph_mention m WHERE m.entity_id = e.id) AS mention_count,
                           (SELECT count(*) FROM graph_relation r WHERE r.src_id = e.id OR r.dst_id = e.id) AS degree
                    FROM graph_entity e WHERE e.id IN ({marks})""",
                ids,
            )]
            edges = [dict(r) for r in conn.execute(
                f"""SELECT r.id, r.src_id AS source, r.dst_id AS target, r.type, r.origin, r.file_id, r.page, f.original_name
                    FROM graph_relation r LEFT JOIN file f ON f.file_id = r.file_id
                    WHERE r.src_id IN ({marks}) AND r.dst_id IN ({marks})
                    ORDER BY r.id""",
                (*ids, *ids),
            )]
        return {"nodes": nodes, "edges": edges, "truncated": truncated}

    def stats(self) -> dict:
        with self.db.get_conn() as conn:
            by_type = {r["type"]: r["n"] for r in conn.execute(
                "SELECT type, count(*) AS n FROM graph_entity GROUP BY type ORDER BY type"
            )}
            relations = conn.execute("SELECT count(*) FROM graph_relation").fetchone()[0]
            by_origin = {r["origin"]: r["n"] for r in conn.execute(
                "SELECT origin, count(*) AS n FROM graph_relation GROUP BY origin ORDER BY origin"
            )}
            files = conn.execute("SELECT count(DISTINCT file_id) FROM graph_mention").fetchone()[0]
            blocked = conn.execute("SELECT count(*) FROM graph_relation_block").fetchone()[0]
        return {"entities": by_type, "relations": relations, "relations_by_origin": by_origin,
                "blocked_relations": blocked, "indexed_files": files}


# ------------------------------------------------------------ 내부 함수

def _entity_row(conn: sqlite3.Connection, entity_id: int | None) -> sqlite3.Row:
    row = None if entity_id is None else conn.execute(
        "SELECT id, type, name, norm FROM graph_entity WHERE id = ?", (entity_id,)
    ).fetchone()
    if row is None:
        raise GraphNotFoundError("개체를 찾을 수 없습니다.")
    return row


def _relation(conn: sqlite3.Connection, relation_id: int) -> dict:
    row = conn.execute(f"SELECT {_RELATION_COLUMNS} {_RELATION_JOINS} WHERE r.id = ?", (relation_id,)).fetchone()
    if row is None:
        raise GraphNotFoundError("관계를 찾을 수 없습니다.")
    return dict(row)


def _block_key(conn: sqlite3.Connection, src_id: int, dst_id: int, rel_type: str) -> tuple | None:
    src = conn.execute("SELECT type, norm FROM graph_entity WHERE id = ?", (src_id,)).fetchone()
    dst = conn.execute("SELECT type, norm FROM graph_entity WHERE id = ?", (dst_id,)).fetchone()
    if src is None or dst is None:
        return None
    return src["type"], src["norm"], rel_type, dst["type"], dst["norm"]


def _is_blocked(conn: sqlite3.Connection, src_id: int, dst_id: int, rel_type: str) -> bool:
    key = _block_key(conn, src_id, dst_id, rel_type)
    return key is not None and conn.execute(
        """SELECT 1 FROM graph_relation_block
           WHERE src_type = ? AND src_norm = ? AND type = ? AND dst_type = ? AND dst_norm = ?""",
        key,
    ).fetchone() is not None


def _block(conn: sqlite3.Connection, src_id: int, dst_id: int, rel_type: str) -> None:
    key = _block_key(conn, src_id, dst_id, rel_type)
    if key is not None:
        conn.execute(
            "INSERT OR IGNORE INTO graph_relation_block (src_type, src_norm, type, dst_type, dst_norm) VALUES (?, ?, ?, ?, ?)",
            key,
        )


def _unblock(conn: sqlite3.Connection, source: sqlite3.Row, target: sqlite3.Row, rel_type: str) -> None:
    conn.execute(
        """DELETE FROM graph_relation_block
           WHERE src_type = ? AND src_norm = ? AND type = ? AND dst_type = ? AND dst_norm = ?""",
        (source["type"], source["norm"], rel_type, target["type"], target["norm"]),
    )


def _upsert_entity(conn: sqlite3.Connection, entity_type: str, name: str) -> int | None:
    """같은 종류에 같은 표기(이름 또는 별칭)의 개체가 있으면 그 id를, 없으면 새로 만들어 id를 돌려준다."""
    name = (name or "").strip()
    norm = normalize(name)
    if len(norm) < MIN_NORM_LEN:
        return None
    row = conn.execute(
        """SELECT e.id FROM graph_alias a JOIN graph_entity e ON e.id = a.entity_id
           WHERE a.alias_norm = ? AND e.type = ? ORDER BY e.id LIMIT 1""",
        (norm, entity_type),
    ).fetchone()
    if row is not None:
        return row[0]
    conn.execute("INSERT OR IGNORE INTO graph_entity (type, name, norm) VALUES (?, ?, ?)", (entity_type, name, norm))
    entity_id = conn.execute(
        "SELECT id FROM graph_entity WHERE type = ? AND norm = ?", (entity_type, norm)
    ).fetchone()[0]
    conn.execute(
        "INSERT OR IGNORE INTO graph_alias (entity_id, alias, alias_norm) VALUES (?, ?, ?)",
        (entity_id, name, norm),
    )
    return entity_id


def _add_alias(conn: sqlite3.Connection, entity_id: int, alias: str) -> None:
    alias = (alias or "").strip()
    alias_norm = normalize(alias)
    if len(alias_norm) >= MIN_NORM_LEN:
        conn.execute(
            "INSERT OR IGNORE INTO graph_alias (entity_id, alias, alias_norm) VALUES (?, ?, ?)", (entity_id, alias, alias_norm)
        )


def _link_spec_entity(conn: sqlite3.Connection, entity_type: str, name: str, ref_type: str, ref_id: str) -> int | None:
    """사양 DB 대상 하나를 가리키는 개체 id. 그 대상을 이미 가리키는 개체 → 같은 이름의 개체 → 새 개체 순서로 찾는다.

    모델명이 바뀌었으면 새 모델명을 별칭으로 더한다. 같은 이름의 개체가 이미 다른 대상을 가리키면 바꾸지 않는다.
    """
    row = conn.execute(
        "SELECT id FROM graph_entity WHERE type = ? AND ref_type = ? AND ref_id = ? ORDER BY id LIMIT 1",
        (entity_type, ref_type, ref_id),
    ).fetchone()
    if row is not None:
        _add_alias(conn, row[0], name)
        return row[0]
    entity_id = _upsert_entity(conn, entity_type, name)
    if entity_id is None:
        return None
    conn.execute(
        "UPDATE graph_entity SET ref_type = ?, ref_id = ? WHERE id = ? AND ref_id IS NULL", (ref_type, ref_id, entity_id)
    )
    return entity_id


def _prune_orphans(conn: sqlite3.Connection) -> int:
    """어느 페이지에도 안 나오고 관계도 없는 개체를 지운다. 상위 개념(concept)과 사양 DB 대상을 가리키는 개체(ref_id)는 남긴다."""
    cur = conn.execute(
        """DELETE FROM graph_entity
           WHERE type != 'concept'
             AND ref_id IS NULL
             AND NOT EXISTS (SELECT 1 FROM graph_mention m WHERE m.entity_id = graph_entity.id)
             AND NOT EXISTS (SELECT 1 FROM graph_relation r
                             WHERE r.src_id = graph_entity.id OR r.dst_id = graph_entity.id)"""
    )
    return cur.rowcount
