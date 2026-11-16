"""문의 유형·문의 분석·DB 절차(skill_doc) 저장소 (지시서 I).

- request_type: 문의 유형. 기본 유형(seed)은 서버 시작 때 없을 때만 넣는다.
- request_analysis: 문의(task) 1건의 분석 결과. 다시 분석하면 덮어쓰고 attempts를 하나 늘린다.
- skill_doc: 생성·수정된 절차의 버전별 행. 승인된 행의 본문은 UPDATE하지 않는다 (고치려면 새 버전).
  사용 중인 절차 = 이름마다 approved·retired 행 중 가장 큰 version이 approved인 것.

approved로 바꾸는 곳은 approve_doc 하나뿐이고, 그것은 승인 API(app/routers/skills.py)만 부른다.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import uuid
from datetime import datetime

from repository.repo_connect import Database

logger = logging.getLogger(__name__)

TYPE_STATES = ("open", "no_skill_needed", "merged")
TYPE_ORIGINS = ("seed", "model")
DOC_STATUSES = ("generating", "draft", "approved", "rejected", "retired", "error")
# 승인 전 상태 (어떤 답변 실행에도 읽히지 않는다)
UNAPPROVED_STATUSES = ("generating", "draft", "error", "rejected")
DOC_ORIGINS = ("generated", "edited")
# 생성 중 행의 임시 이름 머리 (NAME_PATTERN에 맞지 않아 절차 이름과 겹칠 수 없다)
GENERATING_PREFIX = "_generating-"

# 분석 대상 task 상태 (답변이 만들어진 것. 생성 실패 failed는 대상이 아니다)
ANALYZABLE_STATUSES = ("drafted", "in_review", "sending", "sent", "send_failed", "send_unknown")
ANALYSIS_STATUSES = ("ok", "error")
# error 분석은 attempts가 이보다 작을 때만 다시 시도한다
MAX_ANALYSIS_ATTEMPTS = 3

LABEL_MAX = 30
DESCRIPTION_MAX = 200

# 실행 로그의 인자는 200자에서 잘릴 수 있다 (request_analysis.used_skills와 같은 복원 규칙).
_NAME_IN_ARGS = re.compile(r"""['"]name['"]\s*:\s*['"]([^'"]+)['"]""")

# 기본 유형 (지시서 I2 표)
SEED_TYPES = (
    {"label": "입찰 사양 대조", "description": "사양서 조건을 우리 제품과 조건별로 대조해 달라는 문의",
     "skill_name": "spec-compare", "state": "open"},
    {"label": "인증 자료 요청", "description": "인증서·인증번호·발급기관을 묻거나 인증 자료 묶음을 달라는 문의",
     "skill_name": "certification-bundle", "state": "open"},
    {"label": "단순 사실 조회", "description": "제품 한 가지 사실(무게, 포트 수 등)을 묻는 문의. 절차가 필요 없다",
     "skill_name": None, "state": "no_skill_needed"},
)


def _now() -> str:
    return datetime.now().isoformat()


def one_line(text: str | None, limit: int) -> str:
    """줄바꿈·연속 공백을 한 칸으로 줄이고 limit자에서 자른다."""
    return " ".join((text or "").split())[:limit]


def label_key(label: str | None) -> str:
    """유형 이름 비교 키 (공백·대소문자 무시)."""
    return "".join((label or "").split()).casefold()


def _loads(raw: str | None, default):
    if not raw:
        return default
    try:
        return json.loads(raw)
    except ValueError:
        return default


def _doc(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    doc = dict(row)
    doc["source_tasks"] = _loads(doc.pop("source_tasks_json", None), [])
    doc["check"] = _loads(doc.pop("check_json", None), None)
    return doc


class SkillRepository:

    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------ 문의 유형

    def ensure_seed_types(self) -> int:
        """기본 유형을 없을 때만 넣는다 (같은 label의 seed 행이 있으면 건너뛴다). 넣은 수를 돌려준다."""
        inserted = 0
        with self.db.transaction() as conn:
            existing = {label_key(r["label"]) for r in conn.execute("SELECT label FROM request_type WHERE origin = 'seed'")}
            for seed in SEED_TYPES:
                if label_key(seed["label"]) in existing:
                    continue
                now = _now()
                conn.execute(
                    """INSERT INTO request_type (label, description, skill_name, state, origin, created_at, updated_at)
                       VALUES (?, ?, ?, ?, 'seed', ?, ?)""",
                    (seed["label"], seed["description"], seed["skill_name"], seed["state"], now, now),
                )
                inserted += 1
        return inserted

    def get_type(self, type_id: int) -> dict | None:
        with self.db.get_conn() as conn:
            row = conn.execute("SELECT * FROM request_type WHERE type_id = ?", (type_id,)).fetchone()
        return dict(row) if row else None

    def resolve_type(self, type_id: int | None) -> dict | None:
        """merged 유형이면 merged_into를 따라간 최종 유형. 없는 유형이나 순환이면 None."""
        seen: set[int] = set()
        current = type_id
        while isinstance(current, int) and current not in seen:
            seen.add(current)
            found = self.get_type(current)
            if found is None:
                return None
            if found["state"] != "merged":
                return found
            current = found["merged_into"]
        return None

    def list_types(self, states: tuple[str, ...] | None = None, limit: int | None = None) -> list[dict]:
        """유형 목록과 분석 건수(case_count, ok 분석만). 건수 많은 순, 같으면 type_id 순."""
        where = f"WHERE t.state IN ({','.join('?' for _ in states)})" if states else ""
        sql = f"""
            SELECT t.*, COUNT(a.task_id) AS case_count
            FROM request_type t
            LEFT JOIN request_analysis a ON a.type_id = t.type_id AND a.status = 'ok'
            {where}
            GROUP BY t.type_id
            ORDER BY case_count DESC, t.type_id
            {"LIMIT ?" if limit else ""}
        """
        params = list(states or ()) + ([limit] if limit else [])
        with self.db.get_conn() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def find_type_by_label(self, label: str) -> dict | None:
        """label이 같은(공백·대소문자 무시) 유형. merged 유형은 옮겨 간 유형으로 돌려준다."""
        key = label_key(label)
        if not key:
            return None
        with self.db.get_conn() as conn:
            rows = conn.execute("SELECT type_id, label FROM request_type ORDER BY type_id").fetchall()
        for row in rows:
            if label_key(row["label"]) == key:
                return self.resolve_type(row["type_id"])
        return None

    def create_type(self, label: str, description: str, origin: str = "model") -> dict:
        """새 유형. label·description은 한 줄로 줄이고 길이를 자른다. 같은 label이 있으면 그 유형을 돌려준다."""
        if origin not in TYPE_ORIGINS:
            raise ValueError(f"알 수 없는 유형 출처: {origin}")
        label = one_line(label, LABEL_MAX)
        description = one_line(description, DESCRIPTION_MAX)
        if not label:
            raise ValueError("유형 이름이 비었습니다")
        existing = self.find_type_by_label(label)
        if existing is not None:
            return existing
        now = _now()
        with self.db.transaction() as conn:
            cursor = conn.execute(
                """INSERT INTO request_type (label, description, skill_name, state, origin, created_at, updated_at)
                   VALUES (?, ?, NULL, 'open', ?, ?, ?)""",
                (label, description, origin, now, now),
            )
            type_id = cursor.lastrowid
        return self.get_type(type_id)

    # ------------------------------------------------------------ DB 절차

    def get_doc(self, doc_id: int) -> dict | None:
        with self.db.get_conn() as conn:
            row = conn.execute("SELECT * FROM skill_doc WHERE doc_id = ?", (doc_id,)).fetchone()
        return _doc(row)

    def history(self, name: str) -> list[dict]:
        """이름의 모든 버전 (version 오름차순)."""
        with self.db.get_conn() as conn:
            rows = conn.execute("SELECT * FROM skill_doc WHERE name = ? ORDER BY version, doc_id", (name,)).fetchall()
        return [_doc(r) for r in rows]

    def next_version(self, name: str, conn: sqlite3.Connection | None = None) -> int:
        def query(c):
            row = c.execute("SELECT MAX(version) FROM skill_doc WHERE name = ?", (name,)).fetchone()
            return (row[0] or 0) + 1
        if conn is not None:
            return query(conn)
        with self.db.get_conn() as c:
            return query(c)

    def active_skill_docs(self) -> list[dict]:
        """사용 중인 DB 절차: 이름마다 approved·retired 중 가장 큰 version이 approved인 행. 이름 순."""
        with self.db.get_conn() as conn:
            rows = conn.execute(
                """
                SELECT d.* FROM skill_doc d
                JOIN (SELECT name, MAX(version) AS v FROM skill_doc
                      WHERE status IN ('approved', 'retired') GROUP BY name) m
                  ON m.name = d.name AND m.v = d.version
                WHERE d.status = 'approved'
                ORDER BY d.name
                """
            ).fetchall()
        return [_doc(r) for r in rows]

    def active_doc(self, name: str) -> dict | None:
        return next((d for d in self.active_skill_docs() if d["name"] == name), None)

    def latest_approved(self, name: str) -> dict | None:
        """이름의 마지막 승인본 (사용 중지됐어도 돌려준다)."""
        with self.db.get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM skill_doc WHERE name = ? AND status = 'approved' ORDER BY version DESC LIMIT 1", (name,),
            ).fetchone()
        return _doc(row)

    def insert_doc(
        self, *, name: str, version: int, status: str, origin: str, description: str | None = None,
        body: str | None = None, digest: str | None = None, type_id: int | None = None,
        source_tasks: list[str] | None = None, check: dict | None = None, model: str | None = None,
        error: str | None = None, conn: sqlite3.Connection | None = None,
    ) -> int:
        """skill_doc 한 행을 넣고 doc_id를 돌려준다. approved 행은 여기서 만들지 않는다."""
        if status not in DOC_STATUSES or status == "approved":
            raise ValueError(f"insert_doc로 만들 수 없는 상태: {status}")
        if origin not in DOC_ORIGINS:
            raise ValueError(f"알 수 없는 절차 출처: {origin}")
        params = (
            name, version, status, description, body, digest, type_id,
            json.dumps(source_tasks or [], ensure_ascii=False), origin,
            json.dumps(check, ensure_ascii=False) if check is not None else None, model, error, _now(),
        )
        sql = """INSERT INTO skill_doc (name, version, status, description, body, digest, type_id, source_tasks_json,
                                        origin, check_json, model, error, created_at)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
        if conn is not None:
            return conn.execute(sql, params).lastrowid
        with self.db.transaction() as c:
            return c.execute(sql, params).lastrowid

    def create_generating(self, type_id: int) -> int:
        """초안 생성 요청 행 (이름이 정해지기 전이라 임시 이름, version 0). 분석 스레드가 집어 생성한다."""
        return self.insert_doc(
            name=f"{GENERATING_PREFIX}{uuid.uuid4().hex[:12]}", version=0, status="generating", origin="generated",
            type_id=type_id,
        )

    def docs_for_type(self, type_id: int, statuses: tuple[str, ...] | None = None) -> list[dict]:
        where = f"AND status IN ({','.join('?' for _ in statuses)})" if statuses else ""
        with self.db.get_conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM skill_doc WHERE type_id = ? {where} ORDER BY doc_id DESC",
                (type_id, *(statuses or ())),
            ).fetchall()
        return [_doc(r) for r in rows]

    # ------------------------------------------------------------ 문의 분석

    def waiting_task_count(self) -> int:
        """답변을 기다리거나 만드는 중인 메일 작업 수 (있으면 분석·초안 생성은 쉰다: 로컬 모델을 메일 초안이 먼저 쓴다)."""
        with self.db.get_conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM tasks WHERE status IN ('pending', 'processing')").fetchone()[0]

    def tasks_to_analyze(self, limit: int, max_attempts: int = MAX_ANALYSIS_ATTEMPTS) -> list[str]:
        """분석할 task: 답변이 만들어진 상태이고 분석이 없거나, error 분석이 max_attempts번 미만인 것. 최근 것부터."""
        placeholders = ",".join("?" for _ in ANALYZABLE_STATUSES)
        with self.db.get_conn() as conn:
            rows = conn.execute(
                f"""
                SELECT t.task_id FROM tasks t
                LEFT JOIN request_analysis a ON a.task_id = t.task_id
                WHERE t.status IN ({placeholders})
                  AND (a.task_id IS NULL OR (a.status = 'error' AND a.attempts < ?))
                ORDER BY t.created_at DESC, t.rowid DESC
                LIMIT ?
                """,
                (*ANALYZABLE_STATUSES, max_attempts, limit),
            ).fetchall()
        return [r["task_id"] for r in rows]

    def analysis_input(self, task_id: str) -> dict | None:
        """분석 입력: 메일 제목·본문·첨부 파일명 (디스크 경로·이미지 데이터는 넣지 않는다)."""
        with self.db.get_conn() as conn:
            row = conn.execute(
                """SELECT t.task_id, t.status, m.uid, m.subject, m.body, m.received_at
                   FROM tasks t JOIN mails m ON m.uid = t.mail_uid WHERE t.task_id = ?""",
                (task_id,),
            ).fetchone()
            if row is None:
                return None
            files = conn.execute(
                "SELECT filename FROM mail_attachments WHERE mail_uid = ? ORDER BY attachment_id", (row["uid"],),
            ).fetchall()
        data = dict(row)
        data["attachments"] = [f["filename"] for f in files]
        return data

    def get_analysis(self, task_id: str) -> dict | None:
        with self.db.get_conn() as conn:
            row = conn.execute("SELECT * FROM request_analysis WHERE task_id = ?", (task_id,)).fetchone()
        if row is None:
            return None
        analysis = dict(row)
        analysis["used_skills"] = _loads(analysis.pop("used_skills_json", None), [])
        return analysis

    def save_analysis(
        self, task_id: str, *, status: str, type_id: int | None = None, covered_by: str | None = None,
        used_skills: list[str] | None = None, reason: str | None = None, model: str | None = None,
        error: str | None = None,
    ) -> dict:
        """분석 결과를 덮어쓴다. 다시 분석할 때마다 attempts가 하나 는다."""
        if status not in ANALYSIS_STATUSES:
            raise ValueError(f"알 수 없는 분석 상태: {status}")
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO request_analysis (task_id, status, type_id, covered_by, used_skills_json, reason, model,
                                              attempts, error, analyzed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT (task_id) DO UPDATE SET
                    status = excluded.status, type_id = excluded.type_id, covered_by = excluded.covered_by,
                    used_skills_json = excluded.used_skills_json, reason = excluded.reason, model = excluded.model,
                    attempts = request_analysis.attempts + 1, error = excluded.error, analyzed_at = excluded.analyzed_at
                """,
                (task_id, status, type_id, covered_by, json.dumps(used_skills or [], ensure_ascii=False),
                 reason, model, (error or None) and error[:2000], _now()),
            )
        return self.get_analysis(task_id)

    # ------------------------------------------------------------ 절차 초안 재료·생성

    def type_task_ids(self, type_id: int) -> list[str]:
        """이 유형으로 분석된(ok) task들."""
        with self.db.get_conn() as conn:
            rows = conn.execute(
                "SELECT task_id FROM request_analysis WHERE status = 'ok' AND type_id = ?", (type_id,),
            ).fetchall()
        return [r["task_id"] for r in rows]

    def draft_materials(self, type_id: int, limit: int = 5) -> list[dict]:
        """초안 재료 사례 (최대 limit건). 우선순위: 승인 발송된 건 → 반려 이력이 있는 건 → 그 밖, 같은 순위는 최근 것부터.

        각 사례: task_id, subject, status, received_at, body, attachments(파일명), answer,
        answer_kind(sent: 발송 기록 있음 · sent_legacy: 발송 기록 이전에 보냄 · unreviewed: 검토되지 않은 초안),
        rejects(반려 사유 목록), tool_calls(마지막 ok 실행의 [{tool, args_summary}])
        """
        with self.db.get_conn() as conn:
            rows = conn.execute(
                """
                SELECT t.task_id, t.status, t.draft_answer, t.created_at, m.uid, m.subject, m.body, m.received_at,
                       (SELECT body FROM task_send s WHERE s.task_id = t.task_id AND s.outcome = 'sent'
                        ORDER BY s.send_id DESC LIMIT 1) AS sent_body,
                       EXISTS (SELECT 1 FROM task_reviews r WHERE r.task_id = t.task_id AND r.action = 'reject') AS rejected
                FROM request_analysis a
                JOIN tasks t ON t.task_id = a.task_id
                JOIN mails m ON m.uid = t.mail_uid
                WHERE a.status = 'ok' AND a.type_id = ?
                """,
                (type_id,),
            ).fetchall()

            def rank(row) -> int:
                if row["sent_body"] is not None or row["status"] == "sent":
                    return 0
                return 1 if row["rejected"] else 2

            # 최근 순으로 먼저 정렬한 뒤 우선순위로 안정 정렬한다
            chosen = sorted(rows, key=lambda r: r["created_at"] or "", reverse=True)
            chosen = sorted(chosen, key=rank)[:limit]
            cases = []
            for row in chosen:
                files = conn.execute(
                    "SELECT filename FROM mail_attachments WHERE mail_uid = ? ORDER BY attachment_id", (row["uid"],),
                ).fetchall()
                rejects = conn.execute(
                    "SELECT reason FROM task_reviews WHERE task_id = ? AND action = 'reject' ORDER BY review_id",
                    (row["task_id"],),
                ).fetchall()
                run = conn.execute(
                    """SELECT tool_calls_json FROM run WHERE owner_type = 'task' AND owner_id = ? AND status = 'ok'
                       ORDER BY started_at DESC, rowid DESC LIMIT 1""",
                    (row["task_id"],),
                ).fetchone()
                if row["sent_body"] is not None:
                    answer, kind = row["sent_body"], "sent"
                elif row["status"] == "sent":
                    # 발송 기록(task_send) 이전에 보낸 작업: 마지막 초안이 발송본에 가장 가깝다
                    answer, kind = row["draft_answer"], "sent_legacy"
                else:
                    answer, kind = row["draft_answer"], "unreviewed"
                calls = _loads(run["tool_calls_json"] if run else None, [])
                cases.append({
                    "task_id": row["task_id"], "subject": row["subject"], "status": row["status"],
                    "received_at": row["received_at"], "body": row["body"] or "",
                    "attachments": [f["filename"] for f in files],
                    "answer": answer or "", "answer_kind": kind,
                    "rejects": [r["reason"] or "" for r in rejects],
                    "tool_calls": [{"tool": c.get("tool"), "args_summary": c.get("args_summary")}
                                   for c in calls if isinstance(c, dict)],
                })
        return cases

    def case_summaries(self, task_ids: list[str]) -> list[dict]:
        """화면용 재료 사례 요약 (task_id, subject, status, received_at, sent). 본문은 넣지 않는다. 요청 순서대로."""
        unique = list(dict.fromkeys(t for t in task_ids if isinstance(t, str)))
        if not unique:
            return []
        placeholders = ",".join("?" for _ in unique)
        with self.db.get_conn() as conn:
            rows = conn.execute(
                f"""SELECT t.task_id, t.status, m.subject, m.received_at,
                           EXISTS (SELECT 1 FROM task_send s WHERE s.task_id = t.task_id AND s.outcome = 'sent') AS sent_logged
                    FROM tasks t JOIN mails m ON m.uid = t.mail_uid WHERE t.task_id IN ({placeholders})""",
                unique,
            ).fetchall()
        by_id = {r["task_id"]: dict(r) for r in rows}
        result = []
        for task_id in unique:
            row = by_id.get(task_id)
            if row is None:
                continue
            row["sent"] = bool(row.pop("sent_logged")) or row["status"] == "sent"
            result.append(row)
        return result

    def generating_docs(self) -> list[dict]:
        """생성 대기 행 (오래된 것부터). 서버가 도중에 꺼졌어도 다음 시작 때 이어서 처리한다."""
        with self.db.get_conn() as conn:
            rows = conn.execute("SELECT * FROM skill_doc WHERE status = 'generating' ORDER BY doc_id").fetchall()
        return [_doc(r) for r in rows]

    def auto_draft_candidates(self, min_cases: int) -> list[dict]:
        """자동 초안 대상 유형: open이고 skill_name이 없고, 분석 건수가 min_cases 이상이며, 그 유형의 skill_doc이 한 번도 없음.

        건수 많은 순. (반려된 초안도 skill_doc 행이므로 반려 이력이 있는 유형은 자동으로 다시 만들지 않는다)
        """
        with self.db.get_conn() as conn:
            rows = conn.execute(
                """
                SELECT t.*, COUNT(a.task_id) AS case_count
                FROM request_type t
                JOIN request_analysis a ON a.type_id = t.type_id AND a.status = 'ok'
                WHERE t.state = 'open' AND t.skill_name IS NULL
                  AND NOT EXISTS (SELECT 1 FROM skill_doc d WHERE d.type_id = t.type_id)
                GROUP BY t.type_id
                HAVING COUNT(a.task_id) >= ?
                ORDER BY case_count DESC, t.type_id
                """,
                (min_cases,),
            ).fetchall()
        return [dict(r) for r in rows]

    def other_types_using_name(self, name: str, type_id: int | None) -> list[int]:
        """같은 이름의 DB 절차 행을 가진 다른 유형 (생성 중 행 제외)."""
        with self.db.get_conn() as conn:
            rows = conn.execute(
                """SELECT DISTINCT type_id FROM skill_doc
                   WHERE name = ? AND status <> 'generating' AND type_id IS NOT ?""",
                (name, type_id),
            ).fetchall()
        return [r["type_id"] for r in rows]

    def finish_generation(
        self, doc_id: int, *, status: str, name: str | None = None, description: str | None = None,
        body: str | None = None, digest: str | None = None, source_tasks: list[str] | None = None,
        check: dict | None = None, model: str | None = None, error: str | None = None,
    ) -> bool:
        """생성 중 행을 draft(이름·버전 확정) 또는 error로 바꾼다. 생성 중이 아니면 False (두 번 처리하지 않는다)."""
        if status not in ("draft", "error"):
            raise ValueError(f"생성 결과 상태가 아닙니다: {status}")
        with self.db.transaction() as conn:
            row = conn.execute("SELECT name, version FROM skill_doc WHERE doc_id = ? AND status = 'generating'",
                               (doc_id,)).fetchone()
            if row is None:
                return False
            new_name, version = row["name"], row["version"]
            if status == "draft":
                new_name, version = name, self.next_version(name, conn)
            cursor = conn.execute(
                """UPDATE skill_doc SET status = ?, name = ?, version = ?, description = ?, body = ?, digest = ?,
                                        source_tasks_json = ?, check_json = ?, model = ?, error = ?
                   WHERE doc_id = ? AND status = 'generating'""",
                (status, new_name, version, description, body, digest,
                 json.dumps(source_tasks or [], ensure_ascii=False),
                 json.dumps(check, ensure_ascii=False) if check is not None else None, model,
                 (error or None) and error[:2000], doc_id),
            )
            return cursor.rowcount == 1

    # ------------------------------------------------------------ 검토 (승인·반려·수정·사용 중지)

    def update_draft(self, doc_id: int, description: str, body: str, digest: str, check: dict) -> bool:
        """draft일 때만 설명·본문을 고친다 (origin='edited', 검사 결과 갱신). 고쳤으면 True."""
        with self.db.transaction() as conn:
            cursor = conn.execute(
                """UPDATE skill_doc SET description = ?, body = ?, digest = ?, check_json = ?, origin = 'edited'
                   WHERE doc_id = ? AND status = 'draft'""",
                (description, body, digest, json.dumps(check, ensure_ascii=False), doc_id),
            )
            return cursor.rowcount == 1

    def set_check(self, doc_id: int, check: dict) -> None:
        """검사 결과만 갱신한다 (승인 시점 재검사가 errors를 낸 draft). 상태·본문은 그대로."""
        with self.db.transaction() as conn:
            conn.execute("UPDATE skill_doc SET check_json = ? WHERE doc_id = ? AND status = 'draft'",
                         (json.dumps(check, ensure_ascii=False), doc_id))

    def approve_doc(self, doc_id: int, reviewer: str | None, note: str | None, check: dict) -> str:
        """초안을 승인한다. approved로 바꾸는 유일한 함수다 (승인 API만 부른다).

        상태 조건부 UPDATE라 두 번 눌러도 한 번만 승인된다. 돌려주는 값:
        ok | not_found | not_draft(이미 처리됨) | has_errors(검사 errors) | stale(같은 이름의 더 새 버전이 이미 승인·사용 중지됨)
        """
        if not check.get("ok") or check.get("errors"):
            return "has_errors"
        with self.db.transaction() as conn:
            row = conn.execute("SELECT name, version, status, type_id FROM skill_doc WHERE doc_id = ?", (doc_id,)).fetchone()
            if row is None:
                return "not_found"
            if row["status"] != "draft":
                return "not_draft"
            newest = conn.execute(
                "SELECT MAX(version) FROM skill_doc WHERE name = ? AND status IN ('approved', 'retired')", (row["name"],),
            ).fetchone()[0]
            if newest is not None and newest >= row["version"]:
                return "stale"
            cursor = conn.execute(
                """UPDATE skill_doc SET status = 'approved', check_json = ?, reviewed_at = ?, reviewed_by = ?, review_note = ?
                   WHERE doc_id = ? AND status = 'draft'""",
                (json.dumps(check, ensure_ascii=False), _now(), reviewer, (note or None) and note[:2000], doc_id),
            )
            if cursor.rowcount != 1:
                return "not_draft"
            if row["type_id"] is not None:
                conn.execute("UPDATE request_type SET skill_name = ?, updated_at = ? WHERE type_id = ?",
                             (row["name"], _now(), row["type_id"]))
        return "ok"

    def reject_doc(self, doc_id: int, reviewer: str | None, reason: str) -> str:
        """draft·error 초안을 반려한다. ok | not_found | not_rejectable"""
        with self.db.transaction() as conn:
            cursor = conn.execute(
                """UPDATE skill_doc SET status = 'rejected', reviewed_at = ?, reviewed_by = ?, review_note = ?
                   WHERE doc_id = ? AND status IN ('draft', 'error')""",
                (_now(), reviewer, reason[:2000], doc_id),
            )
            if cursor.rowcount == 1:
                return "ok"
            exists = conn.execute("SELECT 1 FROM skill_doc WHERE doc_id = ?", (doc_id,)).fetchone()
        return "not_rejectable" if exists else "not_found"

    def open_draft_for_name(self, name: str) -> dict | None:
        """같은 이름의 검토 대기 초안 중 마지막 승인·사용 중지 버전보다 새 것."""
        with self.db.get_conn() as conn:
            row = conn.execute(
                """SELECT * FROM skill_doc d WHERE d.name = ? AND d.status = 'draft'
                     AND d.version > COALESCE((SELECT MAX(version) FROM skill_doc
                                               WHERE name = d.name AND status IN ('approved', 'retired')), 0)
                   ORDER BY d.version DESC LIMIT 1""",
                (name,),
            ).fetchone()
        return _doc(row)

    def new_version_from_approved(self, name: str, check: dict, digest: str) -> int | None:
        """마지막 승인본을 복사해 새 버전 초안(origin='edited')을 만든다. 승인본이 없으면 None."""
        base = self.latest_approved(name)
        if base is None:
            return None
        with self.db.transaction() as conn:
            return self.insert_doc(
                name=name, version=self.next_version(name, conn), status="draft", origin="edited",
                description=base["description"], body=base["body"], digest=digest, type_id=base["type_id"],
                source_tasks=base["source_tasks"], check=check, model=base["model"], conn=conn,
            )

    def retire(self, name: str, reviewer: str | None, note: str | None = None) -> int | None:
        """사용 중인 DB 절차를 멈춘다: 새 retired 행을 만들고 유형의 skill_name을 비운다. 사용 중이 아니면 None."""
        with self.db.transaction() as conn:
            row = conn.execute(
                """SELECT d.* FROM skill_doc d
                   WHERE d.name = ? AND d.status = 'approved'
                     AND d.version = (SELECT MAX(version) FROM skill_doc WHERE name = ? AND status IN ('approved', 'retired'))""",
                (name, name),
            ).fetchone()
            if row is None:
                return None
            doc_id = self.insert_doc(
                name=name, version=self.next_version(name, conn), status="retired", origin=row["origin"],
                description=row["description"], body=row["body"], digest=row["digest"], type_id=row["type_id"],
                source_tasks=_loads(row["source_tasks_json"], []), model=row["model"], conn=conn,
            )
            conn.execute("UPDATE skill_doc SET reviewed_at = ?, reviewed_by = ?, review_note = ? WHERE doc_id = ?",
                         (_now(), reviewer, (note or None) and note[:2000], doc_id))
            conn.execute("UPDATE request_type SET skill_name = NULL, updated_at = ? WHERE skill_name = ?", (_now(), name))
            return doc_id

    def list_docs(self, statuses: tuple[str, ...]) -> list[dict]:
        placeholders = ",".join("?" for _ in statuses)
        with self.db.get_conn() as conn:
            rows = conn.execute(
                f"""SELECT d.*, t.label AS type_label FROM skill_doc d
                    LEFT JOIN request_type t ON t.type_id = d.type_id
                    WHERE d.status IN ({placeholders}) ORDER BY d.doc_id DESC""",
                statuses,
            ).fetchall()
        return [_doc(r) for r in rows]

    # ------------------------------------------------------------ 유형 관리

    def set_type_state(self, type_id: int, state: str) -> str:
        """open ↔ no_skill_needed. ok | not_found | merged | same"""
        if state not in ("open", "no_skill_needed"):
            raise ValueError(f"바꿀 수 없는 상태: {state}")
        with self.db.transaction() as conn:
            row = conn.execute("SELECT state FROM request_type WHERE type_id = ?", (type_id,)).fetchone()
            if row is None:
                return "not_found"
            if row["state"] == "merged":
                return "merged"
            if row["state"] == state:
                return "same"
            conn.execute("UPDATE request_type SET state = ?, updated_at = ? WHERE type_id = ? AND state <> 'merged'",
                         (state, _now(), type_id))
        return "ok"

    def merge_type(self, type_id: int, into: int) -> str:
        """이 유형의 분석을 다른 유형으로 옮기고 merged로 둔다. ok | not_found | same | merged | target_merged"""
        if type_id == into:
            return "same"
        with self.db.transaction() as conn:
            source = conn.execute("SELECT state FROM request_type WHERE type_id = ?", (type_id,)).fetchone()
            target = conn.execute("SELECT state FROM request_type WHERE type_id = ?", (into,)).fetchone()
            if source is None or target is None:
                return "not_found"
            if source["state"] == "merged":
                return "merged"
            if target["state"] == "merged":
                return "target_merged"
            conn.execute("UPDATE request_analysis SET type_id = ? WHERE type_id = ?", (into, type_id))
            conn.execute("UPDATE request_type SET state = 'merged', merged_into = ?, updated_at = ? WHERE type_id = ?",
                         (into, _now(), type_id))
        return "ok"

    def recent_cases(self, type_id: int, limit: int = 5) -> list[dict]:
        with self.db.get_conn() as conn:
            rows = conn.execute(
                """SELECT t.task_id, t.status, m.subject, m.received_at FROM request_analysis a
                   JOIN tasks t ON t.task_id = a.task_id JOIN mails m ON m.uid = t.mail_uid
                   WHERE a.status = 'ok' AND a.type_id = ? ORDER BY t.created_at DESC, t.rowid DESC LIMIT ?""",
                (type_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_analysis(self, type_id: int | None = None, limit: int | None = None) -> list[dict]:
        """분석된 문의 (최근 것부터): 제목·상태·유형·covered_by·실제 사용 절차. 본문은 넣지 않는다."""
        where = "WHERE a.type_id = ?" if type_id is not None else ""
        params: list = [type_id] if type_id is not None else []
        sql = f"""SELECT a.*, t.status AS task_status, m.subject, m.received_at, rt.label AS type_label
                  FROM request_analysis a
                  JOIN tasks t ON t.task_id = a.task_id JOIN mails m ON m.uid = t.mail_uid
                  LEFT JOIN request_type rt ON rt.type_id = a.type_id
                  {where} ORDER BY t.created_at DESC, t.rowid DESC"""
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        with self.db.get_conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["used_skills"] = _loads(item.pop("used_skills_json", None), [])
            item["mismatch"] = bool(item["covered_by"]) and item["covered_by"] not in item["used_skills"]
            result.append(item)
        return result

    def skill_usage_since(self, since: str) -> dict[str, int]:
        """since 이후 실행에서 절차별로 쓴 실행 수 (서버 적용 + load_skill 호출, 한 실행에 한 번)."""
        counts: dict[str, int] = {}
        with self.db.get_conn() as conn:
            rows = conn.execute("SELECT skills_json, tool_calls_json FROM run WHERE started_at >= ?", (since,)).fetchall()
        for row in rows:
            names = {ref.get("name") for ref in _loads(row["skills_json"], []) if isinstance(ref, dict)}
            for call in _loads(row["tool_calls_json"], []):
                if isinstance(call, dict) and call.get("tool") == "load_skill":
                    summary = call.get("args_summary") or ""
                    name = None
                    try:
                        args = json.loads(summary)
                        name = args.get("name") if isinstance(args, dict) else None
                    except (ValueError, TypeError):
                        match = _NAME_IN_ARGS.search(summary) if isinstance(summary, str) else None
                        name = match.group(1) if match else None
                    if isinstance(name, str) and name:
                        names.add(name[:80])
            for name in names - {None}:
                counts[name] = counts.get(name, 0) + 1
        return counts
