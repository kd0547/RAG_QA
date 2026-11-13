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
    # 제품 초기 버전에는 상위 모델(parent_id)이 없었다
    product_columns = {row["name"] for row in conn.execute("PRAGMA table_info(product)")}
    if product_columns and "parent_id" not in product_columns:
        conn.execute("ALTER TABLE product ADD COLUMN parent_id TEXT REFERENCES product(id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_product_parent ON product(parent_id)")
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
