"""질의응답 로그(qa_log) 저장·평가·조회.

질의응답 화면의 질문마다 한 줄을 남기고(app/routers/questions.py), 화면의 좋음/아쉬움 평가를 그 줄에 붙인다.
그래프 검색을 넣기 전후 답변을 비교하려는 기록이라 답변 본문·출처·도구 호출까지 그대로 남긴다.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime

from repository.repo_connect import Database

RATINGS = ("good", "bad")
COMMENT_MAX = 2000

_LIST_COLUMNS = """log_id, asked_at, client_ip, endpoint, mode, question, attachments_json, status, answer, error,
                   sources_json, validation_json, run_id, model, prompt_id, tools_available, tool_calls_json,
                   tokens_in, tokens_out, duration_ms, rating, comment, rated_at"""
_JSON_COLUMNS = ("attachments_json", "sources_json", "validation_json", "tools_available", "tool_calls_json")


def _now() -> str:
    return datetime.now().isoformat()


def _dumps(value) -> str | None:
    return None if value is None else json.dumps(value, ensure_ascii=False, default=str)


def _loads(raw: str | None):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


class QaLogRepository:

    def __init__(self, db: Database):
        self.db = db

    def insert(
        self,
        *,
        endpoint: str,
        mode: str,
        question: str,
        status: str,
        duration_ms: float,
        client_ip: str = "",
        attachments: list[dict] | None = None,
        answer: str | None = None,
        error: str | None = None,
        sources: list[dict] | None = None,
        validation: dict | None = None,
        run_id: str | None = None,
        model: str | None = None,
        prompt_id: int | None = None,
        tools_available: list[str] | None = None,
        tool_calls_json: str | None = None,
        tokens_in: int | None = None,
        tokens_out: int | None = None,
    ) -> str:
        """한 줄을 넣고 log_id를 돌려준다. tool_calls_json은 run 테이블 값을 그대로 받는다."""
        log_id = "q" + uuid.uuid4().hex[:12]
        with self.db.transaction() as conn:
            conn.execute(
                """INSERT INTO qa_log (log_id, asked_at, client_ip, endpoint, mode, question, attachments_json, status,
                                       answer, error, sources_json, validation_json, run_id, model, prompt_id,
                                       tools_available, tool_calls_json, tokens_in, tokens_out, duration_ms)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    log_id, _now(), client_ip, endpoint, mode, question, _dumps(attachments), status, answer,
                    (error or None) and error[:2000], _dumps(sources), _dumps(validation), run_id, model, prompt_id,
                    _dumps(tools_available), tool_calls_json, tokens_in, tokens_out, round(duration_ms, 1),
                ),
            )
        return log_id

    def set_feedback(self, log_id: str, rating: str | None, comment: str | None) -> bool:
        """평가를 바꾼다. rating=None이면 평가를 지운다. 없는 log_id면 False."""
        if rating is not None and rating not in RATINGS:
            raise ValueError(f"평가 값이 아닙니다: {rating}")
        comment = (comment or "").strip()[:COMMENT_MAX] or None
        rated_at = _now() if rating is not None or comment else None
        with self.db.transaction() as conn:
            cursor = conn.execute(
                "UPDATE qa_log SET rating = ?, comment = ?, rated_at = ? WHERE log_id = ?",
                (rating, comment, rated_at, log_id),
            )
        return cursor.rowcount > 0

    def get(self, log_id: str) -> dict | None:
        with self.db.get_conn() as conn:
            row = conn.execute(f"SELECT {_LIST_COLUMNS} FROM qa_log WHERE log_id = ?", (log_id,)).fetchone()
        return _row(row) if row else None

    def list_logs(self, *, since: str | None = None, until: str | None = None, rating: str | None = None) -> list[dict]:
        """기간(asked_at 문자열 비교, until은 포함하지 않음)과 평가로 거른 목록 (오래된 순).

        rating: 'good' | 'bad' | 'rated'(평가된 것 전부) | 'unrated' | None(전부)
        """
        where, params = [], []
        if since:
            where.append("asked_at >= ?")
            params.append(since)
        if until:
            where.append("asked_at < ?")
            params.append(until)
        if rating in RATINGS:
            where.append("rating = ?")
            params.append(rating)
        elif rating == "rated":
            where.append("rating IS NOT NULL")
        elif rating == "unrated":
            where.append("rating IS NULL")
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        with self.db.get_conn() as conn:
            rows = conn.execute(
                f"SELECT {_LIST_COLUMNS} FROM qa_log {clause} ORDER BY asked_at, rowid", params,
            ).fetchall()
        return [_row(r) for r in rows]


def _row(row) -> dict:
    """JSON 열을 풀어 attachments·sources·validation·tools_available·tool_calls 키로 돌려준다."""
    item = dict(row)
    for column in _JSON_COLUMNS:
        key = column.removesuffix("_json")
        item[key] = _loads(item.pop(column))
    return item
