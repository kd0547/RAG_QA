import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime

from entity.type import TaskEntity, TaskStatus
from repository.repo_connect import Database

view_sql = """
select * from tasks
    where status = :status
       """

@dataclass
class Dashboard:
    task_id: str
    subject: str
    sender: str
    received_at: str
    status: TaskStatus


@dataclass
class DashboardDetail(Dashboard):
    assignee: str | None
    body: str
    draft: str | None
    created_at: str
    updated_at: str


def _row_to_task(row: sqlite3.Row) -> TaskEntity:
    return TaskEntity(
        task_id=row["task_id"],
        mail_uid=row["mail_uid"],
        status=TaskStatus(row["status"]),
        assignee=row["assignee"],
        retry_count=row["retry_count"],
        draft_answer=row["draft_answer"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )

def _row_to_dashboard(row: sqlite3.Row) -> Dashboard:
    return Dashboard(
        task_id=row["task_id"],
        subject=row["subject"],
        sender=row["sender"],
        received_at=row["received_at"],
        status=TaskStatus(row["status"]),
    )


def _row_to_dashboard_detail(row: sqlite3.Row) -> DashboardDetail:
    return DashboardDetail(
        task_id=row["task_id"],
        subject=row["subject"],
        sender=row["sender"],
        received_at=row["received_at"],
        status=TaskStatus(row["status"]),
        assignee=row["assignee"],
        body=row["body"],
        draft=row["draft_answer"] or None,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )



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


    def get_pending_tasks(self) -> list[TaskEntity]:
        with self.db.lock, self.db.get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE status = ?",
                (TaskStatus.PENDING.value,),
            ).fetchall()
        return [_row_to_task(row) for row in rows]

    def update_status(self, task_id: str, state: TaskStatus) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE tasks SET status = ?, updated_at = ? WHERE task_id = ?",
                (state.value, datetime.now().isoformat(), task_id),
            )

    def save_draft(self, task_id: str, answer: str) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE tasks SET draft_answer = ?, status = ?, updated_at = ? WHERE task_id = ?",
                (answer, TaskStatus.DRAFTED.value, datetime.now().isoformat(), task_id),
            )
    def update_draft_answer(self, task_id: str, answer: str) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE tasks SET draft_answer = ?, updated_at = ? WHERE task_id = ?",
                (answer, datetime.now().isoformat(), task_id),
            )

    def view_all(self,statuses:list[TaskStatus]):
        placeholders = ",".join("?" for _ in statuses)
        query = f"SELECT t.task_id, m.subject, m.sender, m.received_at, t.status FROM tasks t join main.mails m on m.uid = t.mail_uid WHERE status IN ({placeholders})"


        with self.db.transaction() as conn:
            rows = conn.execute(
                query, tuple(status.value for status in statuses)
            ).fetchall()
        return [_row_to_dashboard(row) for row in rows]

    def view_task(self, task_id: str) -> DashboardDetail | None:
        query = """
            SELECT t.task_id, m.subject, m.sender, m.received_at, m.body,
                   m.created_at, t.status, t.assignee, t.draft_answer,
                   t.updated_at
            FROM mails AS m
            JOIN tasks AS t ON t.mail_uid = m.uid
            WHERE t.task_id = ?
        """

        with self.db.transaction() as conn:
            row = conn.execute(query, (task_id,)).fetchone()
            if row is None:
                return None
            return _row_to_dashboard_detail(row)


    def get_task_status(self,Task):


        with self.db.lock, self.db.get_conn() as conn:
            conn.execute(
                view_sql,
                         )

    def assign_task(self, task_id, assignee: str):
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE tasks SET assignee = ?, updated_at = ? WHERE task_id = ?",
                (assignee, datetime.now().isoformat(), task_id),
            )

    def approve(self, task_id):
        select_sql = """
                     select t.task_id, t.status, t.draft_answer, m.sender, m.subject
                     from tasks t
                              inner join main.mails m on m.uid = t.mail_uid
                     where t.task_id = ?;
                     """

        with self.db.lock, self.db.get_conn() as conn:
            row = conn.execute(select_sql, (task_id,)).fetchone()

        if row is None:
            return None  # 라우터(app/routers/mails.py)에서 404 처리

        return dict(row)  # {"task_id": ..., "status": ..., "draft_answer": ..., "sender": ..., "subject": ...}
