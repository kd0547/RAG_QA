"""서버 상태 대시보드(/status 화면) API: 자원 사용량과 접속 기록.

이 경로(/monitor/)는 대시보드가 주기적으로 부르므로 접속 기록에 남기지 않는다 (app/access_log.py).
"""
from fastapi import APIRouter, Query

from app import system_monitor
from repository import access_log_repo

router = APIRouter(prefix="/monitor", tags=["monitor"])


@router.get("/system")
def system_status() -> dict:
    """CPU·메모리·GPU 현재 값과 최근 30분 추이."""
    return system_monitor.snapshot()


@router.get("/access/summary")
def access_summary(
    hours: int = Query(24, ge=1, le=24 * 90),
    tz_minutes: int = Query(0, ge=-720, le=840, description="보는 사람 시간대의 UTC 차이(분). 한국은 540"),
) -> dict:
    """최근 hours시간 요청 수·오류·응답 시간, 시간대별 건수, 많이 부른 경로·IP."""
    return access_log_repo.summary(hours, tz_minutes)


@router.get("/access/logs")
def access_logs(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    q: str = Query("", max_length=200, description="경로 부분 일치"),
    status: str = Query("", description="2xx / 3xx / 4xx / 5xx / error"),
    ip: str = Query("", max_length=100),
    method: str = Query("", max_length=10),
) -> dict:
    """최신순 접속 기록."""
    return access_log_repo.list_recent(limit=limit, offset=offset, q=q, status=status, ip=ip, method=method)
