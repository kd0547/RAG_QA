"""Transactional, additive user-edit migration. Never open the production DB here."""
import json
import hashlib

from graph_rag.types import RELATION_TYPES


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
    endpoints = {
        'has_component': (['product'], ['component']),
        'has_certification': (['product'], ['certification']),
        'has_number': (['product','certification'], ['cert_number']),
        'issued_by': (['certification','cert_number'], ['organization']),
        'complies_with': (['product','certification'], ['standard']),
        'part_of': (['certification'], ['concept']), 'variant_of': (['product'], ['product']),
    }
    labels = ['부품', '인증', '번호', '발급 기관', '규격 준수', '상위 개념', '상위 모델']
    for (key, description), label in zip(RELATION_TYPES.items(), labels):
        src, dst = endpoints[key]
        conn.execute("""INSERT OR IGNORE INTO graph_relation_type
          (key,label,description,source_entity_types,target_entity_types,builtin) VALUES (?,?,?,?,?,1)""",
          (key,label,description,json.dumps(src),json.dumps(dst)))
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
