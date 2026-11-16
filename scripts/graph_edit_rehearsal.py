"""Copy a SQLite DB through a read-only connection and rehearse graph migration.

Usage: python scripts/graph_edit_rehearsal.py --source storage/mail.db --target temp/graph-rehearsal.db
The target MUST NOT exist. The production database is never opened for writing.
"""
import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path


def inventory(conn):
    result = {'sqlite_version':sqlite3.sqlite_version}
    for table in ('graph_entity','graph_alias','graph_relation','graph_relation_block'):
        result[table] = conn.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
    result['manual_with_file'] = conn.execute("SELECT count(*) FROM graph_relation WHERE origin='manual' AND file_id IS NOT NULL").fetchone()[0]
    result['relations_by_origin'] = dict(conn.execute('SELECT origin,count(*) FROM graph_relation GROUP BY origin'))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',required=True)
    parser.add_argument('--target',required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    source,target = Path(args.source).resolve(),Path(args.target).resolve()
    if not source.is_file() or target.exists() or source==target:
        parser.error('원본 파일이 있어야 하며 사본 대상은 존재하지 않는 새 파일이어야 합니다.')
    target.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as conn:
        before = inventory(conn)
        manual = conn.execute("SELECT id,src_id,dst_id,type,file_id,page,created_at FROM graph_relation WHERE origin='manual' ORDER BY id").fetchall()
        entity_columns = {r[1] for r in conn.execute('PRAGMA table_info(graph_entity)')}
        entity_select = 'id,type,name,norm' + (',ref_type,ref_id' if 'ref_type' in entity_columns else '')
        entities = conn.execute('SELECT '+entity_select+' FROM graph_entity ORDER BY id').fetchall()
        aliases = conn.execute('SELECT entity_id,alias,alias_norm FROM graph_alias ORDER BY entity_id,alias_norm').fetchall()
        blocks = conn.execute('SELECT * FROM graph_relation_block ORDER BY src_type,src_norm,type,dst_type,dst_norm').fetchall()
        with sqlite3.connect(target) as dest:
            conn.backup(dest)
    original_connect = sqlite3.connect
    # repository's eager construction must also open only the new copy.
    def isolated(database,*args,**kwargs):
        if isinstance(database,(str,Path)) and not str(database).startswith('file:'):
            if Path(database).resolve()==(root/'storage/mail.db').resolve():
                database=str(target)
        return original_connect(database,*args,**kwargs)
    sqlite3.connect=isolated
    sys.path.insert(0,str(root))
    from repository.repo_connect import Database
    Database(str(target)); Database(str(target))
    with original_connect(target) as conn:
        after=inventory(conn)
        assert conn.execute('SELECT '+entity_select+' FROM graph_entity ORDER BY id').fetchall()==entities
        assert conn.execute('SELECT entity_id,alias,alias_norm FROM graph_alias ORDER BY entity_id,alias_norm').fetchall()==aliases
        assert conn.execute('SELECT * FROM graph_relation_block ORDER BY src_type,src_norm,type,dst_type,dst_norm').fetchall()==blocks
        migrated = conn.execute("SELECT id,src_id,dst_id,type,file_id,page,created_at FROM graph_relation WHERE origin='manual' ORDER BY id").fetchall()
        assert [r[:4]+r[6:] for r in manual]==[r[:4]+r[6:] for r in migrated]
        for row in manual:
            if row[4]:
                assert conn.execute("SELECT 1 FROM graph_fact_source WHERE fact_kind='relation' AND fact_id=? AND original_file_id=? AND page IS ?",(row[0],row[4],row[5])).fetchone()
        violations=conn.execute('PRAGMA foreign_key_check').fetchall()
        assert not violations, violations
        state = hashlib.sha256(repr(list(conn.iterdump())).encode()).hexdigest()
    Database(str(target))
    with original_connect(target) as conn:
        assert hashlib.sha256(repr(list(conn.iterdump())).encode()).hexdigest()==state
    print(json.dumps({'before':before,'after':after,'manual_ids_preserved':len(manual),
        'foreign_key_check':'ok','idempotent':True,'target':str(target)},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
