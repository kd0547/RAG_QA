"""문서 자동 추출을 거르는 규칙 중 DB 없이 계산하는 것 (지시서 GR3-3 식별자, GR3-4 정식 이름 맞춤 키).

점검 스크립트(scripts/audit_graph.py)도 쓴다. 저장소(repository)·설정(config)을 임포트하지 않는다 —
점검 스크립트가 운영 DB를 열거나 마이그레이션하지 않게 하기 위해서다.
"""
from __future__ import annotations

import re
import unicodedata

from graph_rag.types import normalize

# 기본 제조사 접두어 (config.GRAPH_VENDOR_PREFIXES의 기본값과 같다)
DEFAULT_VENDOR_PREFIXES: tuple[str, ...] = (
    "NVIDIA", "AMD", "Intel", "Qualcomm", "Samsung", "SK hynix", "Micron", "Kingston", "WD", "Seagate",
    "Realtek", "MediaTek",
)

# 영숫자 토큰: N5800, N5800-GB70-PU02, R-R-TGE-N5800, PM9C1b
_TOKEN = re.compile(r"[A-Za-z0-9]+(?:[-_.][A-Za-z0-9]+)*")
# 끝 괄호: "NVIDIA GeForce RTX 5070 (105W)"
_TRAILING_PAREN = re.compile(r"\s*[\(\[（［][^()\[\]（）［］]*[\)\]）］]\s*$")
# 끝의 일반 명사 (긴 것부터)
_TRAILING_NOUNS = ("processor", "graphics", "프로세서", "그래픽", "칩셋", "cpu", "gpu")
_MARKS = str.maketrans("", "", "™®©")


def has_identifier(names) -> bool:
    """이름이나 별칭 중 하나에 숫자가 든 영숫자 토큰(기호 빼고 3자 이상)이 있으면 True.

    N5800, 5070, PM9C1b, R-R-TGE-N5800은 식별자다. Tensor 코어, RT 코어, Blackwell 아키텍처, Radeon, Ryzen, XDNA는 아니다.
    "XDNA 2", "4세대"처럼 숫자 한두 자만 붙은 것도 식별자로 보지 않는다.
    """
    if isinstance(names, str):
        names = [names]
    for name in names or []:
        for token in _TOKEN.findall(unicodedata.normalize("NFKC", name or "")):
            compact = re.sub(r"[-_.]", "", token)
            if len(compact) >= 3 and any(ch.isdigit() for ch in compact):
                return True
    return False


def _strip(name: str) -> str:
    text = (name or "").translate(_MARKS)  # NFKC는 ™를 TM으로 바꾸므로 먼저 지운다
    text = unicodedata.normalize("NFKC", text).strip()
    while True:
        before = text
        text = _TRAILING_PAREN.sub("", text).strip()
        lowered = text.lower()
        for noun in _TRAILING_NOUNS:
            if lowered.endswith(noun) and len(text) > len(noun):
                head = text[: -len(noun)]
                # 단어 중간(예: "eGPU")은 자르지 않는다. 한글 명사는 붙여 써도 뗀다
                if not head[-1:].isascii() or not head[-1:].isalnum() or not noun.isascii():
                    text = head.rstrip(" -_·")
                    break
        if text == before:
            return text


def without_vendor(name: str, vendors=DEFAULT_VENDOR_PREFIXES) -> str | None:
    """첫 단어(또는 두 단어)가 제조사 이름이면 그것을 뺀 이름. 아니면 None."""
    text = (name or "").strip()
    lowered = text.lower()
    for vendor in sorted(vendors or (), key=len, reverse=True):
        prefix = vendor.lower()
        if lowered.startswith(prefix) and len(text) > len(prefix) and text[len(prefix)] in " \t-_":
            rest = text[len(prefix):].strip(" \t-_")
            return rest or None
    return None


def spec_match_keys(name: str, vendors=DEFAULT_VENDOR_PREFIXES) -> list[str]:
    """사양 DB 대조용 키 (지시서 GR3-4). normalize()와 따로 둔다 (기존 norm을 바꾸지 않기 위해).

    ™·®·© 제거 → 끝 괄호 제거 → 끝 일반 명사 제거 → (제조사 접두어를 뺀 것도) → normalize.
    첫 항목이 대표 키다. 예: "AMD Ryzen™ AI 7 350 프로세서" → ["amdryzenai7350", "ryzenai7350"]
    """
    stripped = _strip(name)
    keys = [normalize(stripped)]
    rest = without_vendor(stripped, vendors)
    if rest:
        keys.append(normalize(rest))
    return [k for k in dict.fromkeys(keys) if k]


def spec_match_key(name: str, vendors=DEFAULT_VENDOR_PREFIXES) -> str:
    keys = spec_match_keys(name, vendors)
    return keys[0] if keys else ""
