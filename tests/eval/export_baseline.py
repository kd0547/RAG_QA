"""현재 상태의 메일 답변 기록을 기준선(baseline) 평가셋으로 내보낸다.

읽기 전용. storage/mail.db의 tasks·mails·task_sources·mail_attachments·task_reviews와
logs/app.log*의 "에이전트 실행 완료" 줄(도구 호출 수·소요시간·검색어)을 묶어 JSON 한 파일로 쓴다.

사용:
    .venv/Scripts/python.exe -I tests/eval/export_baseline.py [출력경로]

출력 기본값: tests/eval/baseline_<오늘>.json
개선 후 같은 질문(본문+첨부)을 다시 돌려 answer·sources·trajectory를 나란히 비교한다.
"""
from __future__ import annotations

import glob
import json
import re
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "storage" / "mail.db"
LOG_GLOB = str(ROOT / "logs" / "app.log*")

# 2026-11-05 15:08:02,942 INFO [MainThread] agent.agent:137 - 에이전트 실행 완료: 메일(첨부 1건, 반려피드백 없음), mode=local, 159.7초, messages=17, tools={'search_documents': 4}
_DONE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ .*에이전트 실행 완료: (?P<label>.+?), mode=(?P<mode>\w+), "
    r"(?P<sec>[\d.]+)초, messages=(?P<msgs>\d+), tools=(?P<tools>.+)$"
)
_TOOL = re.compile(r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ .*\[(?P<tool>search_documents|graph_search|read_source_document|rerank_documents|check_answerability)\] (?P<rest>.*)$")
_QUERY = re.compile(r"query='(?P<q>[^']*)'")
_READ = re.compile(r"^(?P<name>.+?) (?P<start>\d+)~(?P<end>\d+) / (?P<total>\d+)자")
_ANSWERABLE = re.compile(r"is_answerable=(?P<v>True|False)")


def _parse_logs() -> list[dict]:
    """로그에서 실행 1건씩 (완료 줄 + 직전 완료 줄 이후의 도구 호출 줄)을 모은다. 시간순."""
    lines: list[tuple[str, str]] = []
    for path in sorted(glob.glob(LOG_GLOB)):
        with open(path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                lines.append((path, line.rstrip("\n")))

    runs: list[dict] = []
    pending_tools: list[dict] = []
    for _path, line in lines:
        m = _TOOL.match(line)
        if m:
            rest = m.group("rest")
            entry: dict = {"tool": m.group("tool"), "ts": m.group("ts")}
            q = _QUERY.search(rest)
            if q:
                entry["query"] = q.group("q")
            r = _READ.match(rest)
            if r:
                entry.update(file=r.group("name"), start=int(r.group("start")), end=int(r.group("end")), total=int(r.group("total")))
            a = _ANSWERABLE.search(rest)
            if a:
                entry["is_answerable"] = a.group("v") == "True"
            pending_tools.append(entry)
            continue
        m = _DONE.match(line)
        if m:
            try:
                tools = eval(m.group("tools"), {"__builtins__": {}})  # 로그에 찍힌 dict 리터럴 또는 '없음'
            except Exception:
                tools = m.group("tools")
            runs.append({
                "completed_at": m.group("ts"),
                "label": m.group("label"),
                "mode": m.group("mode"),
                "seconds": float(m.group("sec")),
                "messages": int(m.group("msgs")),
                "tool_counts": tools if isinstance(tools, dict) else {},
                "tool_calls": pending_tools,
            })
            pending_tools = []
    return runs


def _match_run(runs: list[dict], updated_at: str, used: set[int]) -> dict | None:
    """초안 저장 시각(updated_at) 직전 10분 안에 끝난 메일 실행 중 가장 가까운 것."""
    try:
        saved = datetime.fromisoformat(updated_at)
    except ValueError:
        return None
    best, best_i = None, -1
    for i, run in enumerate(runs):
        if i in used or not run["label"].startswith("메일"):
            continue
        done = datetime.strptime(run["completed_at"], "%Y-%m-%d %H:%M:%S")
        if done <= saved and saved - done <= timedelta(minutes=10):
            if best is None or done > datetime.strptime(best["completed_at"], "%Y-%m-%d %H:%M:%S"):
                best, best_i = run, i
    if best_i >= 0:
        used.add(best_i)
    return best


def export(out_path: Path) -> dict:
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    runs = _parse_logs()
    used: set[int] = set()

    tasks = conn.execute(
        """SELECT t.task_id, t.mail_uid, t.status, t.draft_answer, t.created_at, t.updated_at,
                  m.subject, m.sender, m.body, m.received_at
           FROM tasks t JOIN mails m ON m.uid = t.mail_uid
           WHERE t.draft_answer IS NOT NULL AND t.draft_answer != ''
           ORDER BY t.updated_at"""
    ).fetchall()

    cases = []
    for t in tasks:
        sources = [
            {
                "file": Path(r["source"]).name if r["source"] else None,
                "page": r["page"],
                "chunk_index": r["chunk_index"],
                "score": r["score"],
                "text_head": (r["text"] or "")[:200],
            }
            for r in conn.execute(
                "SELECT source, page, chunk_index, score, text FROM task_sources WHERE task_id = ? ORDER BY source_id",
                (t["task_id"],),
            )
        ]
        attachments = [
            {"filename": r["filename"], "type": r["type"]}
            for r in conn.execute("SELECT filename, type FROM mail_attachments WHERE mail_uid = ?", (t["mail_uid"],))
        ]
        reviews = [
            {"action": r["action"], "reason": r["reason"], "requeue": r["requeue"], "at": r["reviewed_at"]}
            for r in conn.execute("SELECT action, reason, requeue, reviewed_at FROM task_reviews WHERE task_id = ? ORDER BY review_id", (t["task_id"],))
        ]
        cases.append({
            "task_id": t["task_id"],
            "mail_uid": t["mail_uid"],
            "status": t["status"],
            "received_at": t["received_at"],
            "answered_at": t["updated_at"],
            "sender": t["sender"],
            "subject": t["subject"],
            "question": t["body"],
            "attachments": attachments,
            "baseline_answer": t["draft_answer"],
            "baseline_sources": sources,
            "baseline_source_files": sorted({s["file"] for s in sources if s["file"]}),
            "reviews": reviews,
            "baseline_trajectory": _match_run(runs, t["updated_at"], used),
            # 개선 후 채울 자리
            "expected_evidence": None,   # 사람이 적는 정답 근거 (파일, 페이지)
            "expected_keywords": None,   # 답변에 반드시 있어야 할 값·모델명
            "after": None,               # {"answer":..., "sources":..., "trajectory":...}
        })

    all_files = sorted({f for c in cases for f in c["baseline_source_files"]})
    local_files = {r["original_name"] for r in conn.execute("SELECT original_name FROM file")}
    result = {
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "db": str(DB_PATH),
        "case_count": len(cases),
        "runs_in_logs": len(runs),
        "runs_matched": sum(1 for c in cases if c["baseline_trajectory"]),
        "documents_referenced": all_files,
        "documents_missing_locally": [f for f in all_files if f not in local_files],
        "cases": cases,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "tests" / "eval" / f"baseline_{date.today().isoformat()}.json"
    summary = export(out)
    print(f"written: {out}")
    print(f"cases={summary['case_count']}, runs_in_logs={summary['runs_in_logs']}, matched={summary['runs_matched']}")
    print(f"documents referenced={len(summary['documents_referenced'])}, missing locally={len(summary['documents_missing_locally'])}")
