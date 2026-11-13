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

LABEL_MAX = 30
DESCRIPTION_MAX = 200

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
