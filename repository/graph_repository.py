"""문서 그래프 저장소 (graph_entity, graph_alias, graph_mention, graph_relation, graph_relation_block 테이블).

문서에서 뽑은 개체·관계는 (file_id, page) 단위로 통째로 갈아끼운다. 페이지 검수로 텍스트가 바뀌면
그 페이지만 다시 뽑아 replace_page()를 부른다. 어느 페이지에도 안 나오고 관계도 없는 개체는 치운다.

관계의 출처(origin)
- extract: 문서에서 뽑음. 그 페이지를 다시 뽑으면 갈아끼운다.
- spec: 사양 DB에서 심음. 서버 시작·사양 변경 때 다시 넣는다.
- manual: 그래프 화면에서 사람이 넣음. 다시 뽑아도 유지한다.
사람이 화면에서 지운 관계는 graph_relation_block에 남겨 다시 뽑아도 되살리지 않는다.
"""
from __future__ import annotations

import logging
import re
import sqlite3

from graph_rag.rules import DEFAULT_VENDOR_PREFIXES, spec_match_keys
from graph_rag.types import PageGraph, normalize
from repository.repo_connect import Database

logger = logging.getLogger(__name__)

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


_RELATION_COLUMNS = """r.id, r.revision, r.source_key, r.lifecycle_state, r.type, r.origin, r.is_option, r.page, r.file_id, f.original_name,
                       s.id AS source_id, s.type AS source_type, s.name AS source_name,
                       d.id AS target_id, d.type AS target_type, d.name AS target_name"""
_RELATION_JOINS = """FROM effective_graph_relation r
                     JOIN effective_graph_entity s ON s.id = r.src_id
                     JOIN effective_graph_entity d ON d.id = r.dst_id
                     LEFT JOIN file f ON f.file_id = r.file_id"""


class GraphNotFoundError(LookupError):
    """없는 개체·관계"""


class GraphEditError(ValueError):
    """그래프 편집 요청이 규칙에 맞지 않음 (화면에 그대로 보여줄 메시지)"""


class GraphRepository:

    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------ 추출 결과 쓰기

    def project_specs(self) -> dict:
        """사양 DB를 그래프로 투영한다 (지시서 GR4, repository/graph_projection.py). 한 트랜잭션.

        서버 시작과 사양 저장 API 전부가 부른다. spec 관계만 지우고 다시 넣는다. 요약을 돌려주고 로그에 남긴다.
        """
        import config
        from repository.graph_projection import project_specs

        with self.db.transaction() as conn:
            summary = project_specs(conn, config.GRAPH_VENDOR_PREFIXES)
            _prune_orphans(conn)
        logger.info("사양 DB 그래프 투영: %s", summary)
        if summary["seconds"] > 2:
            logger.warning("사양 DB 그래프 투영이 %.1f초 걸렸습니다", summary["seconds"])
        return summary

    def extraction_schema(self):
        """그때의 개체·관계 종류 (지시서 GR2). 문서 추출 형식과 프롬프트를 만든다."""
        from graph_rag.schema import load_schema
        with self.db.get_conn() as conn:
            return load_schema(conn)

    def entity_type_keys(self) -> list[str]:
        with self.db.get_conn() as conn:
            return [r[0] for r in conn.execute("SELECT key FROM graph_entity_type ORDER BY sort_order, key")]

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

    def replace_page(self, file_id: str, page: int, graph: PageGraph, link_specs: bool = False) -> dict:
        """한 페이지에서 뽑은 개체·관계로 그 페이지의 그래프를 갈아끼운다. 사람이 넣은 관계는 그대로 둔다.

        저장 전에 validate_page_graph로 거른다 (지시서 GR3-3, 문서 추출에만). 버린 수를 사유별로 dropped에 싣는다.
        link_specs: 제품·부품 개체의 이름(또는 별칭)이 사양 DB의 모델명과 같으면 ref_type·ref_id를 단다 (지시서 H3).
        이름 비교는 정식 이름 맞춤 키(GR3-4)로 한다.
        """
        import config
        from graph_rag.schema import load_schema
        from graph_rag.validate import validate_page_graph

        with self.db.transaction() as conn:
            vendors = config.GRAPH_VENDOR_PREFIXES
            spec_index = _spec_node_index(conn, vendors)
            graph, dropped = validate_page_graph(graph, load_schema(conn), spec_index, vendors)
            spec_refs = _spec_ref_map(conn, vendors) if link_specs else {}
            conn.execute("DELETE FROM graph_mention WHERE file_id = ? AND page = ?", (file_id, page))
            conn.execute(
                "DELETE FROM graph_relation WHERE file_id = ? AND page = ? AND origin = 'extract'", (file_id, page)
            )

            ids_by_norm: dict[str, int] = {}
            entity_ids: set[int] = set()
            pending: list[tuple[int, int, str]] = []  # (src, dst, type)
            for entity in graph.entities:
                entity_id = spec_index.attached.get((entity.type, normalize(entity.name))) \
                    or _upsert_entity(conn, entity.type, entity.name)
                if entity_id is None:
                    continue
                entity_ids.add(entity_id)
                ids_by_norm.setdefault(normalize(entity.name), entity_id)
                ref_type = _SPEC_REF_TYPES.get(entity.type)
                if spec_refs and ref_type:
                    ref = next((spec_refs[(ref_type, key)] for n in [entity.name, *entity.aliases]
                                for key in spec_match_keys(n, vendors) if (ref_type, key) in spec_refs), None)
                    if ref is not None:
                        conn.execute("UPDATE graph_entity SET ref_type = ?, ref_id = ? WHERE id = ? AND ref_id IS NULL",
                                     (ref_type, ref, entity_id))
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
        return {"entities": len(entity_ids), "relations": relations, "dropped": dropped}

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

    def _edit(self, command, identity=None, data=None):
        from graph_rag.edit_service import GraphEditService
        return GraphEditService(self.db).execute(command, identity, data)

    def add_relation(self, source_id, rel_type, target_id=None, new_target=None, file_id=None, page=None):
        return self._edit('create_relation', data={
            'source_id': source_id, 'type': rel_type, 'target_id': target_id,
            'new_target': {'type':new_target[0], 'name':new_target[1]} if new_target else None,
            'file_id': file_id, 'page': page,
        })

    def delete_relation(self, relation_id):
        with self.db.get_conn() as conn:
            row = conn.execute('SELECT revision FROM graph_relation WHERE id=?',(relation_id,)).fetchone()
        if row is None:
            raise GraphNotFoundError('관계를 찾을 수 없습니다.')
        self._edit('delete_relation', relation_id, {'expected_revision':row[0]})
        return 1

    def update_relation(self, relation_id, rel_type=None, reverse=False):
        with self.db.get_conn() as conn:
            row = conn.execute('SELECT revision FROM graph_relation WHERE id=?',(relation_id,)).fetchone()
        if row is None:
            raise GraphNotFoundError('관계를 찾을 수 없습니다.')
        return self._edit('update_relation', relation_id, {'type':rel_type,'reverse':reverse,'expected_revision':row[0]})

    def rename_entity(self, entity_id, name):
        entity = self.get_entity(entity_id)
        if entity is None:
            raise GraphNotFoundError('객체를 찾을 수 없습니다.')
        self._edit('update_entity', entity_id, {'name':name,'expected_revision':entity['revision']})
        return self.get_entity(entity_id)

    def merge_entities(self, source_id, target_id):
        source,target = self.get_entity(source_id),self.get_entity(target_id)
        if source is None or target is None:
            raise GraphNotFoundError('객체를 찾을 수 없습니다.')
        self._edit('merge_entity',source_id,{'target_id':target_id,'expected_revision':source['revision'],'target_revision':target['revision']})
        return self.get_entity(target_id)

    # ------------------------------------------------------------ 검색

    def find_entities(self, query: str, limit: int = 20) -> list[dict]:
        """검색어에 들어 있는 개체를 찾는다.

        - 개체 표기(이름·별칭)가 검색어 안에 들어 있으면 찾는다: "KC인증 자료 보내줘" -> KC 인증
        - 검색어의 단어(3자 이상)로 시작하는 개체 표기도 찾되, 그 단어가 표기의 한 어절과 정확히 같을 때만 쓴다:
          "N5800" -> "N5800 14세대" (어절 "N5800"), "N5800-GB70-PU02"는 한 어절이라 제외.
          (중간 일치는 "R-R-TGE-N5800"처럼 다른 개체까지 잡아서 쓰지 않는다)
        - 어절 끝 조사 하나를 뗀 것도 검색어 단어로 쓴다: "N5800의 사양" -> "N5800"
        - 다른 개체의 더 긴 표기 안에만 들어 있는 개체는 뺀다:
          "N5800-GB70-PU02 인증"에서 N5800은 질문에 따로 나오지 않았다. "N5800과 N5800-GB70-PU02"면 둘 다 찾는다.
        반환 항목: {id, type, name, ref_type, ref_id} (ref는 사양 DB 대상. 없으면 None)
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
            SELECT e.id, e.type, e.name, e.ref_type, e.ref_id, a.alias, a.alias_norm
            FROM graph_alias a JOIN effective_graph_entity e ON e.id = a.entity_id
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
        contained = {
            entity_id: row["alias_norm"] for entity_id, (_, row) in best.items()
            if row["alias_norm"] in query_norm
        }
        for entity_id, alias in contained.items():
            longer = [a for other, a in contained.items() if other != entity_id and len(a) > len(alias) and alias in a]
            if not longer:
                continue
            rest = query_norm
            for other_alias in sorted(longer, key=len, reverse=True):
                rest = rest.replace(other_alias, "\x00")
            if alias not in rest:
                best.pop(entity_id, None)
        _keep_matching_value_nodes(self.db, best, query_norm)
        ranked = sorted(best.values(), key=lambda item: (-item[0], item[1]["id"]))
        result = [{"id": r["id"], "type": r["type"], "name": r["name"], "ref_type": r["ref_type"], "ref_id": r["ref_id"]}
                  for _, r in ranked[:limit]]
        if len(result)<limit:
            with self.db.get_conn() as conn:
                extra = conn.execute("""SELECT DISTINCT e.id,e.type,e.name,e.ref_type,e.ref_id
                  FROM effective_graph_entity e JOIN graph_property_value v ON v.entity_id=e.id
                  JOIN graph_property_definition d USING(property_id)
                  WHERE v.lifecycle_state='active' AND
                  (instr(lower(coalesce(v.value_text,'')),lower(?))>0 OR instr(lower(d.label),lower(?))>0
                   OR instr(lower(?),lower(d.label))>0) ORDER BY e.id LIMIT ?""",(query,query,query,limit)).fetchall()
                known={e['id'] for e in result}
                result.extend(dict(r) for r in extra if r['id'] not in known)
        return result[:limit]

    def find_entities_by_norms(self, norms: list[str], entity_type: str | None = None, limit: int = 20) -> list[dict]:
        """표기(비교용 키)가 정확히 같은 개체. 용어집이 찾은 용어의 표기로 그래프를 찾을 때 쓴다 (graph_rag/service.py).

        entity_type을 주면 그 종류의 개체만. 반환 항목은 find_entities와 같다.
        """
        norms = [n for n in dict.fromkeys(norms) if n]
        if not norms:
            return []
        marks = ",".join("?" * len(norms))
        sql = f"""SELECT DISTINCT e.id, e.type, e.name, e.ref_type, e.ref_id
                  FROM graph_alias a JOIN effective_graph_entity e ON e.id = a.entity_id
                  WHERE a.alias_norm IN ({marks})"""
        params: list = list(norms)
        if entity_type:
            sql += " AND e.type = ?"
            params.append(entity_type)
        sql += " ORDER BY e.id LIMIT ?"
        params.append(limit)
        with self.db.get_conn() as conn:
            return [dict(r) for r in conn.execute(sql, params)]

    def parents_of(self, entity_ids: list[int]) -> list[dict]:
        """파생 모델 → 상위 모델 (variant_of). [{child_id, parent_id, parent_name, ref_type, ref_id}]"""
        if not entity_ids:
            return []
        marks = ",".join("?" * len(entity_ids))
        with self.db.get_conn() as conn:
            rows = conn.execute(
                f"""SELECT DISTINCT r.src_id AS child_id, p.id AS parent_id, p.name AS parent_name, p.ref_type, p.ref_id
                    FROM effective_graph_relation r JOIN effective_graph_entity p ON p.id = r.dst_id
                    WHERE r.type = 'variant_of' AND r.src_id IN ({marks})
                    ORDER BY p.name""",
                entity_ids,
            ).fetchall()
            return [dict(r) for r in rows]

    def relations_of(self, entity_ids: list[int], group_id: str | None = None, limit: int = 40,
                     exclude_types: tuple[str, ...] = ()) -> list[dict]:
        """개체에 붙은 관계 (양방향). exclude_types의 관계는 뺀다 (graph_search가 has_spec을 뺀다, GR4-9).

        group_id를 주면 그 그룹 문서를 근거로 한 관계와 근거 문서 없이 사람이 넣은 관계만 본다.
        """
        if not entity_ids:
            return []
        marks = ",".join("?" * len(entity_ids))
        group_sql = "AND (f.group_id = ? OR r.file_id IS NULL)" if group_id else ""
        params: list = [*entity_ids, *entity_ids]
        if group_id:
            params.append(group_id)
        if exclude_types:
            group_sql += f" AND r.type NOT IN ({','.join('?' * len(exclude_types))})"
            params.extend(exclude_types)
        with self.db.get_conn() as conn:
            rows = conn.execute(
                f"""SELECT {_RELATION_COLUMNS} {_RELATION_JOINS}
                    WHERE (r.src_id IN ({marks}) OR r.dst_id IN ({marks})) {group_sql}
                    ORDER BY r.id
                    LIMIT ?""",
                (*params, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def count_relations(self, entity_ids: list[int], rel_type: str) -> int:
        """개체에서 나가는 rel_type 관계 수 (graph_search의 spec_values 개수)."""
        if not entity_ids:
            return 0
        marks = ",".join("?" * len(entity_ids))
        with self.db.get_conn() as conn:
            return conn.execute(f"SELECT count(*) FROM effective_graph_relation WHERE type=? AND src_id IN ({marks})",
                                (rel_type, *entity_ids)).fetchone()[0]

    def hierarchy(self, entity_id: int) -> dict:
        """모델 계층 (GR4-2): 위로 가는 상위 경로(루트부터)와 바로 아래 하위 모델."""
        with self.db.get_conn() as conn:
            ancestors: list[dict] = []
            seen, current = {entity_id}, entity_id
            for _ in range(10):
                row = conn.execute("""SELECT p.id, p.name, p.type FROM effective_graph_relation r
                                      JOIN effective_graph_entity p ON p.id = r.dst_id
                                      WHERE r.type = 'variant_of' AND r.src_id = ? ORDER BY p.name LIMIT 1""",
                                   (current,)).fetchone()
                if row is None or row["id"] in seen:
                    break
                ancestors.insert(0, dict(row))
                seen.add(row["id"])
                current = row["id"]
            children = [dict(r) for r in conn.execute(
                """SELECT DISTINCT c.id, c.name, c.type FROM effective_graph_relation r
                   JOIN effective_graph_entity c ON c.id = r.src_id
                   WHERE r.type = 'variant_of' AND r.dst_id = ? ORDER BY c.name""", (entity_id,))]
        return {"ancestors": ancestors, "children": children}

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
                    JOIN effective_graph_entity e ON e.id = m.entity_id
                    JOIN file f ON f.file_id = m.file_id
                    WHERE m.entity_id IN ({marks}) {group_sql}
                    ORDER BY f.original_name, m.page""",
                params,
            ).fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------ 화면·프롬프트용 조회

    def list_entities(self, entity_type: str | None = None, q: str | None = None, limit: int = 100, offset: int = 0) -> list[dict]:
        conditions, params = [], []
        if entity_type:
            conditions.append("e.type = ?")
            params.append(entity_type)
        if q and normalize(q):
            conditions.append("""(e.id IN (SELECT entity_id FROM graph_alias WHERE alias_norm LIKE ?)
              OR e.id IN (SELECT v.entity_id FROM graph_property_value v JOIN graph_property_definition d USING(property_id)
              WHERE v.lifecycle_state='active' AND (v.value_text LIKE ? OR d.label LIKE ?)))""")
            params.append(f"%{normalize(q)}%")
            params.extend([f'%{q}%',f'%{q}%'])
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        with self.db.get_conn() as conn:
            rows = conn.execute(
                f"""SELECT e.id, e.type, e.name, e.revision,
                           (SELECT count(*) FROM graph_mention m WHERE m.entity_id = e.id) AS mention_count,
                           (SELECT count(*) FROM effective_graph_relation r WHERE r.src_id = e.id OR r.dst_id = e.id) AS relation_count
                    FROM effective_graph_entity e {where}
                    ORDER BY e.type, e.name
                    LIMIT ? OFFSET ?""",
                (*params, limit, offset),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_entity(self, entity_id: int) -> dict | None:
        """개체 하나의 별칭, 모든 관계(출처·id 포함), 나온 문서 페이지."""
        with self.db.get_conn() as conn:
            row = conn.execute("SELECT * FROM effective_graph_entity WHERE id = ?", (entity_id,)).fetchone()
            if row is None:
                return None
            aliases = [r["alias"] for r in conn.execute(
                "SELECT alias FROM graph_alias WHERE entity_id = ? AND hidden=0 ORDER BY alias", (entity_id,)
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
        entity["hierarchy"] = self.hierarchy(entity_id)
        if entity.get("ref_type") == "spec_attribute":
            with self.db.get_conn() as conn:
                attribute = conn.execute("SELECT key, name, unit, data_type, category FROM spec_attribute WHERE key = ?",
                                         (entity["ref_id"],)).fetchone()
                sample = conn.execute("""SELECT v.value_num FROM effective_graph_relation r
                    JOIN spec_value v ON 'spec:value:' || v.id = r.source_key
                    WHERE r.dst_id = ? AND r.type = 'has_spec' LIMIT 1""", (entity_id,)).fetchone()
            entity["spec_attribute"] = {**dict(attribute), "value_key": entity.get("ref_value"),
                                        "value_num": sample["value_num"] if sample else None} if attribute else None
        from graph_rag.edit_service import EffectiveGraphService
        service = EffectiveGraphService(self.db)
        entity['properties'] = service.properties(entity_id)
        entity['spec_diff'] = service.spec_diff(entity_id)
        with self.db.get_conn() as conn:
            for relation in entity['relations']:
                relation['sources'] = service.sources(conn, 'relation', relation['id'])
        return entity

    def view(
        self,
        entity_id: int | None = None,
        depth: int = 1,
        types: list[str] | None = None,
        file_id: str | None = None,
        limit: int = 150,
        spec_values: str = "neighbors",
        hide_isolated_spec: bool = True,
    ) -> dict:
        """그래프 화면용 노드·엣지.

        - entity_id가 있으면 그 개체에서 depth 단계까지 이어진 개체 (중심 개체는 종류 필터와 상관없이 넣는다)
        - 없으면 관계가 많은 개체부터 limit개. file_id를 주면 그 문서에 나오거나 그 문서를 근거로 한 개체만
        - spec_values='neighbors'(기본): 사양 값 노드는 고른 노드의 바로 이웃으로만 보이고 거기서 더 펼치지 않는다.
          전체 보기에는 넣지 않는다 (종류 필터로 사양 값을 고르면 넣는다). 'all'이면 다른 노드와 같다 (GR4-8)
        - hide_isolated_spec: 전체 보기에서 관계·등장 위치가 없는 사양 노드를 뺀다
        엣지는 고른 노드끼리의 관계만 돌려준다.
        """
        type_set = set(types or []) or None
        values_near = spec_values != "all"
        with self.db.get_conn() as conn:
            truncated = False
            if entity_id is not None:
                if conn.execute('SELECT 1 FROM effective_graph_entity WHERE id=?',(entity_id,)).fetchone() is None:
                    raise GraphNotFoundError('활성 객체를 찾을 수 없습니다.')
                ids: list[int] = [entity_id]
                seen = {entity_id}
                frontier = [entity_id]
                center_is_value = conn.execute("SELECT type FROM graph_entity WHERE id=?", (entity_id,)).fetchone()[0] == "spec_value"
                for step in range(max(1, depth)):
                    if not frontier or len(ids) >= limit:
                        break
                    marks = ",".join("?" * len(frontier))
                    rows = conn.execute(
                        f"""SELECT r.src_id, r.dst_id, s.type AS src_type, d.type AS dst_type
                            FROM effective_graph_relation r
                            JOIN effective_graph_entity s ON s.id = r.src_id JOIN effective_graph_entity d ON d.id = r.dst_id
                            WHERE r.src_id IN ({marks}) OR r.dst_id IN ({marks})
                            ORDER BY r.id""",
                        (*frontier, *frontier),
                    ).fetchall()
                    next_frontier = []
                    for row in rows:
                        for other, other_type in ((row["src_id"], row["src_type"]), (row["dst_id"], row["dst_type"])):
                            if other in seen or (type_set and other_type not in type_set):
                                continue
                            if values_near and other_type == "spec_value" and step > 0:
                                continue  # 사양 값 노드는 중심 개체의 바로 이웃으로만
                            if len(ids) >= limit:
                                truncated = True
                                break
                            seen.add(other)
                            ids.append(other)
                            if not (values_near and other_type == "spec_value") or center_is_value:
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
                            OR e.id IN (SELECT src_id FROM effective_graph_relation WHERE file_id = ?)
                            OR e.id IN (SELECT dst_id FROM effective_graph_relation WHERE file_id = ?))"""
                    )
                    params.extend([file_id] * 3)
                if values_near and not (type_set and "spec_value" in type_set):
                    conditions.append("e.type != 'spec_value'")
                if hide_isolated_spec:
                    conditions.append("""(e.ref_id IS NULL
                        OR EXISTS (SELECT 1 FROM effective_graph_relation r WHERE r.src_id = e.id OR r.dst_id = e.id)
                        OR EXISTS (SELECT 1 FROM graph_mention m WHERE m.entity_id = e.id))""")
                where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
                rows = conn.execute(
                    f"""SELECT e.id,
                               (SELECT count(*) FROM effective_graph_relation r WHERE r.src_id = e.id OR r.dst_id = e.id) AS degree,
                               (SELECT count(*) FROM graph_mention m WHERE m.entity_id = e.id) AS mentions
                        FROM effective_graph_entity e {where}
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
                f"""SELECT e.id, e.type, e.name, e.revision,
                           (SELECT count(*) FROM graph_mention m WHERE m.entity_id = e.id) AS mention_count,
                           (SELECT count(*) FROM effective_graph_relation r WHERE r.src_id = e.id OR r.dst_id = e.id) AS degree
                    FROM effective_graph_entity e WHERE e.id IN ({marks})""",
                ids,
            )]
            edges = [dict(r) for r in conn.execute(
                f"""SELECT r.id, r.revision, r.src_id AS source, r.dst_id AS target, r.type, r.origin, r.file_id, r.page, f.original_name
                    FROM effective_graph_relation r LEFT JOIN file f ON f.file_id = r.file_id
                    WHERE r.src_id IN ({marks}) AND r.dst_id IN ({marks})
                    ORDER BY r.id""",
                (*ids, *ids),
            )]
        return {"nodes": nodes, "edges": edges, "truncated": truncated}

    def stats(self) -> dict:
        with self.db.get_conn() as conn:
            by_type = {r["type"]: r["n"] for r in conn.execute(
                "SELECT type, count(*) AS n FROM effective_graph_entity GROUP BY type ORDER BY type"
            )}
            relations = conn.execute("SELECT count(*) FROM effective_graph_relation").fetchone()[0]
            by_origin = {r["origin"]: r["n"] for r in conn.execute(
                "SELECT origin, count(*) AS n FROM effective_graph_relation GROUP BY origin ORDER BY origin"
            )}
            files = conn.execute("SELECT count(DISTINCT file_id) FROM graph_mention").fetchone()[0]
            blocked = conn.execute("SELECT count(*) FROM (SELECT src_id,dst_id,type,source_key FROM graph_exclusion UNION SELECT -1,-1,type,src_norm || dst_norm FROM graph_relation_block WHERE NOT EXISTS (SELECT 1 FROM graph_exclusion x JOIN graph_entity s ON s.id=x.src_id JOIN graph_entity d ON d.id=x.dst_id WHERE s.norm=graph_relation_block.src_norm AND d.norm=graph_relation_block.dst_norm AND x.type=graph_relation_block.type))").fetchone()[0]
        return {"entities": by_type, "relations": relations, "relations_by_origin": by_origin,
                "blocked_relations": blocked, "indexed_files": files}


# ------------------------------------------------------------ 내부 함수

def _keep_matching_value_nodes(db, best: dict, query_norm: str) -> None:
    """사양 값 노드 후보는 값 표기와 속성 이름(한 어절 이상)이 질문에 있을 때만 남긴다 (GR4-9).

    "메모리 64GB" → "메모리 용량 64GB"는 남고 "메모리 용량 16GB"·"SSD 용량 64GB"는 빠진다.
    노드 이름 전체가 질문에 들어 있으면 그대로 남긴다.
    """
    value_ids = [entity_id for entity_id, (_, row) in best.items() if row["type"] == "spec_value"]
    if not value_ids:
        return
    marks = ",".join("?" * len(value_ids))
    with db.get_conn() as conn:
        info = {r["id"]: r for r in conn.execute(
            f"""SELECT e.id, e.ref_value, a.name AS attribute_name FROM graph_entity e
                LEFT JOIN spec_attribute a ON e.ref_type = 'spec_attribute' AND a.key = e.ref_id
                WHERE e.id IN ({marks})""", value_ids)}
    for entity_id in value_ids:
        _, row = best[entity_id]
        if row["alias_norm"] in query_norm:
            continue
        item = info.get(entity_id)
        words = [normalize(w) for w in re.split(r"[\s/()]+", (item["attribute_name"] or "") if item else "") if len(normalize(w)) >= 2]
        value = (item["ref_value"] or "") if item else ""
        if not (value and value in query_norm and any(w in query_norm for w in words)):
            best.pop(entity_id, None)


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
    if conn.execute("SELECT 1 FROM graph_exclusion WHERE src_id=? AND dst_id=? AND type=? AND source_key='*'", (src_id,dst_id,rel_type)).fetchone():
        return True
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


def _upsert_entity(conn: sqlite3.Connection, entity_type: str, name: str, creation_origin: str = 'extract') -> int | None:
    """같은 종류에 같은 표기(이름 또는 별칭)의 개체가 있으면 그 id를, 없으면 새로 만들어 id를 돌려준다."""
    name = (name or "").strip()
    norm = normalize(name)
    if len(norm) < MIN_NORM_LEN:
        return None
    row = conn.execute(
        """SELECT e.id, e.merged_into_id FROM graph_alias a JOIN graph_entity e ON e.id = a.entity_id
           WHERE a.alias_norm = ? AND e.type = ? ORDER BY e.id LIMIT 1""",
        (norm, entity_type),
    ).fetchone()
    if row is not None:
        identity = row[0]
        while row['merged_into_id'] is not None:
            identity = row['merged_into_id']
            row = conn.execute('SELECT id,merged_into_id FROM graph_entity WHERE id=?',(identity,)).fetchone()
        return identity
    conn.execute("INSERT OR IGNORE INTO graph_entity (type, name, norm, creation_origin) VALUES (?, ?, ?, ?)", (entity_type, name, norm, creation_origin))
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


# 개체 종류 → 사양 DB 참조 종류 (제품군도 product 테이블의 행이다)
_SPEC_REF_TYPES = {"product": "product", "product_line": "product", "component": "component"}


def _spec_ref_map(conn: sqlite3.Connection, vendors=DEFAULT_VENDOR_PREFIXES) -> dict[tuple[str, str], str]:
    """{(참조 종류, 정식 이름 맞춤 키): 사양 DB id}. 키가 겹치면 먼저 나온 것."""
    refs: dict[tuple[str, str], str] = {}
    for row in conn.execute("SELECT id, model FROM product ORDER BY model"):
        for key in spec_match_keys(row["model"], vendors):
            refs.setdefault(("product", key), row["id"])
    for row in conn.execute("SELECT id, model FROM component ORDER BY kind, model"):
        for key in spec_match_keys(row["model"], vendors):
            refs.setdefault(("component", key), row["id"])
    return refs


def _spec_node_index(conn: sqlite3.Connection, vendors=DEFAULT_VENDOR_PREFIXES):
    """사양 DB 대상을 가리키는 활성 노드 (정식 종류 우선, GR3-3 1번). 노드의 현재 종류·이름을 쓴다."""
    from graph_rag.validate import SpecIndex

    index = SpecIndex()
    aliases: dict[int, list[str]] = {}
    for row in conn.execute("""SELECT a.entity_id, a.alias FROM graph_alias a JOIN graph_entity e ON e.id = a.entity_id
                               WHERE e.ref_id IS NOT NULL AND e.lifecycle_state = 'active'"""):
        aliases.setdefault(row["entity_id"], []).append(row["alias"])
    for row in conn.execute("""SELECT id, type, coalesce(display_name, name) AS name FROM graph_entity
                               WHERE ref_id IS NOT NULL AND lifecycle_state = 'active' ORDER BY id"""):
        index.add(row["id"], row["type"], row["name"], [row["name"], *aliases.get(row["id"], [])], vendors)
    return index


def _prune_orphans(conn: sqlite3.Connection) -> int:
    """어느 페이지에도 안 나오고 관계도 없는 개체를 지운다. 사양 DB 대상을 가리키는 개체(ref_id)는 남긴다."""
    cur = conn.execute(
        """DELETE FROM graph_entity
           WHERE manual_retained=0 AND lifecycle_state='active'
             AND NOT EXISTS (SELECT 1 FROM graph_property_value p WHERE p.entity_id=graph_entity.id)
             AND NOT EXISTS (SELECT 1 FROM graph_entity e WHERE e.merged_into_id=graph_entity.id)
             AND ref_id IS NULL
             AND NOT EXISTS (SELECT 1 FROM graph_mention m WHERE m.entity_id = graph_entity.id)
             AND NOT EXISTS (SELECT 1 FROM graph_relation r
                             WHERE r.src_id = graph_entity.id OR r.dst_id = graph_entity.id)"""
    )
    return cur.rowcount
