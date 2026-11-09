"""문서 그래프의 개체·관계 종류와 LLM 추출 결과 형식."""
from __future__ import annotations

import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, Field

# 개체 종류. 마음대로 뽑게 하면 잡음이 많아서 이 시스템의 질문(제품·인증 찾기)에 필요한 것만 둔다.
ENTITY_TYPES: dict[str, str] = {
    "product": "자사·타사 제품 모델 (예: N5800, A650)",
    "component": "부품·구성품 (예: CPU, GPU, 메모리, 디스플레이 모델)",
    "certification": "인증·신고·시험의 종류 (예: 안전확인 신고, 적합성 등록, 에너지소비효율)",
    "cert_number": "인증서·등록·신고·시험성적서 번호 (예: R-R-TGE-N5800)",
    "organization": "회사·시험기관·발급기관 (예: 국립전파연구원, KTL)",
    "standard": "규격·표준·기준 (예: KN 32, IEC 62368-1)",
    "concept": "여러 인증 종류를 묶는 상위 개념 (예: KC 인증). aliases.yaml에서만 만든다",
}
EntityType = Literal["product", "component", "certification", "cert_number", "organization", "standard"]

# 관계 종류 (src -> dst)
RELATION_TYPES: dict[str, str] = {
    "has_component": "제품 -> 부품",
    "has_certification": "제품 -> 인증 종류",
    "has_number": "인증 종류 또는 제품 -> 인증·등록 번호",
    "issued_by": "인증 종류 또는 번호 -> 발급·시험 기관",
    "complies_with": "제품 또는 인증 -> 규격·표준",
    "part_of": "인증 종류 -> 상위 개념. aliases.yaml에서만 만든다",
}
RelationType = Literal["has_component", "has_certification", "has_number", "issued_by", "complies_with"]

# 관계 양 끝의 개체 종류. LLM이 관계에는 썼지만 entities에서 빠뜨린 이름을 채울 때 쓴다 (None이면 추론하지 않음)
RELATION_ENDPOINT_TYPES: dict[str, tuple[str | None, str]] = {
    "has_component": ("product", "component"),
    "has_certification": ("product", "certification"),
    "has_number": (None, "cert_number"),
    "issued_by": (None, "organization"),
    "complies_with": (None, "standard"),
}

_NORM_STRIP = re.compile(r"[\s\-_·.,/()\[\]{}:;'\"]+")


def normalize(text: str) -> str:
    """비교용 키. 전각/반각을 맞추고 소문자로 바꾼 뒤 공백·기호를 뺀다. 'KC 인증' == 'KC인증'."""
    text = unicodedata.normalize("NFKC", text or "").lower()
    return _NORM_STRIP.sub("", text)


class ExtractedEntity(BaseModel):
    type: EntityType = Field(description="개체 종류")
    name: str = Field(description="문서에 적힌 그대로의 이름")
    aliases: list[str] = Field(default_factory=list, description="같은 페이지에 나온 다른 표기 (없으면 빈 목록)")
    concept: str | None = Field(default=None, description="certification일 때 속하는 상위 개념 이름. 없거나 모르면 null")


class ExtractedRelation(BaseModel):
    source: str = Field(description="출발 개체 이름 (entities의 name과 같게)")
    type: RelationType = Field(description="관계 종류")
    target: str = Field(description="도착 개체 이름 (entities의 name과 같게)")


class PageGraph(BaseModel):
    entities: list[ExtractedEntity] = Field(default_factory=list)
    relations: list[ExtractedRelation] = Field(default_factory=list)
