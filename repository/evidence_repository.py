"""근거(evidence)·에이전트 실행(run)·근거 사용(evidence_use) 저장소.

에이전트 도구가 문서 페이지·검색 청크·첨부를 읽을 때마다 근거로 등록하고 짧은 ID(e…)를 돌려준다.
답변은 이 ID로 인용하고, 서버는 ID의 소유자(task/session)와 이번 실행에서 실제로 읽었는지를 검증한다.
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime

from repository.repo_connect import Database

logger = logging.getLogger(__name__)

OWNER_TYPES = ("task", "session")
ORIGIN_TYPES = ("file_page", "chunk", "attachment", "spec_value")
USE_ACTIONS = ("read", "rerank", "cite")
RUN_STATUSES = ("running", "ok", "error", "limit")

_EVIDENCE_COLUMNS = """e.evidence_id, e.owner_type, e.owner_id, e.origin_type, e.file_id, e.page_id, e.page,
                       e.attachment_id, e.spec_value_id, e.revision, e.content_hash, e.text, e.source_name, e.created_at"""


def _now() -> str:
    return datetime.now().isoformat()


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _new_id(prefix: str, length: int = 8) -> str:
    return prefix + uuid.uuid4().hex[:length]


class EvidenceRepository:

    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------ 근거

    def register(
        self,
        owner_type: str,
        owner_id: str,
        origin_type: str,
        text: str,
        *,
        file_id: str | None = None,
        page_id: int | None = None,
        page: int | None = None,
        attachment_id: int | None = None,
        spec_value_id: int | None = None,
        revision: str | None = None,
        source_name: str | None = None,
    ) -> str:
        """근거를 등록하고 ID를 돌려준다.

        같은 소유자·원천·파일·페이지 행·페이지·첨부·revision·본문이면 기존 ID를 돌려준다.
        (본문 해시까지 보는 이유: 검색 청크는 한 파일·페이지에 여러 개이고, 검수 저장이 1초 안에 두 번 일어나면
        file_page.updated_at이 같아도 본문이 다를 수 있다)
        """
        if owner_type not in OWNER_TYPES:
            raise ValueError(f"알 수 없는 소유자 종류: {owner_type}")
        if origin_type not in ORIGIN_TYPES:
            raise ValueError(f"알 수 없는 근거 원천: {origin_type}")
        digest = content_hash(text)
        key = (owner_type, owner_id, origin_type, file_id, page_id, page, attachment_id, spec_value_id, revision, digest)
        with self.db.transaction() as conn:
            row = conn.execute(
                """
                SELECT evidence_id FROM evidence
                WHERE owner_type = ? AND owner_id = ? AND origin_type = ?
                  AND file_id IS ? AND page_id IS ? AND page IS ? AND attachment_id IS ? AND spec_value_id IS ?
                  AND revision IS ? AND content_hash = ?
                LIMIT 1
                """,
                key,
            ).fetchone()
            if row is not None:
                return row["evidence_id"]
            evidence_id = _new_id("e")
            conn.execute(
                """
                INSERT INTO evidence (evidence_id, owner_type, owner_id, origin_type, file_id, page_id, page,
                                      attachment_id, spec_value_id, revision, content_hash, text, source_name, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (evidence_id, *key[:-1], digest, text, source_name, _now()),
            )
            return evidence_id

    def get(self, evidence_id: str, owner_type: str | None = None, owner_id: str | None = None) -> dict | None:
        """근거 하나. 소유자를 주면 다른 소유자의 근거는 None."""
        found = self.get_many([evidence_id], owner_type, owner_id)
        return found[0] if found else None

    def get_many(self, ids: list[str], owner_type: str | None = None, owner_id: str | None = None) -> list[dict]:
        """근거 여러 개를 요청 순서대로. 없는 ID와 (소유자를 준 경우) 다른 소유자의 ID는 빠진다."""
        unique = list(dict.fromkeys(i for i in ids if isinstance(i, str)))
        if not unique:
            return []
        placeholders = ",".join("?" for _ in unique)
        with self.db.get_conn() as conn:
            rows = conn.execute(
                f"SELECT {_EVIDENCE_COLUMNS} FROM evidence e WHERE e.evidence_id IN ({placeholders})", unique,
            ).fetchall()
        by_id = {row["evidence_id"]: dict(row) for row in rows}
        result = []
        for evidence_id in unique:
            row = by_id.get(evidence_id)
            if row is None:
                continue
            if owner_type is not None and (row["owner_type"], row["owner_id"]) != (owner_type, owner_id):
                continue
            result.append(row)
        return result

    def list_for_owner(self, owner_type: str, owner_id: str) -> list[dict]:
        """소유자의 근거 전체 (등록 순서)."""
        with self.db.get_conn() as conn:
            rows = conn.execute(
                f"""SELECT {_EVIDENCE_COLUMNS} FROM evidence e
                    WHERE e.owner_type = ? AND e.owner_id = ? ORDER BY e.created_at, e.rowid""",
                (owner_type, owner_id),
            ).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------ 사용 기록

    def record_use(self, run_id: str, evidence_id: str, action: str) -> None:
        if action not in USE_ACTIONS:
            raise ValueError(f"알 수 없는 근거 사용: {action}")
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO evidence_use (run_id, evidence_id, action, at) VALUES (?, ?, ?, ?)",
                (run_id, evidence_id, action, _now()),
            )

    def uses_for_run(self, run_id: str, action: str | None = None) -> list[dict]:
        """실행에서 쓴 근거 (처음 쓴 순서, 근거마다 한 번). 각 항목은 근거 행 + action + at."""
        sql = f"""
            SELECT {_EVIDENCE_COLUMNS}, u.action, u.at
            FROM evidence_use u JOIN evidence e ON e.evidence_id = u.evidence_id
            WHERE u.run_id = ? {"AND u.action = ?" if action else ""}
            ORDER BY u.rowid
        """
        params = (run_id, action) if action else (run_id,)
        with self.db.get_conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        seen: set[str] = set()
        result = []
        for row in rows:
            if row["evidence_id"] in seen:
                continue
            seen.add(row["evidence_id"])
            result.append(dict(row))
        return result

    def uses_for_owner(self, owner_type: str, owner_id: str, action: str) -> list[dict]:
        """소유자의 모든 실행에서 쓴 근거 (처음 쓴 순서, 근거마다 한 번).

        메일은 소유자 = 대화(task:{task_id})라서, 반려 후 재작성 실행이 1차에서 읽은 근거를 다시 읽지 않고 인용할 수 있다.
        """
        with self.db.get_conn() as conn:
            rows = conn.execute(
                f"""
                SELECT {_EVIDENCE_COLUMNS}, u.action, u.at
                FROM evidence_use u
                JOIN run r ON r.run_id = u.run_id
                JOIN evidence e ON e.evidence_id = u.evidence_id
                WHERE r.owner_type = ? AND r.owner_id = ? AND u.action = ?
                ORDER BY u.rowid
                """,
                (owner_type, owner_id, action),
            ).fetchall()
        seen: set[str] = set()
        result = []
        for row in rows:
            if row["evidence_id"] in seen:
                continue
            seen.add(row["evidence_id"])
            result.append(dict(row))
        return result

    # ------------------------------------------------------------ 실행

    def start_run(self, owner_type: str, owner_id: str, model: str | None, prompt_id: int | None) -> str:
        run_id = _new_id("r", 12)
        with self.db.transaction() as conn:
            conn.execute(
                """INSERT INTO run (run_id, owner_type, owner_id, model, prompt_id, started_at, status)
                   VALUES (?, ?, ?, ?, ?, ?, 'running')""",
                (run_id, owner_type, owner_id, model, prompt_id, _now()),
            )
        return run_id

    def finish_run(
        self,
        run_id: str,
        status: str,
        tool_calls: list | None,
        tokens_in: int | None,
        tokens_out: int | None,
        error: str | None = None,
    ) -> None:
        if status not in RUN_STATUSES or status == "running":
            raise ValueError(f"실행 종료 상태가 아닙니다: {status}")
        with self.db.transaction() as conn:
            conn.execute(
                """UPDATE run SET status = ?, ended_at = ?, tool_calls_json = ?, tokens_in = ?, tokens_out = ?, error = ?
                   WHERE run_id = ?""",
                (status, _now(), json.dumps(tool_calls or [], ensure_ascii=False), tokens_in, tokens_out,
                 (error or None) and error[:2000], run_id),
            )

    def get_run(self, run_id: str) -> dict | None:
        with self.db.get_conn() as conn:
            row = conn.execute("SELECT * FROM run WHERE run_id = ?", (run_id,)).fetchone()
        return dict(row) if row else None

    def latest_run(self, owner_type: str, owner_id: str) -> dict | None:
        """소유자의 가장 최근 실행 (검토 화면의 '에이전트가 한 일'용)."""
        with self.db.get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM run WHERE owner_type = ? AND owner_id = ? ORDER BY started_at DESC, rowid DESC LIMIT 1",
                (owner_type, owner_id),
            ).fetchone()
        return dict(row) if row else None
