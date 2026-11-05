from entity.file import FileEntity
from repository.repo_connect import Database



class FileRepository:

    def __init__(self,db:Database):
        self.db = db

    def file_list(self) -> list[dict]:
        with self.db.get_conn() as conn:
            select_sql = "SELECT file_id,original_name,group_id,description FROM file"

            rows = conn.execute(select_sql).fetchall()

            return [dict(row) for row in rows]

    def exists_by_sha256(self,sha256:str) -> bool:
        with self.db.get_conn() as conn:
            select_sql = "SELECT 1 FROM file WHERE sha256 = ? AND status != 'failed' LIMIT 1"
            row = conn.execute(select_sql, (sha256,)).fetchone()
            return row is not None

    def file_save(self,file:FileEntity):
        with self.db.get_conn() as conn:
            insert_sql = "INSERT INTO file (file_id, original_name,stored_path,mime_type,size_bytes,sha256,chunk_count,group_id,description) VALUES (?,?,?,?,?,?,?,?,?)"
            conn.execute(insert_sql,(file.file_id,file.original_name,file.stored_path,file.mime_type,file.size_bytes,file.sha256,file.chunk_count,file.group_id,file.description))
            conn.commit()

    def get_file_by_id(self,file_id:str):
        with self.db.get_conn() as conn:
            select_sql = "SELECT * FROM file WHERE file_id = ?"
            row = conn.execute(select_sql, (file_id,)).fetchone()
            if row is None:
                return None
            # 컬럼 순서가 아니라 이름으로 채운다. 마이그레이션으로 컬럼이 뒤에 붙어도 깨지지 않는다.
            return FileEntity(**dict(row))

    def has_other_stored_path(self, stored_path: str, file_id: str) -> bool:
        """옛 업로드의 동명 파일이 같은 원본 경로를 공유하는지 확인한다."""
        with self.db.get_conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM file WHERE stored_path = ? AND file_id != ? LIMIT 1",
                (stored_path, file_id),
            ).fetchone()
            return row is not None

    def update_group(self, file_ids: list[str], group_id: str | None) -> int:
        """파일들을 group_id 그룹으로 옮긴다. None이면 그룹에서 뺀다. 바뀐 행 수를 반환한다."""
        if not file_ids:
            return 0
        with self.db.get_conn() as conn:
            placeholders = ",".join("?" * len(file_ids))
            update_sql = f"UPDATE file SET group_id = ?, updated_at = current_timestamp WHERE file_id IN ({placeholders})"
            cursor = conn.execute(update_sql, (group_id, *file_ids))
            conn.commit()
            return cursor.rowcount

    def update_description(self, file_id: str, description: str) -> bool:
        """파일 설명을 바꾼다. 파일이 없으면 False."""
        with self.db.get_conn() as conn:
            update_sql = "UPDATE file SET description = ?, updated_at = current_timestamp WHERE file_id = ?"
            cursor = conn.execute(update_sql, (description, file_id))
            conn.commit()
            return cursor.rowcount > 0

    def add_relation(self, file_id: str, related_file_id: str) -> bool:
        """두 파일을 연관 파일로 잇는다. 새로 이었으면 True, 이미 이어져 있으면 False.
        자기 자신과는 이을 수 없고(ValueError), 없는 파일이면 sqlite3.IntegrityError가 난다."""
        if file_id == related_file_id:
            raise ValueError("파일을 자기 자신과 연결할 수 없습니다.")
        a, b = sorted((file_id, related_file_id))  # 방향 없는 관계라 항상 작은 id를 앞에 둔다
        with self.db.get_conn() as conn:
            insert_sql = "INSERT OR IGNORE INTO file_relation (file_id, related_file_id) VALUES (?, ?)"
            cursor = conn.execute(insert_sql, (a, b))
            conn.commit()
            return cursor.rowcount > 0

    def remove_relation(self, file_id: str, related_file_id: str) -> bool:
        """두 파일의 연결을 끊는다. 끊을 연결이 없었으면 False."""
        a, b = sorted((file_id, related_file_id))
        with self.db.get_conn() as conn:
            delete_sql = "DELETE FROM file_relation WHERE file_id = ? AND related_file_id = ?"
            cursor = conn.execute(delete_sql, (a, b))
            conn.commit()
            return cursor.rowcount > 0

    def get_related_files(self, file_id: str) -> list[dict]:
        """file_id와 이어진 파일 목록. 관계가 어느 쪽에 저장됐든 상대 파일을 돌려준다."""
        with self.db.get_conn() as conn:
            select_sql = """
                SELECT f.file_id, f.original_name, f.group_id, f.description
                FROM file_relation r
                JOIN file f ON f.file_id = CASE WHEN r.file_id = ? THEN r.related_file_id ELSE r.file_id END
                WHERE r.file_id = ? OR r.related_file_id = ?
                ORDER BY f.original_name
            """
            rows = conn.execute(select_sql, (file_id, file_id, file_id)).fetchall()
            return [dict(row) for row in rows]

    def delete_file(self,file_id:str):
        with self.db.get_conn() as conn:
            delete_sql = "DELETE FROM file WHERE file_id = ?"
            conn.execute(delete_sql, (file_id,))
            conn.commit()
