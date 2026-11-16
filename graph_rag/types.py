"""문서 그래프의 개체·관계 종류와 LLM 추출 결과 형식."""
from __future__ import annotations

import re
import unicodedata
from pydantic import BaseModel, Field

from graph_rag.defaults import DEFAULT_RELATION_TYPES

# 개체 종류는 graph_entity_type 테이블에 있다 (지시서 GR2). 기본값은 graph_rag/defaults.py.
# 관계 종류의 기본값 (src -> dst 설명). 실행 중의 목록은 graph_relation_type 테이블이다.
RELATION_TYPES: dict[str, str] = {r["key"]: r["description"] for r in DEFAULT_RELATION_TYPES}
# 기본 관계 중 문서 추출에 쓰지 않는 것 (사양 DB에서만 만든다)
NON_EXTRACT_RELATIONS = frozenset(r["key"] for r in DEFAULT_RELATION_TYPES if not r["extract"])

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
    """추출 결과 개체. type은 graph_entity_type의 key다 (LLM 출력 형식은 graph_rag/schema.py가 그때 만든다)."""
    type: str = Field(description="개체 종류")
    name: str = Field(description="문서에 적힌 그대로의 이름")
    aliases: list[str] = Field(default_factory=list, description="같은 페이지에 나온 다른 표기 (없으면 빈 목록)")


class ExtractedRelation(BaseModel):
    source: str = Field(description="출발 개체 이름 (entities의 name과 같게)")
    type: str = Field(description="관계 종류")
    target: str = Field(description="도착 개체 이름 (entities의 name과 같게)")


class PageGraph(BaseModel):
    entities: list[ExtractedEntity] = Field(default_factory=list)
    relations: list[ExtractedRelation] = Field(default_factory=list)
