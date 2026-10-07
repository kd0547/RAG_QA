from entity.file import FileEntity
from repository.repo_connect import Database



class FileRepository:

    def __init__(self,db:Database):
        self.db = db

    def file_list(self) -> dict:
        with self.db.get_conn() as conn:
            select_sql = "SELECT file_id,original_name FROM file"

            rows = conn.execute(select_sql).fetchall()

            return [{"file_id":row[0],"original_name":row[1]} for row in rows]

    def exists_by_sha256(self,sha256:str) -> bool:
        with self.db.get_conn() as conn:
            select_sql = "SELECT 1 FROM file WHERE sha256 = ? AND status != 'failed' LIMIT 1"
            row = conn.execute(select_sql, (sha256,)).fetchone()
            return row is not None

    def file_save(self,file:FileEntity):
        with self.db.get_conn() as conn:
            insert_sql = "INSERT INTO file (file_id, original_name,stored_path,mime_type,size_bytes,sha256,chunk_count) VALUES (?,?,?,?,?,?,?)"
            conn.execute(insert_sql,(file.file_id,file.original_name,file.stored_path,file.mime_type,file.size_bytes,file.sha256,file.chunk_count))
            conn.commit()

    def get_file_by_id(self,file_id:str):
        with self.db.get_conn() as conn:
            select_sql = "SELECT * FROM file WHERE file_id = ?"
            row = conn.execute(select_sql, (file_id,)).fetchone()
            if row is None:
                return None
            return FileEntity(*row)

    def delete_file(self,file_id:str):
        with self.db.get_conn() as conn:
            delete_sql = "DELETE FROM file WHERE file_id = ?"
            conn.execute(delete_sql, (file_id,))
            conn.commit()
