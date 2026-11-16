"""실행 중의 개체·관계 종류 (지시서 GR2). 테이블에서 읽고, 문서 추출용 구조화 출력 형식을 그때 만든다.

종류 목록이 같으면 만든 형식을 재사용한다 (종류·관계 종류의 key·revision 목록으로 캐시).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field, create_model

from graph_rag.defaults import DEFAULT_ENTITY_TYPES, DEFAULT_RELATION_TYPES


@dataclass(frozen=True)
class ExtractionSchema:
    """문서 추출이 쓰는 종류. entity_types·relation_types는 활성·추출 대상만, 정렬된 순서."""
    entity_types: tuple[dict, ...]
    relation_types: tuple[dict, ...]
    all_entity_types: dict = field(default_factory=dict)    # key -> 행 (사용 중지 포함)
    all_relation_types: dict = field(default_factory=dict)  # key -> 행 (사용 중지 포함)
    cache_key: tuple = ()

    @property
    def entity_keys(self) -> list[str]:
        return [t["key"] for t in self.entity_types]

    @property
    def relation_keys(self) -> list[str]:
        return [t["key"] for t in self.relation_types]


def _relation_row(row: dict) -> dict:
    item = dict(row)
    for key in ("source_entity_types", "target_entity_types"):
        if isinstance(item.get(key), str):
            item[key] = json.loads(item[key])
    return item


def build_schema(entity_rows, relation_rows) -> ExtractionSchema:
    entities = sorted((dict(r) for r in entity_rows), key=lambda r: (r.get("sort_order", 0), r["key"]))
    relations = sorted((_relation_row(r) for r in relation_rows), key=lambda r: (not r.get("builtin", 0), r["key"]))
    active_entities = tuple(e for e in entities if e.get("active", 1) and e.get("extract", 0))
    active_relations = tuple(r for r in relations if r.get("active", 1) and r.get("extract", 0))
    cache_key = (tuple((e["key"], e.get("revision", 1), e.get("active", 1), e.get("extract", 0)) for e in entities),
                 tuple((r["key"], r.get("revision", 1), r.get("active", 1), r.get("extract", 0)) for r in relations))
    return ExtractionSchema(active_entities, active_relations, {e["key"]: e for e in entities},
                            {r["key"]: r for r in relations}, cache_key)


def default_schema() -> ExtractionSchema:
    """DB 없이 쓰는 기본 종류 (테스트·대역 호출용). 마이그레이션이 넣는 기본값과 같다."""
    entities = [{**e, "active": 1, "builtin": 1, "revision": 1, "sort_order": i * 10}
                for i, e in enumerate(DEFAULT_ENTITY_TYPES)]
    relations = [{"key": r["key"], "label": r["label"], "description": r["description"],
                  "source_entity_types": list(r["source"]), "target_entity_types": list(r["target"]),
                  "extract": r["extract"], "active": 1, "builtin": 1, "revision": 1, "allow_self": 0}
                 for r in DEFAULT_RELATION_TYPES]
    return build_schema(entities, relations)


def load_schema(conn) -> ExtractionSchema:
    return build_schema(conn.execute("SELECT * FROM graph_entity_type"), conn.execute("SELECT * FROM graph_relation_type"))


_MODEL_CACHE: dict[tuple, type[BaseModel]] = {}


def page_graph_model(schema: ExtractionSchema) -> type[BaseModel] | None:
    """LLM 구조화 출력 형식. type이 그때의 활성·추출 대상 종류의 Literal이다. 뽑을 종류가 없으면 None."""
    if not schema.entity_keys:
        return None
    cached = _MODEL_CACHE.get(schema.cache_key)
    if cached is not None:
        return cached
    entity_literal = Literal[tuple(schema.entity_keys)]  # type: ignore[valid-type]
    entity = create_model(
        "ExtractedEntity",
        type=(entity_literal, Field(description="개체 종류")),
        name=(str, Field(description="문서에 적힌 그대로의 이름")),
        aliases=(list[str], Field(default_factory=list, description="같은 페이지에 나온 다른 표기 (없으면 빈 목록)")),
    )
    fields = {"entities": (list[entity], Field(default_factory=list))}
    if schema.relation_keys:
        relation_literal = Literal[tuple(schema.relation_keys)]  # type: ignore[valid-type]
        relation = create_model(
            "ExtractedRelation",
            source=(str, Field(description="출발 개체 이름 (entities의 name과 같게)")),
            type=(relation_literal, Field(description="관계 종류")),
            target=(str, Field(description="도착 개체 이름 (entities의 name과 같게)")),
        )
        fields["relations"] = (list[relation], Field(default_factory=list))
    model = create_model("PageGraph", **fields)
    _MODEL_CACHE[schema.cache_key] = model
    return model
