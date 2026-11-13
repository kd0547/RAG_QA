"""사양 값의 단위 표와 환산 (DB·LLM을 쓰지 않는 순수 함수).

같은 차원 안에서만 환산한다 (지시서 E2 (다)). 표에 없는 단위(코어, 개, px, 년 …)는 속성 단위와 글자가 같을 때만 쓴다.
저장된 값(value_text)도 같은 규칙으로 읽는다: 숫자 뒤에 단위가 적혀 있으면 그 단위로 읽어 속성 단위로 바꾸고,
없으면 속성 단위로 본다. 모르는 단위나 다른 차원이면 숫자를 쓰지 않는다 ("단위 확인 필요").

점검 스크립트(scripts/audit_spec_values.py)와 사양 서비스(agent/spec_service.py)가 함께 쓴다.
저장소(repository)를 임포트하지 않는다 — 점검 스크립트가 운영 DB를 열지 않게 하기 위해서다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# 차원 → {표준 단위: 기준 단위로의 배수}
DIMENSIONS: dict[str, dict[str, float]] = {
    "mass": {"kg": 1000.0, "g": 1.0},
    "storage": {"TB": 1_000_000.0, "GB": 1000.0, "MB": 1.0},       # 1TB = 1,000GB
    "memory": {"GB": 1024.0, "MB": 1.0},                            # 1GB = 1,024MB
    "frequency": {"GHz": 1000.0, "MHz": 1.0},
    "length": {"mm": 1.0, "cm": 10.0, "inch": 25.4},
    "speed": {"GB/s": 1000.0, "MB/s": 1.0},
    "iops": {"K IOPS": 1000.0, "IOPS": 1.0},
    # 전력·용량은 서로 환산하지 않는다 (각자 한 단위짜리 차원)
    "power": {"W": 1.0},
    "energy": {"Wh": 1.0},
    "charge": {"mAh": 1.0},
}

# 차원별 다른 표기 → 표준 단위. 그 속성의 차원 안에서만 쓴다 ("G"는 저장 용량 속성에서만 GB)
ALIASES: dict[str, dict[str, str]] = {
    "storage": {"T": "TB", "G": "GB"},
    "memory": {"G": "GB"},
    "iops": {"K": "K IOPS", "KIOPS": "K IOPS"},
    "length": {"인치": "inch", "in": "inch", '"': "inch", "″": "inch"},
}

# 메모리 용량으로 보는 속성 분류 (그 밖의 GB·MB 속성은 저장 용량)
MEMORY_CATEGORIES = frozenset({"memory", "graphics", "cpu"})

_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def _key(unit: str | None) -> str:
    """단위 비교 키: 소문자, 공백 제거."""
    return "".join((unit or "").split()).lower()


def attribute_dimension(attribute_unit: str | None, category: str | None = None) -> str | None:
    """속성 단위의 차원. 표에 없는 단위면 None (그 단위 글자 그대로만 쓴다)."""
    key = _key(attribute_unit)
    if not key:
        return None
    if key in ("gb", "mb") and category in MEMORY_CATEGORIES:
        return "memory"
    if key in ("tb", "gb", "mb"):
        return "storage"
    for dimension, units in DIMENSIONS.items():
        if key in {_key(u) for u in units} or key in {_key(a) for a in ALIASES.get(dimension, {})}:
            return dimension
    return None


def canonical_unit(unit: str | None, dimension: str | None) -> str | None:
    """그 차원의 표준 단위 이름. 그 차원의 단위가 아니면 None."""
    if dimension is None:
        return None
    key = _key(unit)
    for name in DIMENSIONS[dimension]:
        if _key(name) == key:
            return name
    for alias, name in ALIASES.get(dimension, {}).items():
        if _key(alias) == key:
            return name
    return None


def _dimensions_of(unit: str) -> list[str]:
    return [d for d in DIMENSIONS if canonical_unit(unit, d) is not None]


def to_attribute_unit(value: float, unit: str | None, attribute_unit: str | None, category: str | None = None) -> float | None:
    """value(unit)를 속성 단위로 바꾼다. 단위가 비었으면 속성 단위로 본다. 환산할 수 없으면 None.

    예: (1.5, "kg", "g") → 1500, (1, "TB", "GB") → 1000, (1, "GB", "MB", "memory") → 1024, (16, "GB", "GHz") → None
    """
    if not _key(unit) or _key(unit) == _key(attribute_unit):
        return float(value)
    dimension = attribute_dimension(attribute_unit, category)
    source = canonical_unit(unit, dimension)
    target = canonical_unit(attribute_unit, dimension)
    if source is None or target is None:
        return None
    factors = DIMENSIONS[dimension]
    return float(value) * factors[source] / factors[target]


@dataclass(frozen=True)
class ReadNumber:
    """사양 값 문자열을 속성 단위의 숫자로 읽은 결과."""
    value: float | None        # 속성 단위의 숫자. 읽을 수 없거나 단위 확인이 필요하면 None
    raw: float | None          # 문자열의 첫 숫자 (단위 환산 전)
    unit: str | None           # 문자열에서 읽은 단위 (없으면 None)
    problem: str | None = None  # None이 아니면 숫자를 쓰지 않은 이유


def _unit_candidates(attribute_unit: str | None) -> list[str]:
    names = {u for units in DIMENSIONS.values() for u in units}
    names |= {a for aliases in ALIASES.values() for a in aliases}
    if _key(attribute_unit):
        names.add(attribute_unit.strip())
    return sorted(names, key=len, reverse=True)


def _match_unit(after: str, attribute_unit: str | None) -> str | None:
    """숫자 바로 뒤 글자에서 단위를 찾는다 (긴 것부터, 뒤에 영문·숫자가 이어지면 단위가 아니다: 'GDDR7'은 'G'가 아님)."""
    for candidate in _unit_candidates(attribute_unit):
        # "K IOPS"처럼 띄어 쓴 단위는 "KIOPS"·"K  IOPS"도 같은 단위로 본다
        pattern = r"\s*".join(re.escape(part) for part in candidate.split())
        match = re.match(pattern, after, re.IGNORECASE)
        if match is None:
            continue
        rest = after[match.end():]
        if rest and rest[0].isascii() and rest[0].isalnum():
            continue
        return candidate
    return None


def read_number(value_text: str, attribute_unit: str | None, category: str | None = None) -> ReadNumber:
    """'5,000MB/s', '1TB', '600T', '8 GDDR7' 같은 값 문자열을 속성 단위의 숫자로 읽는다.

    - 첫 숫자를 쓴다 (천 단위 쉼표는 뺀다). 숫자가 없으면 problem.
    - 숫자 바로 뒤의 단위(표의 단위·차원별 표기·속성 단위)를 읽어 속성 단위로 바꾼다.
    - 숫자에 붙어 있는 모르는 영문 단위(예: '16XB')나 다른 차원의 단위(예: GHz 속성에 '16GB')면 problem.
    - 띄어 쓴 뒤 단위가 아닌 말('8 GDDR7')은 설명으로 보고 속성 단위로 읽는다.
    """
    text = (value_text or "").replace(",", "")
    match = _NUMBER.search(text)
    if match is None:
        return ReadNumber(None, None, None, f"숫자를 읽을 수 없음: {value_text}")
    raw = float(match.group())
    rest = text[match.end():]
    after = rest.lstrip()
    spaced = len(after) != len(rest)
    unit = _match_unit(after, attribute_unit)
    if unit is None:
        if not spaced and after[:1].isascii() and after[:1].isalpha():
            token = re.match(r"[A-Za-z/]+", after).group()
            return ReadNumber(None, raw, token, f"단위 확인 필요: 모르는 단위 '{token}' (속성 단위 {attribute_unit or '없음'})")
        return ReadNumber(raw, raw, None)
    converted = to_attribute_unit(raw, unit, attribute_unit, category)
    if converted is None:
        where = ", ".join(_dimensions_of(unit)) or "표에 없음"
        return ReadNumber(None, raw, unit, f"단위 확인 필요: '{unit}'({where})를 속성 단위 {attribute_unit or '없음'}로 바꿀 수 없음")
    return ReadNumber(converted, raw, unit)
