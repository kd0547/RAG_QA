"""고객방: 발신자별 문의·초안·반려·발송 조회 (화면 전용, 조회만).

발신자 키는 LOWER(TRIM(mails.sender)). 대소문자만 다른 주소는 같은 고객이다. 도메인 단위로는 묶지 않는다.
모델 입력과 분리한다: agent/, tools/, mail/email_service.py는 이 모듈을 임포트하지 않는다.

시각: mails.received_at은 시간대가 붙은 값과 안 붙은 값이 섞여 있고, run·task_reviews·tasks·task_send는
서버 지역 시각(시간대 없음)이다. 문자열로 비교하지 않고 datetime으로 바꿔 비교한다 (시간대 없으면 서버 지역 시각).
응답에는 저장된 문자열을 그대로 내보낸다.

내보내지 않는 것: 디스크 경로(stored_path, 발송 첨부 path), 이미지 data URL, 도구 호출, 근거 본문.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from repository.repo_connect import Database

logger = logging.getLogger(__name__)

# 담당자 확인이 필요한 상태 (프론트 format.ts REVIEW_STATUSES와 같은 집합)
NEEDS_REVIEW_STATUSES = ("drafted", "in_review", "sending", "send_failed", "send_unknown", "failed")
# 본문 필드(body, answer, reason)를 이 길이에서 자른다
TEXT_LIMIT = 8000
# run_failed 사건의 오류 앞부분
ERROR_PREVIEW_CHARS = 200
# 같은 시각일 때 사건 순서
EVENT_ORDER = {"draft": 0, "run_failed": 1, "reject": 2, "retry": 3, "send": 4, "mark_sent": 5}

_MIN_TIME = datetime.min.replace(tzinfo=timezone.utc)


def sender_key(sender: str) -> str:
    return (sender or "").strip().lower()


def parse_time(value: str | None) -> datetime | None:
    """저장된 시각 문자열 → 시간대 있는 datetime. 시간대가 없으면 서버 지역 시각으로 본다. 읽을 수 없으면 None."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).strip())
    except ValueError:
        logger.warning("시각 문자열을 읽지 못함: %r", value)
        return None
    # naive.astimezone()은 그 값을 서버 지역 시각으로 해석해 시간대를 붙인다
    return parsed.astimezone() if parsed.tzinfo is None else parsed


def _time_key(value: str | None) -> datetime:
    return parse_time(value) or _MIN_TIME


def _cut(text: str | None) -> tuple[str | None, bool]:
    if text is None:
        return None, False
    if len(text) > TEXT_LIMIT:
        return text[:TEXT_LIMIT], True
    return text, False


def _placeholders(values) -> str:
    return ",".join("?" for _ in values)


class CustomerRepository:
    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------ 목록

    def list_customers(self, q: str | None = None, limit: int = 50, offset: int = 0) -> dict:
        """발신자 목록 (마지막 수신 시각이 최근인 순서).

        q: 발신자 주소나 제목의 부분 일치 (대소문자 무시). 제목이 맞는 메일이 하나라도 있으면 그 고객을 넣는다.
        건수·상태는 q와 관계없이 그 고객의 전체 메일 기준이다.
        """
        with self.db.get_conn() as conn:
            rows = conn.execute(
                """
                SELECT m.uid, m.sender, m.subject, m.received_at, t.task_id, t.status
                FROM mails m LEFT JOIN tasks t ON t.mail_uid = m.uid
                """
            ).fetchall()

        customers: dict[str, dict] = {}
        for row in rows:
            key = sender_key(row["sender"])
            customer = customers.setdefault(key, {
                "sender": key, "mails": set(), "first": None, "last": None,
                "status_counts": {}, "needs_review": 0, "subjects": [],
            })
            customer["mails"].add(row["uid"])
            customer["subjects"].append(row["subject"] or "")
            received = _time_key(row["received_at"])
            if customer["first"] is None or received < _time_key(customer["first"]["received_at"]):
                customer["first"] = row
            if customer["last"] is None or received >= _time_key(customer["last"]["received_at"]):
                customer["last"] = row
            if row["status"]:
                counts = customer["status_counts"]
                counts[row["status"]] = counts.get(row["status"], 0) + 1
                if row["status"] in NEEDS_REVIEW_STATUSES:
                    customer["needs_review"] += 1

        needle = (q or "").strip().lower()
        if needle:
            customers = {
                key: c for key, c in customers.items()
                if needle in key or any(needle in s.lower() for s in c["subjects"])
            }

        ordered = sorted(customers.values(), key=lambda c: _time_key(c["last"]["received_at"]), reverse=True)
        page = ordered[offset:offset + limit]
        return {
            "items": [
                {
                    "sender": c["sender"],
                    "mail_count": len(c["mails"]),
                    "first_received_at": c["first"]["received_at"],
                    "last_received_at": c["last"]["received_at"],
                    "last_subject": c["last"]["subject"],
                    "last_task_id": c["last"]["task_id"],
                    "status_counts": c["status_counts"],
                    "needs_review": c["needs_review"],
                }
                for c in page
            ],
            "total": len(ordered),
            "limit": limit,
            "offset": offset,
        }

    # ------------------------------------------------------------ 타임라인

    def timeline(self, sender: str, limit: int = 20, before: str | None = None) -> dict | None:
        """한 발신자의 문의 묶음. 발신자의 메일이 없으면 None.

        최근 limit개 문의를 고르고 수신 시각 오름차순으로 돌려준다. before가 있으면 그 시각보다 이전 문의만.
        실행·검토·발송·첨부는 고른 문의에 대해 IN (…) 한 번씩 조회한다.
        """
        key = sender_key(sender)
        with self.db.get_conn() as conn:
            inquiries = conn.execute(
                """
                SELECT m.uid, m.subject, m.body, m.received_at,
                       t.task_id, t.status, t.draft_answer, t.updated_at
                FROM mails m LEFT JOIN tasks t ON t.mail_uid = m.uid
                WHERE LOWER(TRIM(m.sender)) = ?
                """,
                (key,),
            ).fetchall()
            if not inquiries:
                return None

            newest_first = sorted(inquiries, key=lambda r: _time_key(r["received_at"]), reverse=True)
            if before:
                cursor = parse_time(before)
                if cursor is None:
                    raise ValueError(f"before 시각을 읽을 수 없습니다: {before}")
                newest_first = [r for r in newest_first if _time_key(r["received_at"]) < cursor]
            selected = newest_first[:limit]
            has_more = len(newest_first) > limit

            task_ids = [r["task_id"] for r in selected if r["task_id"]]
            mail_uids = [r["uid"] for r in selected]
            runs = self._by_key(conn, "run_id, owner_id, label, status, started_at, ended_at, error, answer, skills_json",
                                "run", "owner_type = 'task' AND owner_id", task_ids, "owner_id")
            reviews = self._by_key(conn, "review_id, task_id, action, reason, requeue, reviewed_at",
                                   "task_reviews", "task_id", task_ids, "task_id")
            sends = self._by_key(conn, "send_id, task_id, body, recipient, attachments_json, attempted_at, outcome, detail",
                                 "task_send", "task_id", task_ids, "task_id")
            attachments = self._by_key(conn, "attachment_id, mail_uid, filename, type",
                                       "mail_attachments", "mail_uid", mail_uids, "mail_uid")

        items = [
            self._inquiry(row, runs.get(row["task_id"], []), reviews.get(row["task_id"], []),
                          sends.get(row["task_id"], []), attachments.get(row["uid"], []))
            for row in reversed(selected)
        ]
        return {
            "sender": key,
            "total": len(inquiries),
            "next_before": selected[-1]["received_at"] if has_more and selected else None,
            "items": items,
        }

    @staticmethod
    def _by_key(conn, columns: str, table: str, where: str, values: list, key: str) -> dict[str, list[dict]]:
        """WHERE <where> IN (…) 한 번으로 읽어 key별로 묶는다."""
        if not values:
            return {}
        rows = conn.execute(
            f"SELECT {columns} FROM {table} WHERE {where} IN ({_placeholders(values)})", values,
        ).fetchall()
        grouped: dict[str, list[dict]] = {}
        for row in rows:
            grouped.setdefault(row[key], []).append(dict(row))
        return grouped

    def _inquiry(self, row, runs: list[dict], reviews: list[dict], sends: list[dict], attachments: list[dict]) -> dict:
        body, truncated = _cut(row["body"] or "")
        received = {
            "type": "received", "at": row["received_at"], "body": body, "truncated": truncated,
            "attachments": [
                {"filename": a["filename"], "type": a["type"]}
                for a in sorted(attachments, key=lambda a: a["attachment_id"])
            ],
        }
        events = self._run_events(runs, row["draft_answer"]) + self._review_events(reviews) + self._send_events(sends)

        inferred: list[dict] = []
        if not runs and row["draft_answer"]:
            answer, cut = _cut(row["draft_answer"])
            inferred.append({
                "type": "draft", "at": None, "run_id": None, "label": None, "answer": answer, "truncated": cut,
                "text_source": "task", "current": True, "inferred": True, "skills": [],
            })
        if not sends and row["status"] == "sent":
            events.append({
                "type": "send", "at": row["updated_at"], "outcome": "sent", "recipient": None, "body": None,
                "truncated": False, "attachments": [], "detail": None, "inferred": True,
            })

        events.sort(key=lambda e: (_time_key(e["at"]), EVENT_ORDER[e["type"]]))
        return {
            "task_id": row["task_id"],
            "subject": row["subject"],
            "status": row["status"],
            "received_at": row["received_at"],
            "events": [received, *inferred, *events],
        }

    @staticmethod
    def _run_events(runs: list[dict], draft_answer: str | None) -> list[dict]:
        ordered = sorted(runs, key=lambda r: (_time_key(r["started_at"]), r["run_id"]))
        ok_runs = [r for r in ordered if r["status"] == "ok"]
        last_ok = ok_runs[-1]["run_id"] if ok_runs else None
        events = []
        for run in ordered:
            if run["status"] == "ok":
                current = run["run_id"] == last_ok
                if run["answer"] is not None:
                    answer, source = run["answer"], "run"
                elif current and draft_answer:
                    answer, source = draft_answer, "task"
                else:
                    answer, source = None, None
                answer, cut = _cut(answer)
                events.append({
                    "type": "draft", "at": run["ended_at"], "run_id": run["run_id"], "label": run["label"],
                    "answer": answer, "truncated": cut, "text_source": source, "current": current,
                    "inferred": False, "skills": _skills(run["skills_json"]),
                })
            elif run["status"] in ("error", "limit"):
                events.append({
                    "type": "run_failed", "at": run["ended_at"], "run_id": run["run_id"], "label": run["label"],
                    "status": run["status"], "error": (run["error"] or "")[:ERROR_PREVIEW_CHARS] or None,
                })
            # running(진행 중) 실행은 사건으로 내보내지 않는다. 문의 상태(processing)로 보인다
        return events

    @staticmethod
    def _review_events(reviews: list[dict]) -> list[dict]:
        events = []
        for review in reviews:
            action = review["action"]
            event = {"type": action, "at": review["reviewed_at"], "review_id": review["review_id"]}
            if action in ("reject", "mark_sent"):
                reason, cut = _cut(review["reason"])
                event.update(reason=reason, truncated=cut)
            if action == "reject":
                event["requeue"] = bool(review["requeue"])
            if action in EVENT_ORDER:
                events.append(event)
        return events

    @staticmethod
    def _send_events(sends: list[dict]) -> list[dict]:
        events = []
        for send in sorted(sends, key=lambda s: s["send_id"]):
            body, cut = _cut(send["body"])
            events.append({
                "type": "send", "at": send["attempted_at"], "outcome": send["outcome"] or "sending",
                "recipient": send["recipient"], "body": body, "truncated": cut,
                "attachments": _send_attachment_names(send["attachments_json"]),
                "detail": send["detail"], "inferred": False,
            })
        return events


def _skills(raw: str | None) -> list[dict]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except ValueError:
        return []
    return [{"name": s.get("name"), "digest": s.get("digest")} for s in value if isinstance(s, dict)] \
        if isinstance(value, list) else []


def _send_attachment_names(raw: str | None) -> list[str]:
    """발송 첨부는 파일명만 (저장 경로는 내보내지 않는다)."""
    try:
        value = json.loads(raw or "[]")
    except ValueError:
        return []
    names = []
    for item in value if isinstance(value, list) else []:
        if isinstance(item, dict) and item.get("filename"):
            names.append(str(item["filename"]))
        elif isinstance(item, str):
            names.append(item.replace("\\", "/").rsplit("/", 1)[-1])
    return names
