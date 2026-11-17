"""질의응답 로그 남기기 (repository/qa_log_repository.py).

라우터가 답변을 돌려주기 직전(또는 실패를 돌려주기 직전)에 부른다. 기록 실패는 경고만 남기고 삼킨다:
로그 때문에 답변이 막히면 안 된다. 에이전트 실행 로직은 건드리지 않고, 실행이 남긴 run 행을 읽어 복사만 한다.
"""
from __future__ import annotations

import logging
import time

from fastapi import Request

from app.access_log import _client_ip
from repository import evidence_repo, qa_log_repo

logger = logging.getLogger(__name__)


def _ip(request: Request | None) -> str:
    if request is None:
        return ""
    try:
        return _client_ip(request.scope, dict(request.scope.get("headers") or []))
    except Exception:  # noqa: BLE001 - 접속 주소는 없어도 된다
        return ""


def _tools_available() -> list[str] | None:
    try:
        from agent.agent import active_tools
        return [getattr(t, "name", str(t)) for t in active_tools()]
    except Exception:  # noqa: BLE001
        return None


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000


def record_answer(
    request: Request | None, endpoint: str, mode: str, question: str, started: float,
    result: dict, sources: list[dict], attachments: list[dict] | None = None,
) -> str | None:
    """정상 답변 한 건. log_id를 돌려준다 (실패하면 None — 화면은 평가 버튼을 숨긴다)."""
    try:
        run_id = result.get("run_id")
        run = evidence_repo.get_run(run_id) if run_id else None
        run = run or {}
        return qa_log_repo.insert(
            endpoint=endpoint, mode=mode, question=question, status="ok",
            duration_ms=_elapsed_ms(started), client_ip=_ip(request), attachments=attachments,
            answer=str(result.get("answer") or ""), sources=sources, validation=result.get("validation"),
            run_id=run_id, model=run.get("model"), prompt_id=run.get("prompt_id"),
            tools_available=_tools_available(), tool_calls_json=run.get("tool_calls_json"),
            tokens_in=run.get("tokens_in"), tokens_out=run.get("tokens_out"),
        )
    except Exception:  # noqa: BLE001 - 로그 실패로 답변을 막지 않는다
        logger.warning("질의응답 로그를 남기지 못함: endpoint=%s", endpoint, exc_info=True)
        return None


def record_failure(
    request: Request | None, endpoint: str, mode: str, question: str, started: float,
    exc: BaseException, attachments: list[dict] | None = None,
) -> None:
    """답변을 못 만든 한 건 (모델 미로드, 호출 한도, 빈 답변, 그 밖의 예외)."""
    try:
        qa_log_repo.insert(
            endpoint=endpoint, mode=mode, question=question, status="error",
            duration_ms=_elapsed_ms(started), client_ip=_ip(request), attachments=attachments,
            error=f"{type(exc).__name__}: {exc}", tools_available=_tools_available(),
        )
    except Exception:  # noqa: BLE001
        logger.warning("질의응답 실패 로그를 남기지 못함: endpoint=%s", endpoint, exc_info=True)
