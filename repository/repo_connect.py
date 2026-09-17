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

    def transaction(self):
        """with db.transaction() as conn: 형태로 사용. 블록 정상 종료 시 커밋, 예외 시 롤백."""
        return _Transaction(self)

    @property
    def lock(self) -> threading.Lock:
        return self._lock

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
