"""Transactional, additive user-edit migration. Never open the production DB here."""
import json
import hashlib
import logging
import uuid

from graph_rag.defaults import DEFAULT_ENTITY_TYPES, DEFAULT_RELATION_TYPES

logger = logging.getLogger(__name__)


def migrate_graph_editing(conn):
    conn.execute("SAVEPOINT graph_edit_migration")
    try:
        _migrate(conn)
        conn.execute("RELEASE graph_edit_migration")
    except Exception:
        conn.execute("ROLLBACK TO graph_edit_migration")
        conn.execute("RELEASE graph_edit_migration")
        raise


def _migrate(conn):
    columns = {
        "graph_entity": {
            "creation_origin": "TEXT NOT NULL DEFAULT 'legacy'",
            "lifecycle_state": "TEXT NOT NULL DEFAULT 'active'",
            "manual_retained": "INTEGER NOT NULL DEFAULT 0",
            "display_name": "TEXT", "revision": "INTEGER NOT NULL DEFAULT 1",
            "updated_at": "TEXT", "deleted_at": "TEXT",
            "merged_into_id": "INTEGER REFERENCES graph_entity(id)",
        },
        "graph_relation": {
            "source_key": "TEXT NOT NULL DEFAULT ''",
            "lifecycle_state": "TEXT NOT NULL DEFAULT 'active'",
            "revision": "INTEGER NOT NULL DEFAULT 1", "updated_at": "TEXT",
        },
        "graph_alias": {"hidden": "INTEGER NOT NULL DEFAULT 0"},
    }
    for table, additions in columns.items():
        present = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, ddl in additions.items():
            if name not in present:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
    statements = [
        """CREATE TABLE IF NOT EXISTS graph_relation_type (
          key TEXT PRIMARY KEY, label TEXT NOT NULL UNIQUE, description TEXT NOT NULL DEFAULT '',
          source_entity_types TEXT NOT NULL, target_entity_types TEXT NOT NULL,
          allow_self INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1,
          builtin INTEGER NOT NULL DEFAULT 0, revision INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT)""",
        """CREATE TABLE IF NOT EXISTS graph_property_definition (
          property_id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT NOT NULL UNIQUE, label TEXT NOT NULL UNIQUE,
          value_type TEXT NOT NULL CHECK(value_type IN ('text','number','boolean','date','enum')),
          unit TEXT, allowed_values TEXT NOT NULL DEFAULT '[]', allowed_entity_types TEXT NOT NULL,
          multiple INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1,
          revision INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT)""",
        """CREATE TABLE IF NOT EXISTS graph_property_value (
          value_id INTEGER PRIMARY KEY AUTOINCREMENT, entity_id INTEGER NOT NULL REFERENCES graph_entity(id),
          property_id INTEGER NOT NULL REFERENCES graph_property_definition(property_id),
          value_text TEXT, value_number REAL, value_boolean INTEGER CHECK(value_boolean IN (0,1)), value_date TEXT,
          confirmation TEXT NOT NULL DEFAULT 'confirmed' CHECK(confirmation IN ('confirmed','uncertain','unsupported')),
          lifecycle_state TEXT NOT NULL DEFAULT 'active', revision INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT)""",
        """CREATE TABLE IF NOT EXISTS graph_fact_source (
          source_id INTEGER PRIMARY KEY AUTOINCREMENT, fact_kind TEXT NOT NULL, fact_id INTEGER NOT NULL,
          fact_revision INTEGER NOT NULL DEFAULT 1,
          file_id TEXT REFERENCES file(file_id) ON DELETE SET NULL, original_file_id TEXT,
          page INTEGER, source_name TEXT, revision TEXT, excerpt TEXT, content_hash TEXT,
          reason TEXT NOT NULL DEFAULT '', verification TEXT NOT NULL DEFAULT 'user_input',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
        "CREATE INDEX IF NOT EXISTS idx_graph_fact_source ON graph_fact_source(fact_kind, fact_id)",
        """CREATE TABLE IF NOT EXISTS graph_exclusion (
          src_id INTEGER NOT NULL REFERENCES graph_entity(id), dst_id INTEGER NOT NULL REFERENCES graph_entity(id),
          type TEXT NOT NULL, source_key TEXT NOT NULL DEFAULT '*',
          PRIMARY KEY(src_id,dst_id,type,source_key))""",
        """CREATE TABLE IF NOT EXISTS graph_edit_event (
          event_id INTEGER PRIMARY KEY AUTOINCREMENT, target_kind TEXT NOT NULL, target_id TEXT NOT NULL,
          action TEXT NOT NULL, before_json TEXT, after_json TEXT,
          expected_revision INTEGER, result_revision INTEGER,
          actor_label TEXT NOT NULL DEFAULT '', session_id TEXT NOT NULL DEFAULT '',
          authenticated INTEGER NOT NULL DEFAULT 0, correlation_id TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS graph_edit_request (
          request_key TEXT PRIMARY KEY, payload_hash TEXT NOT NULL, response_json TEXT NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS idx_graph_edit_target ON graph_edit_event(target_kind,target_id,event_id)",
    ]
    for sql in statements:
        conn.execute(sql)
    if 'fact_revision' not in {r['name'] for r in conn.execute('PRAGMA table_info(graph_fact_source)')}:
        conn.execute('ALTER TABLE graph_fact_source ADD COLUMN fact_revision INTEGER NOT NULL DEFAULT 1')
    _migrate_types(conn)
    # Drop the old file-based uniqueness BEFORE detaching manual source references.
    conn.execute("DROP INDEX IF EXISTS idx_graph_relation_unique")
    conn.execute("""UPDATE graph_relation SET source_key = CASE WHEN origin='manual' THEN 'manual:' || id
      ELSE origin || ':' || ifnull(file_id,'') || ':' || ifnull(page,-1) END WHERE source_key=''""")
    conn.execute("""INSERT INTO graph_fact_source
      (fact_kind,fact_id,file_id,original_file_id,page,source_name,reason)
      SELECT 'relation',r.id,f.file_id,r.file_id,r.page,f.original_name,'기존 수동 관계 이관'
      FROM graph_relation r LEFT JOIN file f ON f.file_id=r.file_id
      WHERE r.origin='manual' AND r.file_id IS NOT NULL""")
    for source in conn.execute("""SELECT fs.source_id,fp.text,fp.updated_at FROM graph_fact_source fs
      JOIN file_page fp ON fp.file_id=fs.file_id AND fp.page=fs.page
      WHERE fs.reason='기존 수동 관계 이관' AND fs.content_hash IS NULL ORDER BY fp.seq""").fetchall():
        conn.execute('UPDATE graph_fact_source SET revision=?,excerpt=?,content_hash=? WHERE source_id=? AND content_hash IS NULL',
            (source['updated_at'],source['text'][:4000],hashlib.sha256(source['text'].encode()).hexdigest(),source['source_id']))
    conn.execute("UPDATE graph_relation SET file_id=NULL, page=NULL WHERE origin='manual'")
    conn.execute("""UPDATE graph_entity SET manual_retained=1 WHERE id IN
      (SELECT src_id FROM graph_relation WHERE origin='manual' UNION SELECT dst_id FROM graph_relation WHERE origin='manual')""")
    conn.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_graph_relation_source ON graph_relation
      (src_id,dst_id,type,coalesce(nullif(source_key,''),origin || ':' || ifnull(file_id,'') || ':' || ifnull(page,-1)))""")
    conn.execute("""CREATE TRIGGER IF NOT EXISTS graph_relation_source_key AFTER INSERT ON graph_relation
      WHEN NEW.source_key='' BEGIN UPDATE graph_relation SET source_key=CASE WHEN NEW.origin='manual'
      THEN 'manual:' || NEW.id ELSE NEW.origin || ':' || ifnull(NEW.file_id,'') || ':' || ifnull(NEW.page,-1) END
      WHERE id=NEW.id; END""")
    # Map unambiguous legacy blocks; unmapped normalized rules remain intact.
    conn.execute("""INSERT OR IGNORE INTO graph_exclusion(src_id,dst_id,type)
      SELECT s.id,d.id,b.type FROM graph_relation_block b
      JOIN graph_entity s ON s.type=b.src_type AND s.norm=b.src_norm
      JOIN graph_entity d ON d.type=b.dst_type AND d.norm=b.dst_norm""")
    conn.execute("""UPDATE graph_entity SET manual_retained=1 WHERE id IN
      (SELECT src_id FROM graph_exclusion UNION SELECT dst_id FROM graph_exclusion)""")
    conn.execute("""CREATE VIEW IF NOT EXISTS effective_graph_entity AS SELECT
      id,type,coalesce(display_name,name) AS name,norm,created_at,ref_type,ref_id,creation_origin,
      lifecycle_state,manual_retained,display_name,revision,updated_at,deleted_at,merged_into_id
      FROM graph_entity WHERE lifecycle_state='active'""")
    conn.execute('DROP VIEW IF EXISTS effective_graph_relation')
    conn.execute("""CREATE VIEW effective_graph_relation AS SELECT r.* FROM graph_relation r
      JOIN effective_graph_entity s ON s.id=r.src_id JOIN effective_graph_entity d ON d.id=r.dst_id
      WHERE r.lifecycle_state='active' AND (r.origin='manual' OR (NOT EXISTS (SELECT 1 FROM graph_exclusion b
      WHERE b.src_id=r.src_id AND b.dst_id=r.dst_id AND b.type=r.type AND b.source_key IN ('*',r.source_key))
      AND NOT EXISTS (SELECT 1 FROM graph_relation_block b WHERE b.src_type=s.type AND b.src_norm=s.norm
      AND b.dst_type=d.type AND b.dst_norm=d.norm AND b.type=r.type)))""")
    remove_system_concepts(conn)


def _migrate_types(conn):
    """개체 종류 테이블(GR2)과 관계 종류의 추출 여부 열. 기본값은 없을 때만 넣고, 사용자가 고친 값을 덮지 않는다."""
    conn.execute("""CREATE TABLE IF NOT EXISTS graph_entity_type (
      key                 TEXT PRIMARY KEY,
      label               TEXT NOT NULL UNIQUE,
      description         TEXT NOT NULL DEFAULT '',
      color               TEXT NOT NULL,
      extract             INTEGER NOT NULL DEFAULT 0,
      requires_identifier INTEGER NOT NULL DEFAULT 0,
      builtin             INTEGER NOT NULL DEFAULT 0,
      active              INTEGER NOT NULL DEFAULT 1,
      sort_order          INTEGER NOT NULL DEFAULT 0,
      revision            INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT)""")
    seeded = conn.execute("SELECT count(*) FROM graph_entity_type").fetchone()[0] > 0
    for order, item in enumerate(DEFAULT_ENTITY_TYPES):
        if seeded:
            break  # 한 번 넣은 뒤에는 사용자가 지운 기본 종류를 되살리지 않는다
        conn.execute("""INSERT OR IGNORE INTO graph_entity_type
          (key,label,description,color,extract,requires_identifier,builtin,sort_order) VALUES (?,?,?,?,?,?,1,?)""",
          (item["key"], item["label"], item["description"], item["color"], item["extract"],
           item["requires_identifier"], order * 10))
    relation_columns = {r["name"] for r in conn.execute("PRAGMA table_info(graph_relation_type)")}
    if "extract" not in relation_columns:
        conn.execute("ALTER TABLE graph_relation_type ADD COLUMN extract INTEGER NOT NULL DEFAULT 0")
        # 열이 새로 생길 때만: 기존 기본 관계 중 문서 추출에 쓰던 것은 1 (지금 동작 유지)
        for item in DEFAULT_RELATION_TYPES:
            if item["extract"]:
                conn.execute("UPDATE graph_relation_type SET extract=1 WHERE key=? AND builtin=1", (item["key"],))
    for item in DEFAULT_RELATION_TYPES:
        source, target = json.dumps(sorted(item["source"])), json.dumps(sorted(item["target"]))
        conn.execute("""INSERT OR IGNORE INTO graph_relation_type
          (key,label,description,source_entity_types,target_entity_types,builtin,extract) VALUES (?,?,?,?,?,1,?)""",
          (item["key"], item["label"], item["description"], source, target, item["extract"]))
        # 사용자가 고치지 않은(revision 1) 기본 관계만 기본 표로 맞춘다 (지시서 GR3-1). revision은 올리지 않는다
        conn.execute("""UPDATE graph_relation_type SET description=?, source_entity_types=?, target_entity_types=?, extract=?
          WHERE key=? AND builtin=1 AND revision=1
            AND (description!=? OR source_entity_types!=? OR target_entity_types!=? OR extract!=?)""",
          (item["description"], source, target, item["extract"], item["key"],
           item["description"], source, target, item["extract"]))


def remove_system_concepts(conn):
    """시스템이 만든 상위 개념을 지운다 (지시서 GR1). 출처와 관계없이 concept 개체와 part_of 관계 전부.

    몇 번 돌려도 결과가 같다. 지운 것이 있을 때만 편집 이력 한 건(action='migration', target_kind='schema')과 INFO 로그를 남긴다.
    """
    concept_ids = [r[0] for r in conn.execute("SELECT id FROM graph_entity WHERE type='concept'")]
    marks = ",".join("?" * len(concept_ids))
    counts = {}
    relation_filter = "type='part_of'" + (f" OR src_id IN ({marks}) OR dst_id IN ({marks})" if concept_ids else "")
    relation_params = [*concept_ids, *concept_ids] if concept_ids else []
    relation_ids = [r[0] for r in conn.execute(f"SELECT id FROM graph_relation WHERE {relation_filter}", relation_params)]
    if relation_ids:
        rel_marks = ",".join("?" * len(relation_ids))
        conn.execute(f"DELETE FROM graph_fact_source WHERE fact_kind='relation' AND fact_id IN ({rel_marks})", relation_ids)
    counts["relations"] = conn.execute(f"DELETE FROM graph_relation WHERE {relation_filter}", relation_params).rowcount
    exclusion_filter = "type='part_of'" + (f" OR src_id IN ({marks}) OR dst_id IN ({marks})" if concept_ids else "")
    counts["exclusions"] = conn.execute(f"DELETE FROM graph_exclusion WHERE {exclusion_filter}", relation_params).rowcount
    counts["blocks"] = conn.execute(
        "DELETE FROM graph_relation_block WHERE type='part_of' OR src_type='concept' OR dst_type='concept'").rowcount
    if concept_ids:
        value_ids = [r[0] for r in conn.execute(f"SELECT value_id FROM graph_property_value WHERE entity_id IN ({marks})", concept_ids)]
        if value_ids:
            value_marks = ",".join("?" * len(value_ids))
            conn.execute(f"DELETE FROM graph_fact_source WHERE fact_kind='property' AND fact_id IN ({value_marks})", value_ids)
        counts["property_values"] = conn.execute(
            f"DELETE FROM graph_property_value WHERE entity_id IN ({marks})", concept_ids).rowcount
        conn.execute(f"DELETE FROM graph_alias WHERE entity_id IN ({marks})", concept_ids)
        conn.execute(f"DELETE FROM graph_mention WHERE entity_id IN ({marks})", concept_ids)
        conn.execute(f"UPDATE graph_entity SET merged_into_id=NULL WHERE merged_into_id IN ({marks})", concept_ids)
        counts["entities"] = conn.execute(f"DELETE FROM graph_entity WHERE id IN ({marks})", concept_ids).rowcount
    else:
        counts["property_values"] = counts["entities"] = 0
    counts["relation_types"] = conn.execute("DELETE FROM graph_relation_type WHERE key='part_of'").rowcount
    # 사용자 정의의 허용 종류 목록에서 concept을 뺀다 (다른 종류가 남을 때만)
    for table, key, columns in (("graph_relation_type", "key", ("source_entity_types", "target_entity_types")),
                                ("graph_property_definition", "property_id", ("allowed_entity_types",))):
        for row in conn.execute(f"SELECT {key}, {', '.join(columns)} FROM {table}").fetchall():
            for column in columns:
                values = json.loads(row[column])
                if "concept" in values and len(values) > 1:
                    conn.execute(f"UPDATE {table} SET {column}=? WHERE {key}=?",
                                 (json.dumps(sorted(v for v in values if v != "concept"), ensure_ascii=False, sort_keys=True), row[key]))
    if any(counts.values()):
        conn.execute("""INSERT INTO graph_edit_event (target_kind,target_id,action,before_json,after_json,correlation_id)
          VALUES ('schema','GR1-remove-system-concepts','migration',NULL,?,?)""",
          (json.dumps(counts, ensure_ascii=False, sort_keys=True), uuid.uuid4().hex))
        logger.info("시스템 상위 개념 삭제 (GR1): %s", counts)
    return counts
