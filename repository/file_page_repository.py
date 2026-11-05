"""파일의 페이지별 파싱 텍스트 저장소 (file_page 테이블).

업로드 때 파서 결과를 그대로 저장해 두고, 파일 검수에서는 text만 고친다.
original_text는 처음 파싱한 결과로 남겨 두어 무엇이 바뀌었는지 비교할 수 있게 한다.
"""
from parser.pdf.type import PageText
from repository.repo_connect import Database


def _row(row) -> dict:
    data = dict(row)
    data["edited"] = data["text"] != data["original_text"]
    return data


class FilePageRepository:

    def __init__(self, db: Database):
        self.db = db

    def save_pages(self, file_id: str, pages: list[PageText]) -> int:
        """파일의 페이지 텍스트를 파서 순서대로 저장한다. 이미 있으면 갈아끼운다. 저장한 행 수를 돌려준다."""
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM file_page WHERE file_id = ?", (file_id,))
            conn.executemany(
                "INSERT INTO file_page (file_id, seq, page, text, original_text) VALUES (?, ?, ?, ?, ?)",
                [(file_id, seq, p.page, p.text, p.text) for seq, p in enumerate(pages)],
            )
        return len(pages)

    def has_pages(self, file_id: str) -> bool:
        with self.db.get_conn() as conn:
            return conn.execute("SELECT 1 FROM file_page WHERE file_id = ? LIMIT 1", (file_id,)).fetchone() is not None

    def list_pages(self, file_id: str) -> list[dict]:
        """파일의 페이지 텍스트를 파서 순서대로 돌려준다."""
        with self.db.get_conn() as conn:
            rows = conn.execute(
                "SELECT page_id, seq, page, text, original_text, updated_at FROM file_page WHERE file_id = ? ORDER BY seq",
                (file_id,),
            ).fetchall()
            return [_row(r) for r in rows]

    def get_page(self, file_id: str, page_id: int) -> dict | None:
        """파일에 속한 페이지 행 하나. 다른 파일의 행이거나 없으면 None."""
        with self.db.get_conn() as conn:
            row = conn.execute(
                "SELECT page_id, seq, page, text, original_text, updated_at FROM file_page WHERE file_id = ? AND page_id = ?",
                (file_id, page_id),
            ).fetchone()
            return _row(row) if row else None

    def pages_with_number(self, file_id: str, page: int) -> list[dict]:
        """같은 페이지 번호의 행들 (xlsx 시트처럼 여러 블록일 수 있다)."""
        with self.db.get_conn() as conn:
            rows = conn.execute(
                "SELECT page_id, seq, page, text, original_text, updated_at FROM file_page WHERE file_id = ? AND page = ? ORDER BY seq",
                (file_id, page),
            ).fetchall()
            return [_row(r) for r in rows]

    def update_text(self, page_id: int, text: str) -> None:
        """검수에서 고친 텍스트를 저장한다. original_text는 그대로 둔다."""
        with self.db.get_conn() as conn:
            conn.execute(
                "UPDATE file_page SET text = ?, updated_at = current_timestamp WHERE page_id = ?",
                (text, page_id),
            )
            conn.commit()
