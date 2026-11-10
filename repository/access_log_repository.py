"""HTTP 접속 기록(access_log) 저장·조회. 기록은 app/access_log.py의 미들웨어가 모아서 넣는다.

시각(ts)은 UTC ISO 문자열('2026-11-10T03:15:42Z')이라 문자열 비교로 기간을 자를 수 있다.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from repository.repo_connect import Database

# 상태 코드 범주 필터 값 → SQL 조건
_STATUS_FILTERS = {
    "2xx": "status BETWEEN 200 AND 299",
    "3xx": "status BETWEEN 300 AND 399",
    "4xx": "status BETWEEN 400 AND 499",
    "5xx": "status >= 500",
    "error": "status >= 400",
}


def utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class AccessLogRepository:

    def __init__(self, db: Database):
        self.db = db

    def insert_many(self, rows: list[tuple]) -> None:
        """rows: (ts, client_ip, method, path, route, query, status, duration_ms, user_agent)"""
        if not rows:
            return
        with self.db.get_conn() as conn:
            conn.executemany(
                """
                INSERT INTO access_log (ts, client_ip, method, path, route, query, status, duration_ms, user_agent)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.commit()

    def purge_older_than(self, days: int) -> int:
        cutoff = utc_iso(datetime.now(timezone.utc) - timedelta(days=days))
        with self.db.get_conn() as conn:
            cursor = conn.execute("DELETE FROM access_log WHERE ts < ?", (cutoff,))
            conn.commit()
            return cursor.rowcount

    def summary(self, hours: int, tz_minutes: int = 0) -> dict:
        """최근 hours시간의 요청 수·오류·응답 시간과 시간대별 건수, 많이 부른 경로·IP.

        tz_minutes: 보는 사람 시간대의 UTC 차이(분). 하루 단위로 묶을 때 날짜 경계를 맞춘다.
        """
        now = datetime.now(timezone.utc)
        since = utc_iso(now - timedelta(hours=hours))
        with self.db.get_conn() as conn:
            totals = conn.execute(
                """
                SELECT COUNT(*) AS total,
                       COUNT(DISTINCT client_ip) AS unique_ips,
                       SUM(CASE WHEN status BETWEEN 400 AND 499 THEN 1 ELSE 0 END) AS client_errors,
                       SUM(CASE WHEN status >= 500 THEN 1 ELSE 0 END) AS server_errors,
                       AVG(duration_ms) AS avg_ms
                FROM access_log WHERE ts >= ?
                """,
                (since,),
            ).fetchone()
            total = totals["total"] or 0

            # SQLite에는 백분위 함수가 없어서 정렬 후 해당 순번 하나만 읽는다
            p95_ms = None
            if total:
                row = conn.execute(
                    "SELECT duration_ms FROM access_log WHERE ts >= ? ORDER BY duration_ms LIMIT 1 OFFSET ?",
                    (since, min(total - 1, int(total * 0.95))),
                ).fetchone()
                p95_ms = row["duration_ms"] if row else None

            # 기간이 길면 시간 단위 막대가 너무 많아져 하루 단위로 묶는다.
            # 날짜 경계는 보는 사람의 시간대(tz_minutes, 한국은 +540) 기준이어야 하므로 시각을 옮긴 뒤 자른다
            by_hour = hours <= 48
            fmt = "%Y-%m-%dT%H" if by_hour else "%Y-%m-%d"
            buckets = {
                row["bucket"]: (row["count"], row["errors"])
                for row in conn.execute(
                    """
                    SELECT strftime(?, ts, ?) AS bucket, COUNT(*) AS count,
                           SUM(CASE WHEN status >= 500 THEN 1 ELSE 0 END) AS errors
                    FROM access_log WHERE ts >= ? GROUP BY bucket
                    """,
                    (fmt, f"{tz_minutes:+d} minutes", since),
                )
            }

            top_paths = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT method, route, COUNT(*) AS count, AVG(duration_ms) AS avg_ms,
                           SUM(CASE WHEN status >= 500 THEN 1 ELSE 0 END) AS errors
                    FROM access_log WHERE ts >= ?
                    GROUP BY method, route ORDER BY count DESC LIMIT 10
                    """,
                    (since,),
                )
            ]
            top_ips = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT client_ip, COUNT(*) AS count, MAX(ts) AS last_seen
                    FROM access_log WHERE ts >= ?
                    GROUP BY client_ip ORDER BY count DESC LIMIT 10
                    """,
                    (since,),
                )
            ]

        # 빈 시간대도 0으로 채워야 막대 간격이 시간과 맞는다
        # t는 보는 사람 시간대의 벽시계 시각, start는 그 구간 시작의 UTC 시각
        shift = timedelta(minutes=tz_minutes)
        local_now = now + shift
        if by_hour:
            step, count_n = timedelta(hours=1), hours
            first = (local_now - step * (count_n - 1)).replace(minute=0, second=0, microsecond=0)
        else:
            step, count_n = timedelta(days=1), max(1, hours // 24)
            first = (local_now - step * (count_n - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
        series = []
        for i in range(count_n):
            t = first + step * i
            count, errors = buckets.get(t.strftime(fmt), (0, 0))
            series.append({"start": utc_iso(t - shift), "count": count, "errors": errors})

        return {
            "hours": hours,
            "bucket": "hour" if by_hour else "day",
            "total": total,
            "unique_ips": totals["unique_ips"] or 0,
            "client_errors": totals["client_errors"] or 0,
            "server_errors": totals["server_errors"] or 0,
            "avg_ms": totals["avg_ms"],
            "p95_ms": p95_ms,
            "series": series,
            "top_paths": top_paths,
            "top_ips": top_ips,
        }

    def list_recent(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        q: str = "",
        status: str = "",
        ip: str = "",
        method: str = "",
    ) -> dict:
        """최신순 접속 기록. q는 경로 부분 일치, status는 2xx/3xx/4xx/5xx/error."""
        where: list[str] = []
        params: list = []
        if q:
            where.append("path LIKE ?")
            params.append(f"%{q}%")
        if status in _STATUS_FILTERS:
            where.append(_STATUS_FILTERS[status])
        if ip:
            where.append("client_ip = ?")
            params.append(ip)
        if method:
            where.append("method = ?")
            params.append(method.upper())
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        with self.db.get_conn() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM access_log {clause}", params).fetchone()[0]
            items = [
                dict(row)
                for row in conn.execute(
                    f"""
                    SELECT id, ts, client_ip, method, path, route, query, status, duration_ms, user_agent
                    FROM access_log {clause} ORDER BY id DESC LIMIT ? OFFSET ?
                    """,
                    [*params, limit, offset],
                )
            ]
        return {"total": total, "items": items}
