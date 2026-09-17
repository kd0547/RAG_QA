import sqlite3
from datetime import datetime

from entity.type import TaskStatus
from entity.type import MailEntity
from repository.repo_connect import Database


class EmailRepository:
    def __init__(self, db: Database):
        self.db = db

    def get_processed_uids(self) -> set[str]:
        with self.db.lock, self.db.get_conn() as conn:
            rows = conn.execute("SELECT uid FROM mails").fetchall()
            return {row["uid"] for row in rows}

    def save_pending(self, mail: MailEntity, conn: sqlite3.Connection) -> None:
        now = datetime.now().isoformat()
        conn.execute(
            """
            INSERT INTO mails
            (uid, subject, sender, body, received_at, attachments,
             created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT
                (uid)
                DO NOTHING
            """,
            (
                mail.uid,
                mail.subject,
                mail.sender,
                mail.body,
                mail.received_at.isoformat(),
                ",".join(mail.attachments) if mail.attachments else "",
                now,
                now,
            ),
        )

    def get_mail_by_id(self, mail_uid):
        pass