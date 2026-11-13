"""고객 이력 조회와 담당자 메모 (통합 지시서 G1).

설계: 고객 메모리를 LLM이 써서 쌓지 않는다. 이력은 기존 기록(mails·tasks·request_analysis)에서 그때그때 조회하고,
사람이 남기는 것만 customer_note에 둔다. 출처 없는 추측이 기억으로 굳지 않고 기록과 기억이 어긋나지 않는다.

고객방 저장소(customer_repository)와 다르게 이 모듈은 모델에 보여 줄 수 있는 것만 돌려준다:
- 같은 발신자의 다른 문의: 수신일, 제목, 문의 유형(문의 분석), 분석 사유 한 줄, 상태
- 담당자 메모(사용 중인 것)
메일 본문, 초안 본문, 반려된 초안, 발송 본문은 싣지 않는다.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from repository.customer_repository import parse_time, sender_key
from repository.repo_connect import Database

logger = logging.getLogger(__name__)

NOTE_MAX_CHARS = 500
REASON_MAX_CHARS = 200
SENDER_MAX_CHARS = 320

STATUS_LABELS = {"sent": "답변 발송됨", "failed": "생성 실패"}
DEFAULT_STATUS_LABEL = "검토 중"


class CustomerNoteNotFoundError(LookupError):
    """그 발신자의 메모가 아니거나 없는 메모"""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _one_line(text: str | None, limit: int = REASON_MAX_CHARS) -> str:
    line = " ".join((text or "").split())
    return line if len(line) <= limit else line[: limit - 1] + "…"


def _note(row) -> dict:
    return {"note_id": row["note_id"], "sender": row["sender"], "text": row["text"], "created_at": row["created_at"],
            "created_by": row["created_by"], "retired_at": row["retired_at"]}


class CustomerHistoryRepository:

    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------ 담당자 메모

    def list_notes(self, sender: str, include_retired: bool = True) -> list[dict]:
        """메모 목록 (최근 것부터). include_retired=False면 사용 중인 것만."""
        key = sender_key(sender)
        sql = "SELECT * FROM customer_note WHERE sender = ?" + ("" if include_retired else " AND retired_at IS NULL")
        with self.db.get_conn() as conn:
            rows = conn.execute(sql + " ORDER BY created_at DESC, note_id DESC", (key,)).fetchall()
        return [_note(r) for r in rows]

    def add_note(self, sender: str, text: str, created_by: str = "") -> dict:
        key = sender_key(sender)
        if not key or len(key) > SENDER_MAX_CHARS:
            raise ValueError("발신자 주소가 올바르지 않습니다.")
        text = (text or "").strip()
        if not text:
            raise ValueError("메모 내용을 입력해 주세요.")
        if len(text) > NOTE_MAX_CHARS:
            raise ValueError(f"메모는 {NOTE_MAX_CHARS}자 이하로 입력해 주세요 ({len(text)}자).")
        with self.db.transaction() as conn:
            note_id = conn.execute(
                "INSERT INTO customer_note (sender, text, created_at, created_by) VALUES (?, ?, ?, ?)",
                (key, text, _now(), (created_by or "")[:100]),
            ).lastrowid
            row = conn.execute("SELECT * FROM customer_note WHERE note_id = ?", (note_id,)).fetchone()
        return _note(row)

    def retire_note(self, sender: str, note_id: int) -> dict:
        """메모를 사용 중지한다 (지우지 않는다). 이미 중지된 메모는 그대로 돌려준다."""
        key = sender_key(sender)
        with self.db.transaction() as conn:
            row = conn.execute("SELECT * FROM customer_note WHERE note_id = ? AND sender = ?", (note_id, key)).fetchone()
            if row is None:
                raise CustomerNoteNotFoundError("이 발신자의 메모가 아닙니다.")
            if row["retired_at"] is None:
                conn.execute("UPDATE customer_note SET retired_at = ? WHERE note_id = ?", (_now(), note_id))
                row = conn.execute("SELECT * FROM customer_note WHERE note_id = ?", (note_id,)).fetchone()
        return _note(row)

    # ------------------------------------------------------------ 이력 (모델에 보이는 것만)

    def sender_for_task(self, task_id: str) -> str | None:
        with self.db.get_conn() as conn:
            row = conn.execute(
                "SELECT m.sender FROM tasks t JOIN mails m ON m.uid = t.mail_uid WHERE t.task_id = ?", (task_id,),
            ).fetchone()
        return sender_key(row["sender"]) if row and row["sender"] else None

    def _other_inquiries(self, conn, task_id: str, key: str, days: int) -> list[dict]:
        cutoff = datetime.now().astimezone() - timedelta(days=days)
        rows = conn.execute(
            """
            SELECT m.received_at, m.subject, t.task_id, t.status,
                   ra.status AS analysis_status, ra.type_id, ra.reason
            FROM tasks t JOIN mails m ON m.uid = t.mail_uid
            LEFT JOIN request_analysis ra ON ra.task_id = t.task_id
            WHERE LOWER(TRIM(m.sender)) = ? AND t.task_id != ?
            """,
            (key, task_id),
        ).fetchall()
        types = {r["type_id"]: dict(r) for r in conn.execute("SELECT type_id, label, state, merged_into FROM request_type")}
        result = []
        for row in rows:
            received = parse_time(row["received_at"])
            if received is None or received < cutoff:
                continue  # 오래된 문의(끝난 입찰 조건 등)는 싣지 않는다. 시각을 읽을 수 없는 것도 뺀다
            label = None
            if row["analysis_status"] == "ok" and row["type_id"] is not None:
                type_row, hops = types.get(row["type_id"]), 0
                while type_row and type_row["state"] == "merged" and type_row["merged_into"] in types and hops < 10:
                    type_row, hops = types[type_row["merged_into"]], hops + 1
                label = type_row["label"] if type_row else None
            result.append({
                "received_at": row["received_at"],
                "subject": row["subject"] or "",
                "request_type": label,
                "reason": _one_line(row["reason"]) if row["analysis_status"] == "ok" and row["reason"] else None,
                "status": STATUS_LABELS.get(row["status"], DEFAULT_STATUS_LABEL),
                "_sort": received,
            })
        result.sort(key=lambda r: r["_sort"], reverse=True)
        for item in result:
            item.pop("_sort")
        return result

    def history_for_task(self, task_id: str, days: int, limit: int = 10) -> dict | None:
        """현재 작업의 발신자의 다른 문의(최근 것부터, days일 이내)와 사용 중인 메모. 작업이 없으면 None."""
        key = self.sender_for_task(task_id)
        if key is None:
            return None
        with self.db.get_conn() as conn:
            inquiries = self._other_inquiries(conn, task_id, key, days)
        notes = [{"text": n["text"], "created_at": n["created_at"]} for n in self.list_notes(key, include_retired=False)]
        return {"days": days, "inquiry_total": len(inquiries), "inquiries": inquiries[:max(1, limit)], "notes": notes}

    def counts_for_task(self, task_id: str, days: int) -> tuple[int, int]:
        """(이전 문의 수, 사용 중인 메모 수). 첫 user 메시지의 안내 줄에 건수만 쓴다."""
        key = self.sender_for_task(task_id)
        if key is None:
            return 0, 0
        with self.db.get_conn() as conn:
            inquiries = len(self._other_inquiries(conn, task_id, key, days))
            notes = conn.execute(
                "SELECT COUNT(*) FROM customer_note WHERE sender = ? AND retired_at IS NULL", (key,),
            ).fetchone()[0]
        return inquiries, notes
