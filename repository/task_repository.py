import sqlite3
import uuid
from datetime import datetime

from entity.type import TaskEntity, TaskStatus
from repository.repo_connect import Database

view_sql = """
select * from tasks
    where status = :status
       """

class TaskRepository:
    def __init__(self, db: Database):
        self.db = db

    def create_task(self, mail_uid: str, conn: sqlite3.Connection) -> TaskEntity:
        now = datetime.now().isoformat()
        task_id = str(uuid.uuid4())

        conn.execute(
            """
            INSERT INTO tasks
            (task_id, mail_uid, status, assignee, retry_count,
             draft_answer, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (task_id, mail_uid, TaskStatus.PENDING.value, None, 0, "", now, now),
        )

        return TaskEntity(
            task_id=task_id,
            status=TaskStatus.PENDING,
            mail_uid=mail_uid,
            created_at=datetime.fromisoformat(now),
            updated_at=datetime.fromisoformat(now),
        )


    def update_status(self, task_id: str, state: TaskStatus):
        pass

    def save_draft(self, answer, DRAFTED):
        pass

    def view_all(self):
        pass


    def get_task_status(self,Task):


        with self.db.lock, self.db.get_conn() as conn:
            conn.execute(
                view_sql,
                         )