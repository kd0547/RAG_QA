"""최종 답변의 근거 검증 (서버 코드로 강제하는 최소 규칙).

답변 마지막 줄은 "근거: e12ab34cd, e9f8e7d6c" 또는 "근거: 없음"이다 (시스템 프롬프트 v2).
서버가 이 줄을 파싱해 인용(cite)을 기록하고 본문에서는 지운다.

- errors: 저장은 하되 검토 화면에 경고로 보인다. (상태는 그대로 drafted. "검증 완료" 같은 표시는 하지 않는다)
  1) 다른 소유자(다른 메일·세션)의 근거이거나 없는 ID를 인용
  2) '근거: 없음'이 아닌데 이 질문(같은 대화의 실행들)에서 아무것도 읽지 않음
- warnings: 근거 줄 없음, 이 질문에서 읽지 않은 근거 인용, ID 형식이 아닌 항목

'읽음'은 같은 소유자(메일 = 같은 대화)의 모든 실행에서 읽은 것을 센다. 반려 후 재작성은 1차에서 읽은 근거를
다시 읽지 않고 인용하기 때문이다 (단계 C3). /ask는 호출마다 소유자가 새로 생겨 '이번 실행'과 같다.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

import repository
from agent.evidence_context import Owner

_EVIDENCE_LINE = re.compile(r"^\s*\**\s*근거\s*\**\s*[:：]\s*(?P<value>.*?)\s*$")
_EVIDENCE_ID = re.compile(r"^e[0-9a-f]{4,32}$")
_NONE_VALUES = {"없음", "없음.", "none"}


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    cited_ids: list[str] = field(default_factory=list)
    answer: str = ""          # 근거 줄을 뺀 본문

    def to_dict(self) -> dict:
        data = asdict(self)
        data.pop("answer")
        return data


def split_evidence_line(answer: str) -> tuple[str, str | None]:
    """(근거 줄을 뺀 본문, 근거 줄의 값). 마지막 비어 있지 않은 줄이 근거 줄이 아니면 값은 None."""
    lines = (answer or "").rstrip().splitlines()
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return "", None
    match = _EVIDENCE_LINE.match(lines[-1])
    if match is None:
        return (answer or "").rstrip(), None
    return "\n".join(lines[:-1]).rstrip(), match.group("value")


def validate_answer(run_id: str, owner: Owner, answer: str) -> ValidationResult:
    """근거 줄을 파싱·검증하고 유효한 인용을 evidence_use(cite)에 기록한다."""
    body, value = split_evidence_line(answer)
    errors: list[str] = []
    warnings: list[str] = []
    declared_none = False
    ids: list[str] = []

    if value is None or not value.strip("[]`* "):
        warnings.append("근거 줄 없음")
        body = (answer or "").rstrip() if value is None else body
    else:
        cleaned = value.strip("[]`* ")
        if cleaned.lower() in _NONE_VALUES:
            declared_none = True
        else:
            for token in (t.strip("[]`*.() ") for t in re.split(r"[,\s]+", cleaned)):
                if not token:
                    continue
                if _EVIDENCE_ID.match(token):
                    ids.append(token)
                else:
                    warnings.append(f"근거 ID 형식이 아님: {token}")
    ids = list(dict.fromkeys(ids))

    evidence_repo = repository.evidence_repo
    owned = {e["evidence_id"] for e in evidence_repo.get_many(ids, owner.type, owner.id)}
    cited = []
    for evidence_id in ids:
        if evidence_id in owned:
            cited.append(evidence_id)
        else:
            errors.append(f"이 질문의 근거가 아닌 ID 인용: {evidence_id}")

    read_ids = {u["evidence_id"] for u in evidence_repo.uses_for_run(run_id, "read")}
    read_ids |= {u["evidence_id"] for u in evidence_repo.uses_for_owner(owner.type, owner.id, "read")}
    for evidence_id in cited:
        if evidence_id not in read_ids:
            warnings.append(f"이 질문에서 읽지 않은 근거 인용: {evidence_id}")
    if not declared_none and not read_ids:
        errors.append("근거를 읽지 않고 답변")

    for evidence_id in cited:
        evidence_repo.record_use(run_id, evidence_id, "cite")

    return ValidationResult(ok=not errors, errors=errors, warnings=warnings, cited_ids=cited, answer=body)
