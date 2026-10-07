import sqlite3
from datetime import datetime

from entity.type import TaskStatus, DocumentType
from entity.type import MailEntity, Attachment
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
        cursor = conn.execute(
            """
            INSERT INTO mails
            (uid, subject, sender, body, received_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
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
                now,
                now,
            ),
        )

        # 이미 저장된 메일이면(DO NOTHING) 첨부파일도 중복 저장하지 않음
        if cursor.rowcount == 1 and mail.attachments:
            self.save_attachments(mail.uid, mail.attachments, conn)

    def save_attachments(
        self, mail_uid: str, attachments: list[Attachment], conn: sqlite3.Connection
    ) -> None:
        conn.executemany(
            """
            INSERT INTO mail_attachments
            (mail_uid, type, filename, content_type, image_data, stored_path)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    mail_uid,
                    DocumentType(attachment.type).value,
                    attachment.filename,
                    attachment.content_type,
                    attachment.image,
                    attachment.path,
                )
                for attachment in attachments
            ],
        )

    def get_attachments_by_mail_uid(
        self, mail_uid: str, conn: sqlite3.Connection
    ) -> list[Attachment]:
        rows = conn.execute(
            """
            SELECT type, filename, content_type, image_data, stored_path
            FROM mail_attachments
            WHERE mail_uid = ?
            ORDER BY attachment_id
            """,
            (mail_uid,),
        ).fetchall()

        return [
            Attachment(
                type=DocumentType(row["type"]),
                filename=row["filename"],
                content_type=row["content_type"],
                image=row["image_data"],
                path=row["stored_path"],
            )
            for row in rows
        ]

    def get_mail_by_id(self, mail_uid: str) -> MailEntity | None:
        with self.db.lock, self.db.get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM mails WHERE uid = ?", (mail_uid,)
            ).fetchone()

            if row is None:
                return None

            attachments = self.get_attachments_by_mail_uid(mail_uid, conn)

        return MailEntity(
            uid=row["uid"],
            subject=row["subject"],
            sender=row["sender"],
            body=row["body"],
            received_at=datetime.fromisoformat(row["received_at"]),
            attachments=attachments,
        )
