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


def _dedupe_sources(sources: list[dict]) -> list[dict]:
    """search/rerank 결과에 같은 청크가 반복되므로 청크 ID(없으면 문서·페이지·본문) 기준으로 한 번만 남긴다."""
    seen = set()
    result = []
    for doc in sources:
        if not isinstance(doc, dict):
            continue
        key = doc.get("id") or (doc.get("source"), doc.get("page"), doc.get("text"))
        if key in seen:
            continue
        seen.add(key)
        result.append(doc)
    return result


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

    def save_draft(self, task_id: str, answer: str, sources: list[dict] | None = None) -> None:
        """초안과 참조 문서를 한 트랜잭션으로 저장한다. sources가 None이면 출처는 건드리지 않는다."""
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE tasks SET draft_answer = ?, status = ?, updated_at = ? WHERE task_id = ?",
                (answer, TaskStatus.DRAFTED.value, datetime.now().isoformat(), task_id),
            )
            if sources is not None:
                self._replace_sources(task_id, sources, conn)

    def _replace_sources(self, task_id: str, sources: list[dict], conn: sqlite3.Connection) -> None:
        # 재처리 시 이전 출처가 남지 않도록 지우고 다시 넣는다.
        conn.execute("DELETE FROM task_sources WHERE task_id = ?", (task_id,))
        conn.executemany(
            """
            INSERT INTO task_sources
            (task_id, chunk_id, file_id, source, page, chunk_index, text, score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    task_id,
                    doc.get("id"),
                    doc.get("file_id"),
                    doc.get("source") or "",
                    doc.get("page"),
                    doc.get("chunk_index"),
                    doc.get("text") or "",
                    doc.get("score"),
                )
                for doc in _dedupe_sources(sources)
            ],
        )

    def get_sources(self, task_id: str) -> list[dict]:
        with self.db.lock, self.db.get_conn() as conn:
            rows = conn.execute(
                """
                SELECT chunk_id, file_id, source, page, chunk_index, text, score
                FROM task_sources
                WHERE task_id = ?
                ORDER BY source_id
                """,
                (task_id,),
            ).fetchall()
        return [dict(row) for row in rows]
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

    def get_task(self, task_id: str) -> TaskEntity | None:
        with self.db.lock, self.db.get_conn() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        return _row_to_task(row) if row else None

    def reject(
        self,
        task_id: str,
        reason: str,
        next_status: TaskStatus,
        allowed: list[TaskStatus],
    ) -> bool:
        """allowed 상태일 때만 next_status로 바꾸고 반려 이력을 남긴다.
        그사이 다른 요청(승인 등)이 상태를 바꿨으면 아무것도 하지 않고 False."""
        now = datetime.now().isoformat()
        placeholders = ",".join("?" for _ in allowed)
        with self.db.transaction() as conn:
            cursor = conn.execute(
                f"UPDATE tasks SET status = ?, updated_at = ? WHERE task_id = ? AND status IN ({placeholders})",
                (next_status.value, now, task_id, *(s.value for s in allowed)),
            )
            if cursor.rowcount != 1:
                return False
            conn.execute(
                """
                INSERT INTO task_reviews (task_id, action, reason, requeue, reviewed_at)
                VALUES (?, 'reject', ?, ?, ?)
                """,
                (task_id, reason, int(next_status == TaskStatus.PENDING), now),
            )
        return True

    def get_source_files(self, task_id: str) -> list[dict]:
        """답변이 참고한 문서 원본 파일 목록. 청크가 여러 개여도 파일은 한 번만, 처음 참조된 순서로.
        업로드가 같은 이름이면 같은 경로에 덮어쓰므로 file_id가 아니라 stored_path로 중복을 거른다."""
        with self.db.lock, self.db.get_conn() as conn:
            rows = conn.execute(
                """
                -- SQLite는 MIN()과 같이 쓴 나머지 컬럼을 MIN 행에서 가져온다 → 처음 참조된 file_id
                SELECT f.file_id, f.original_name, f.stored_path, f.mime_type, MIN(s.source_id) AS first_ref
                FROM task_sources s
                JOIN file f ON f.file_id = s.file_id
                WHERE s.task_id = ?
                GROUP BY f.stored_path
                ORDER BY first_ref
                """,
                (task_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_reject_reasons(self, task_id: str) -> list[str]:
        """재작성 요청(requeue)으로 반려된 사유를 오래된 순으로 돌려준다."""
        with self.db.lock, self.db.get_conn() as conn:
            rows = conn.execute(
                """
                SELECT reason FROM task_reviews
                WHERE task_id = ? AND action = 'reject' AND requeue = 1 AND reason IS NOT NULL
                ORDER BY review_id
                """,
                (task_id,),
            ).fetchall()
        return [row["reason"] for row in rows]

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
