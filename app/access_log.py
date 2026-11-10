"""HTTP 접속 기록을 DB(access_log 테이블)에 남기는 미들웨어.

요청마다 바로 INSERT하면 SQLite 쓰기가 응답을 붙잡으므로, 미들웨어는 큐에 넣기만 하고
백그라운드 스레드가 몇 초마다 모아서 한 번에 넣는다. 큐가 가득 차면(DB 장애 등) 버리고 개수만 센다.

남기지 않는 요청
- /assets/ 등 프론트엔드 정적 파일
- /monitor/ : 상태 대시보드가 몇 초마다 부르는 API (남기면 기록이 대시보드 폴링으로 덮인다)
"""
from __future__ import annotations

import logging
import queue
import re
import threading
import time
from datetime import datetime, timezone

from starlette.types import ASGIApp, Message, Receive, Scope, Send

import config
from repository import access_log_repo

logger = logging.getLogger(__name__)

_SKIP_PREFIXES = ("/assets/", "/monitor/")
# dist 루트의 정적 파일 (/favicon.svg, /icons.svg 등)
_ROOT_STATIC = re.compile(r"^/[^/]+\.(?:svg|ico|png|jpg|webp|js|css|map|txt|webmanifest|woff2?)$", re.IGNORECASE)
# main.py의 SPA catch-all. 이 경로로 처리된 요청은 템플릿 대신 실제 경로를 묶음 기준으로 쓴다
_SPA_ROUTE = "/{spa_path:path}"

_FLUSH_SECONDS = 2.0
_BATCH_SIZE = 500
_PURGE_INTERVAL_SECONDS = 6 * 3600

_queue: queue.Queue[tuple] = queue.Queue(maxsize=20000)
_stop = threading.Event()
_thread: threading.Thread | None = None
_dropped = 0


def _client_ip(scope: Scope, headers: dict[bytes, bytes]) -> str:
    # 리버스 프록시 뒤에 두면 실제 클라이언트는 X-Forwarded-For 첫 값이다 (사내망 대시보드 용도라 그대로 믿는다)
    forwarded = headers.get(b"x-forwarded-for")
    if forwarded:
        return forwarded.decode("latin-1").split(",")[0].strip()
    real_ip = headers.get(b"x-real-ip")
    if real_ip:
        return real_ip.decode("latin-1").strip()
    client = scope.get("client")
    return client[0] if client else ""


class AccessLogMiddleware:
    """순수 ASGI 미들웨어. BaseHTTPMiddleware와 달리 스트리밍 응답을 버퍼링하지 않는다."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope.get("path", "")
        if path.startswith(_SKIP_PREFIXES) or _ROOT_STATIC.match(path):
            await self.app(scope, receive, send)
            return

        started = time.perf_counter()
        status = 500  # 응답 시작 전에 예외가 나면 서버 오류로 남긴다

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            _record(scope, path, status, (time.perf_counter() - started) * 1000)


def _record(scope: Scope, path: str, status: int, duration_ms: float) -> None:
    global _dropped
    try:
        headers = dict(scope.get("headers") or [])
        # 라우팅이 끝나면 scope["route"]에 FastAPI 경로 템플릿(/file/{file_id} 등)이 들어 있다
        route = getattr(scope.get("route"), "path", None)
        if not route or route == _SPA_ROUTE:
            route = path
        row = (
            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            _client_ip(scope, headers),
            scope.get("method", ""),
            path[:1000],
            route[:300],
            (scope.get("query_string") or b"").decode("latin-1")[:1000],
            status,
            round(duration_ms, 1),
            headers.get(b"user-agent", b"").decode("latin-1")[:300],
        )
        _queue.put_nowait(row)
    except queue.Full:
        _dropped += 1
    except Exception:
        # 기록 실패가 요청 처리를 깨면 안 된다
        logger.exception("접속 기록 생성 실패")


def _drain(limit: int) -> list[tuple]:
    rows: list[tuple] = []
    while len(rows) < limit:
        try:
            rows.append(_queue.get_nowait())
        except queue.Empty:
            break
    return rows


def _purge() -> None:
    try:
        removed = access_log_repo.purge_older_than(config.ACCESS_LOG_RETENTION_DAYS)
        if removed:
            logger.info("접속 기록 %d건 정리 (%d일 보관)", removed, config.ACCESS_LOG_RETENTION_DAYS)
    except Exception:
        logger.exception("오래된 접속 기록 정리 실패")


def _writer_loop() -> None:
    global _dropped
    _purge()
    next_purge = time.monotonic() + _PURGE_INTERVAL_SECONDS
    while True:
        stopping = _stop.wait(_FLUSH_SECONDS)
        while True:
            rows = _drain(_BATCH_SIZE)
            if not rows:
                break
            try:
                access_log_repo.insert_many(rows)
            except Exception:
                logger.exception("접속 기록 %d건 저장 실패", len(rows))
        if _dropped:
            logger.warning("큐가 가득 차 접속 기록 %d건을 버렸습니다", _dropped)
            _dropped = 0
        if stopping:
            return
        if time.monotonic() >= next_purge:
            _purge()
            next_purge = time.monotonic() + _PURGE_INTERVAL_SECONDS


def start() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_writer_loop, name="access-log-writer", daemon=True)
    _thread.start()


def stop() -> None:
    """남은 기록을 저장하고 스레드를 끝낸다."""
    _stop.set()
    if _thread:
        _thread.join(timeout=5)
