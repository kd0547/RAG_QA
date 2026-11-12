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
            SELECT attachment_id, type, filename, content_type, image_data, stored_path
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
                attachment_id=row["attachment_id"],
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

    # ------------------------------------------------------------ 첨부 페이지 (read_attachment)

    def attachment_for_task(self, attachment_id: int, task_id: str) -> dict | None:
        """task의 메일에 속한 첨부 하나. 다른 메일의 첨부거나 없으면 None."""
        with self.db.get_conn() as conn:
            row = conn.execute(
                """
                SELECT a.attachment_id, a.type, a.filename, a.content_type, a.stored_path
                FROM mail_attachments a JOIN tasks t ON t.mail_uid = a.mail_uid
                WHERE a.attachment_id = ? AND t.task_id = ?
                """,
                (attachment_id, task_id),
            ).fetchone()
        return dict(row) if row else None

    def attachment_pages(self, attachment_id: int) -> list[dict]:
        with self.db.get_conn() as conn:
            rows = conn.execute(
                "SELECT seq, page, text, parser_version FROM attachment_page WHERE attachment_id = ? ORDER BY seq",
                (attachment_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def save_attachment_pages(self, attachment_id: int, pages: list, parser_version: str) -> None:
        """첨부를 파싱한 페이지들을 저장한다 (이미 있으면 갈아끼운다). pages: PageText 목록."""
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM attachment_page WHERE attachment_id = ?", (attachment_id,))
            conn.executemany(
                "INSERT INTO attachment_page (attachment_id, seq, page, text, parser_version) VALUES (?, ?, ?, ?, ?)",
                [(attachment_id, seq, p.page, p.text or "", parser_version) for seq, p in enumerate(pages)],
            )
