"""두 구성의 결과(current.json, proto.json)를 마크다운 표로 낸다 (통합 지시서 F-4).

    .venv/Scripts/python.exe tests/eval/deepagents_proto/compare.py <작업 폴더>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _verdict(case: dict) -> str:
    if case.get("error"):
        return "실패: " + case["error"].splitlines()[0][:60]
    validation = case.get("validation") or {}
    if validation.get("ok"):
        return "통과" + (f" (경고 {len(validation.get('warnings') or [])})" if validation.get("warnings") else "")
    return "오류: " + "; ".join(validation.get("errors") or [])[:80]


def _cell(value) -> str:
    return str(value if value is not None else "-").replace("|", "\\|").replace("\n", " ")


def table(current: dict, proto: dict) -> str:
    rows = ["| # | 문항 | 구성 | 답변 검증 | 인용한 근거 | 도구 호출(오류) | 모델 호출 | 입력/출력 토큰 | 초 |",
            "|---|---|---|---|---|---|---|---|---|"]
    by_title = {c["eval_title"]: c for c in proto.get("cases", [])}
    totals = {"current": [0, 0, 0, 0, 0.0, 0], "proto": [0, 0, 0, 0, 0.0, 0]}
    for index, case in enumerate(current.get("cases", []), start=1):
        for kind, item in (("현재", case), ("시제품", by_title.get(case["eval_title"], {}))):
            key = "current" if kind == "현재" else "proto"
            if item:
                t = totals[key]
                t[0] += 1 if (item.get("validation") or {}).get("ok") and not item.get("error") else 0
                t[1] += item.get("tool_calls") or 0
                t[2] += item.get("tool_errors") or 0
                t[3] += item.get("tokens_in") or 0
                t[4] += item.get("seconds") or 0
                t[5] += 1
            cited = ", ".join(item.get("cited") or []) or ("없음" if item else "-")
            rows.append(
                f"| {index if kind == '현재' else ''} | {_cell(case['eval_title']) if kind == '현재' else ''} | {kind} | "
                f"{_cell(_verdict(item)) if item else '-'} | {_cell(cited[:120])} | "
                f"{_cell(item.get('tool_calls'))}({_cell(item.get('tool_errors'))}) | {_cell(item.get('model_calls'))} | "
                f"{_cell(item.get('tokens_in'))}/{_cell(item.get('tokens_out'))} | {_cell(item.get('seconds'))} |"
            )
    summary = ["", "| 구성 | 문항 | 검증 통과 | 도구 호출 합 | 도구 오류 합 | 입력 토큰 합 | 소요 합(초) |", "|---|---|---|---|---|---|---|"]
    for key, label in (("current", "현재 엔진"), ("proto", "deepagents 시제품")):
        t = totals[key]
        summary.append(f"| {label} | {t[5]} | {t[0]} | {t[1]} | {t[2]} | {t[3]:,} | {t[4]:.1f} |")
    return "\n".join(rows + summary)


def main() -> int:
    work = Path(sys.argv[1])
    current, proto = _load(work / "current.json"), _load(work / "proto.json")
    sys.stdout.reconfigure(encoding="utf-8")
    print(f"- 현재 엔진: {current['versions']} · 프롬프트 `{current['prompt']}` · 도구 {len(current['tools'])}개")
    print(f"- 시제품: {proto['versions']} · 프롬프트 `{proto['prompt']}` · 도구 {len(proto['tools'])}개 · 절차 {proto.get('skills_offered')}")
    print()
    print(table(current, proto))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
