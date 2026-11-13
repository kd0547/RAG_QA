import sqlite3
import threading
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "storage" / "schema.sql"


class Database:
    """SQLite 커넥션 생성 + 스키마 초기화 담당. Repository들이 이 인스턴스를 공유한다."""

    def __init__(self, db_path: str = "storage/mail.db"):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_schema()

    def get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_schema(self):
        schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
        with self._lock, self.get_conn() as conn:
            conn.executescript(schema_sql)
            _migrate(conn)

    def transaction(self):
        """with db.transaction() as conn: 형태로 사용. 블록 정상 종료 시 커밋, 예외 시 롤백."""
        return _Transaction(self)

    @property
    def lock(self) -> threading.Lock:
        return self._lock

def _migrate(conn: sqlite3.Connection) -> None:
    """schema.sql은 CREATE IF NOT EXISTS라 이미 있는 테이블에 새 컬럼을 넣지 못한다. 그 차이를 여기서 채운다."""
    file_columns = {row["name"] for row in conn.execute("PRAGMA table_info(file)")}
    if "group_id" not in file_columns:
        conn.execute("ALTER TABLE file ADD COLUMN group_id TEXT REFERENCES file_group(id) ON DELETE SET NULL")
    if "description" not in file_columns:
        conn.execute("ALTER TABLE file ADD COLUMN description TEXT NOT NULL DEFAULT ''")
    # 컬럼이 생긴 뒤에 만들어야 하므로 schema.sql이 아니라 여기서 만든다
    conn.execute("CREATE INDEX IF NOT EXISTS idx_file_group_id ON file(group_id)")
    # 문서 그래프 초기 버전에는 관계 출처(origin) 컬럼이 없었다. 근거 파일이 없는 관계는 aliases.yaml에서 넣은 것이다
    relation_columns = {row["name"] for row in conn.execute("PRAGMA table_info(graph_relation)")}
    if relation_columns and "origin" not in relation_columns:
        conn.execute("ALTER TABLE graph_relation ADD COLUMN origin TEXT NOT NULL DEFAULT 'extract'")
        conn.execute("UPDATE graph_relation SET origin = 'seed' WHERE file_id IS NULL")
    _migrate_graph_relation_origin(conn)
    # 그래프 개체가 가리키는 사양 DB 대상 (지시서 H1)
    entity_columns = {row["name"] for row in conn.execute("PRAGMA table_info(graph_entity)")}
    if entity_columns and "ref_type" not in entity_columns:
        conn.execute("ALTER TABLE graph_entity ADD COLUMN ref_type TEXT")
    if entity_columns and "ref_id" not in entity_columns:
        conn.execute("ALTER TABLE graph_entity ADD COLUMN ref_id TEXT")
    if entity_columns:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_graph_entity_ref ON graph_entity(ref_type, ref_id)")
    # 제품 초기 버전에는 상위 모델(parent_id)이 없었다
    product_columns = {row["name"] for row in conn.execute("PRAGMA table_info(product)")}
    if product_columns and "parent_id" not in product_columns:
        conn.execute("ALTER TABLE product ADD COLUMN parent_id TEXT REFERENCES product(id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_product_parent ON product(parent_id)")
    # 파생 모델이 상위 모델 값을 물려받아도 되는 속성 표시 (지시서 E1). 기존 속성은 전부 0(허용 안 함)
    attribute_columns = {row["name"] for row in conn.execute("PRAGMA table_info(spec_attribute)")}
    if attribute_columns and "inheritable" not in attribute_columns:
        conn.execute("ALTER TABLE spec_attribute ADD COLUMN inheritable INTEGER NOT NULL DEFAULT 0")
    _migrate_task_reviews_action(conn)
    # 초안의 근거 검증 결과 (agent/validation.py)
    task_columns = {row["name"] for row in conn.execute("PRAGMA table_info(tasks)")}
    if task_columns and "validation_json" not in task_columns:
        conn.execute("ALTER TABLE tasks ADD COLUMN validation_json TEXT")
    # 반려를 같은 대화의 다음 턴으로 넣을 때, 이미 반영한 반려를 다시 넣지 않기 위한 표시
    if task_columns and "last_review_id" not in task_columns:
        conn.execute("ALTER TABLE tasks ADD COLUMN last_review_id INTEGER")
    # 검토 화면의 실행별 이력에 실행 종류를 보여 준다
    run_columns = {row["name"] for row in conn.execute("PRAGMA table_info(run)")}
    if run_columns and "label" not in run_columns:
        conn.execute("ALTER TABLE run ADD COLUMN label TEXT")
    # 고객방이 반려 전후 초안을 모두 보여 주도록 실행별 답변 본문, 서버가 적용한 업무 절차
    if run_columns and "answer" not in run_columns:
        conn.execute("ALTER TABLE run ADD COLUMN answer TEXT")
    if run_columns and "skills_json" not in run_columns:
        conn.execute("ALTER TABLE run ADD COLUMN skills_json TEXT")
    # 근거 서비스 이후 출처가 '인용'인지 '읽기만'인지 구분한다
    source_columns = {row["name"] for row in conn.execute("PRAGMA table_info(task_sources)")}
    if source_columns and "cited" not in source_columns:
        conn.execute("ALTER TABLE task_sources ADD COLUMN cited INTEGER NOT NULL DEFAULT 0")
    conn.commit()


# task_reviews.action에 허용하는 값 (schema.sql의 CHECK와 같아야 한다)
TASK_REVIEW_ACTIONS = ("reject", "mark_sent", "retry")


def _migrate_task_reviews_action(conn: sqlite3.Connection) -> None:
    """task_reviews.action의 CHECK에 'mark_sent'·'retry'를 넣는다.

    SQLite는 CHECK 제약을 ALTER로 바꿀 수 없어서, 예전 제약을 가진 테이블은 새 테이블로 옮겨 만든다.
    기존 반려 이력(review_id 포함)은 그대로 복사한다.
    """
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'task_reviews'").fetchone()
    if row is None or all(f"'{action}'" in row["sql"] for action in TASK_REVIEW_ACTIONS):
        return
    conn.execute("""
        CREATE TABLE task_reviews_new (
            review_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id     TEXT NOT NULL,
            action      TEXT NOT NULL CHECK (action IN ('reject', 'mark_sent', 'retry')),
            reason      TEXT,
            requeue     INTEGER NOT NULL DEFAULT 1,
            reviewed_at TEXT NOT NULL,
            FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
        )
    """)
    conn.execute("""
        INSERT INTO task_reviews_new (review_id, task_id, action, reason, requeue, reviewed_at)
        SELECT review_id, task_id, action, reason, requeue, reviewed_at FROM task_reviews
    """)
    conn.execute("DROP TABLE task_reviews")
    conn.execute("ALTER TABLE task_reviews_new RENAME TO task_reviews")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_task_reviews_task_id ON task_reviews(task_id)")


# graph_relation.origin에 허용하는 값 (schema.sql의 CHECK와 같아야 한다)
GRAPH_RELATION_ORIGINS = ("extract", "seed", "manual", "spec")


def _migrate_graph_relation_origin(conn: sqlite3.Connection) -> None:
    """graph_relation.origin의 CHECK에 'spec'을 넣고 옵션 여부(is_option) 컬럼을 더한다 (지시서 H1).

    SQLite는 CHECK 제약을 ALTER로 바꿀 수 없어서, 예전 제약을 가진 테이블은 새 테이블로 옮겨 만든다.
    기존 행은 id·created_at까지 그대로 복사하고 인덱스(유일 인덱스 포함)를 다시 만든다.
    옮기는 동안 외래키 검사를 끈다: 지금 있는 행을 바꾸지 않고 그대로 옮기는 것이 목적이라서다
    (외래키를 켠 채 옮기면 예전에 남은 행 하나 때문에 서버 시작이 막힐 수 있다).
    """
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'graph_relation'").fetchone()
    if row is None or all(f"'{origin}'" in row["sql"] for origin in GRAPH_RELATION_ORIGINS):
        return
    conn.commit()  # 앞선 마이그레이션의 열린 트랜잭션을 닫아야 외래키 설정을 바꿀 수 있다
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute("BEGIN")
        conn.execute("""
            CREATE TABLE graph_relation_new (
                id         integer primary key autoincrement,
                src_id     integer not null references graph_entity(id) on delete cascade,
                dst_id     integer not null references graph_entity(id) on delete cascade,
                type       text not null,
                file_id    text references file(file_id) on delete cascade,
                page       integer,
                origin     text not null default 'extract' check (origin in ('extract', 'seed', 'manual', 'spec')),
                is_option  integer not null default 0 check (is_option in (0, 1)),
                created_at text not null default current_timestamp
            )
        """)
        conn.execute("""
            INSERT INTO graph_relation_new (id, src_id, dst_id, type, file_id, page, origin, created_at)
            SELECT id, src_id, dst_id, type, file_id, page, origin, created_at FROM graph_relation
        """)
        conn.execute("DROP TABLE graph_relation")
        conn.execute("ALTER TABLE graph_relation_new RENAME TO graph_relation")
        conn.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_graph_relation_unique
                        ON graph_relation(src_id, dst_id, type, ifnull(file_id, ''), ifnull(page, -1))""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_graph_relation_dst ON graph_relation(dst_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_graph_relation_file ON graph_relation(file_id, page)")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


class _Transaction:

    def __init__(self,db: "Database"):
        self.db = db


    def __enter__(self) -> sqlite3.Connection:
        self.db.lock.acquire()
        self.conn = self.db.get_conn()
        self.conn.__enter__()
        return self.conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            return self.conn.__exit__(exc_type, exc_val, exc_tb)
        finally:
            self.db.lock.release()
