"""답변 지침(시스템 프롬프트) 저장소. 여러 개를 저장하고 그중 하나만 선택해 쓴다.

- 기본 프롬프트: is_default = 1 인 행. 서버 시작 시 없으면 ensure_default()가 넣는다.
- 선택된 프롬프트: is_selected = 1 인 행. 에이전트는 이 프롬프트를 쓴다.
- 둘 다 하나뿐인 것은 DB가 보장한다 (schema.sql의 idx_prompt_default, idx_prompt_selected).
"""
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime

from agent.prompt import SYSTEM_PROMPT_TEMPLATE
from repository.repo_connect import Database

logger = logging.getLogger(__name__)

# 기본 프롬프트의 처음 내용이자 백업. DB에 기본 프롬프트가 없거나 DB를 못 읽을 때 이 원문을 쓴다.
# $aliases 는 실행 시 aliases.yaml 별칭으로 채워지므로 그대로 둔다.
DEFAULT_PROMPT = SYSTEM_PROMPT_TEMPLATE.template
DEFAULT_PROMPT_NAME = "기본 프롬프트"

_COLUMNS = "id, name, content, is_default, is_selected, created_at, updated_at"


class DefaultPromptDeleteError(Exception):
    """기본 프롬프트는 지울 수 없다 (선택된 프롬프트가 없을 때 돌아갈 곳이라서)."""


@dataclass(frozen=True)
class Prompt:
    id: int
    name: str
    content: str
    is_default: bool
    is_selected: bool
    created_at: datetime
    updated_at: datetime


def _row_to_prompt(row: sqlite3.Row) -> Prompt:
    return Prompt(
        id=row["id"],
        name=row["name"],
        content=row["content"],
        is_default=bool(row["is_default"]),
        is_selected=bool(row["is_selected"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _fetch(conn: sqlite3.Connection, prompt_id: int) -> Prompt | None:
    row = conn.execute(f"SELECT {_COLUMNS} FROM prompt WHERE id = ?", (prompt_id,)).fetchone()
    return _row_to_prompt(row) if row else None


def _fetch_where(conn: sqlite3.Connection, condition: str) -> Prompt | None:
    row = conn.execute(f"SELECT {_COLUMNS} FROM prompt WHERE {condition}").fetchone()
    return _row_to_prompt(row) if row else None


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class PromptRepository:
    def __init__(self, db: Database):
        self.db = db

    def ensure_default(self) -> Prompt:
        """기본 프롬프트가 없으면 agent/prompt.py 내용으로 넣는다. 서버 시작 시 한 번 부른다.
        선택된 프롬프트가 하나도 없으면 기본 프롬프트를 선택한다."""
        with self.db.transaction() as conn:
            default = _fetch_where(conn, "is_default = 1")
            if default is None:
                now = _now()
                cursor = conn.execute(
                    """
                    INSERT INTO prompt (name, content, is_default, is_selected, created_at, updated_at)
                    VALUES (?, ?, 1, 0, ?, ?)
                    """,
                    (DEFAULT_PROMPT_NAME, DEFAULT_PROMPT, now, now),
                )
                logger.info("기본 프롬프트 등록: id=%d", cursor.lastrowid)
                default = _fetch(conn, cursor.lastrowid)

            if _fetch_where(conn, "is_selected = 1") is None:
                conn.execute("UPDATE prompt SET is_selected = 1 WHERE id = ?", (default.id,))
                logger.info("선택된 프롬프트가 없어 기본 프롬프트를 선택: id=%d", default.id)
                default = _fetch(conn, default.id)
        return default

    def list_all(self) -> list[Prompt]:
        """저장된 프롬프트 전체 (만든 순서라 기본 프롬프트가 보통 맨 앞)."""
        with self.db.lock, self.db.get_conn() as conn:
            rows = conn.execute(f"SELECT {_COLUMNS} FROM prompt ORDER BY id").fetchall()
        return [_row_to_prompt(row) for row in rows]

    def get(self, prompt_id: int) -> Prompt | None:
        with self.db.lock, self.db.get_conn() as conn:
            return _fetch(conn, prompt_id)

    def get_default(self) -> Prompt | None:
        with self.db.lock, self.db.get_conn() as conn:
            return _fetch_where(conn, "is_default = 1")

    def get_selected(self) -> Prompt | None:
        with self.db.lock, self.db.get_conn() as conn:
            return _fetch_where(conn, "is_selected = 1")

    def get_system_prompt(self) -> str:
        """에이전트가 쓸 프롬프트 내용. 선택된 프롬프트 → DB 기본 프롬프트 → agent/prompt.py 원문 순서로 쓴다."""
        try:
            with self.db.lock, self.db.get_conn() as conn:
                prompt = _fetch_where(conn, "is_selected = 1") or _fetch_where(conn, "is_default = 1")
        except sqlite3.Error:
            # 프롬프트를 못 읽어도 답변 생성은 멈추지 않도록 백업 원문으로 대신한다
            logger.exception("프롬프트 조회 실패: agent/prompt.py 원문으로 대신합니다")
            return DEFAULT_PROMPT
        return prompt.content if prompt else DEFAULT_PROMPT

    def create(self, name: str, content: str) -> Prompt:
        """새 프롬프트를 저장한다. 선택은 select()로 따로 한다."""
        now = _now()
        with self.db.transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO prompt (name, content, is_default, is_selected, created_at, updated_at)
                VALUES (?, ?, 0, 0, ?, ?)
                """,
                (name, content, now, now),
            )
            return _fetch(conn, cursor.lastrowid)

    def update(self, prompt_id: int, name: str, content: str) -> Prompt | None:
        """이름과 내용을 고친다. 없는 id면 None (라우터에서 404 처리). 기본·선택 여부는 바꾸지 않는다."""
        with self.db.transaction() as conn:
            cursor = conn.execute(
                "UPDATE prompt SET name = ?, content = ?, updated_at = ? WHERE id = ?",
                (name, content, _now(), prompt_id),
            )
            if cursor.rowcount != 1:
                return None
            return _fetch(conn, prompt_id)

    def delete(self, prompt_id: int) -> bool:
        """프롬프트를 지운다. 없는 id면 False. 기본 프롬프트면 DefaultPromptDeleteError.
        선택된 프롬프트를 지우면 기본 프롬프트를 선택해 선택이 비지 않게 한다."""
        with self.db.transaction() as conn:
            prompt = _fetch(conn, prompt_id)
            if prompt is None:
                return False
            if prompt.is_default:
                raise DefaultPromptDeleteError(prompt_id)

            conn.execute("DELETE FROM prompt WHERE id = ?", (prompt_id,))
            if prompt.is_selected:
                conn.execute("UPDATE prompt SET is_selected = 1 WHERE is_default = 1")
        return True

    def select(self, prompt_id: int) -> Prompt | None:
        """이 프롬프트를 선택하고 기존 선택은 푼다. 없는 id면 기존 선택을 그대로 두고 None (라우터에서 404 처리)."""
        with self.db.transaction() as conn:
            # 없는 id로 기존 선택만 풀리는 일이 없도록 먼저 확인한다
            if _fetch(conn, prompt_id) is None:
                return None

            # 기존 선택을 먼저 풀어야 한다 (순서가 바뀌면 idx_prompt_selected 유니크 위반)
            conn.execute("UPDATE prompt SET is_selected = 0 WHERE is_selected = 1")
            conn.execute("UPDATE prompt SET is_selected = 1 WHERE id = ?", (prompt_id,))
            return _fetch(conn, prompt_id)
