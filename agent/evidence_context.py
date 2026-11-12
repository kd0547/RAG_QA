"""에이전트 실행 중 '누구의 근거인지(owner)'와 '어느 실행인지(run)'를 도구에 전달한다.

도구는 모델이 넘긴 인자만 받으므로 task_id 같은 서버 정보를 인자로 받지 않는다 (모델이 바꿀 수 없게).
run_agent*가 진입 시 owner를, _invoke_logged가 run을 설정하고 끝나면 해제한다.
contextvars라서 LangGraph가 도구를 다른 스레드에서 실행해도 값이 그대로 전달된다.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, NamedTuple


class Owner(NamedTuple):
    type: str   # 'task' | 'session'
    id: str


_owner: ContextVar[Owner | None] = ContextVar("evidence_owner", default=None)
_run: ContextVar[str | None] = ContextVar("evidence_run", default=None)
# /ask/attachments의 임시 첨부: 이번 질문에만 쓰는 첨부를 번호로 찾는다 (DB에 저장하지 않는다)
_temp_attachments: ContextVar[dict | None] = ContextVar("temp_attachments", default=None)


def current_owner() -> Owner | None:
    return _owner.get()


def current_run() -> str | None:
    return _run.get()


def temp_attachments() -> dict:
    """현재 세션의 임시 첨부 {번호: 첨부 정보}. 세션 밖이면 빈 dict."""
    return _temp_attachments.get() or {}


@contextmanager
def owner_scope(owner: Owner, temp: dict | None = None) -> Iterator[Owner]:
    owner_token = _owner.set(owner)
    temp_token = _temp_attachments.set(temp if temp is not None else {})
    try:
        yield owner
    finally:
        _temp_attachments.reset(temp_token)
        _owner.reset(owner_token)


@contextmanager
def run_scope(run_id: str) -> Iterator[str]:
    token = _run.set(run_id)
    try:
        yield run_id
    finally:
        _run.reset(token)
