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
    conn.commit()


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
