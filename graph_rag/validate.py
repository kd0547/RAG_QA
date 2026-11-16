"""문서 추출 결과를 저장 전에 거른다 (지시서 GR3-3). 문서 자동 추출에만 쓴다 — 사람의 편집에는 적용하지 않는다.

순서
1. 정식 종류 우선: 이름(또는 별칭)의 정식 이름 맞춤 키가 사양 DB 노드와 같으면 그 노드의 **현재 종류·이름**으로 바꿔 붙인다
2. 종류 검사: 활성·추출 대상 종류가 아니면 버린다
3. 식별자 규칙: requires_identifier 종류는 이름·별칭 중 하나에 식별자가 있어야 한다 (1번에서 붙은 개체는 건너뛴다)
4. 관계 검사: 끝이 남은 개체여야 하고, 관계 종류가 활성·추출 대상이고, 출발·도착 종류가 허용 종류여야 한다.
   방향만 반대면 뒤집어 받는다
5. 자기 자신을 가리키는 관계는 버린다

DB·저장소를 임포트하지 않는다. 사양 노드 목록(spec_index)은 저장소가 만들어 넘긴다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from graph_rag.rules import DEFAULT_VENDOR_PREFIXES, has_identifier, spec_match_keys
from graph_rag.schema import ExtractionSchema
from graph_rag.types import ExtractedRelation, PageGraph, normalize

DROP_REASONS = ("type", "identifier", "relation_endpoint", "relation_type")


@dataclass
class SpecIndex:
    """정식 이름 맞춤 키 → 사양 DB 노드 (id, 현재 종류, 현재 이름). 두 노드가 같은 키를 가지면 그 키로는 붙이지 않는다."""
    nodes: dict[str, tuple[int, str, str]] = field(default_factory=dict)
    ambiguous: set[str] = field(default_factory=set)
    # 검사 중 붙인 개체: (종류, 정규화 이름) → 노드 id. 저장소가 이름으로 다시 찾지 않고 이 노드에 붙인다
    attached: dict[tuple[str, str], int] = field(default_factory=dict)

    def add(self, entity_id: int, entity_type: str, name: str, names, vendors=DEFAULT_VENDOR_PREFIXES) -> None:
        for text in names:
            for key in spec_match_keys(text, vendors):
                current = self.nodes.get(key)
                if current is not None and current[0] != entity_id:
                    self.ambiguous.add(key)
                else:
                    self.nodes[key] = (entity_id, entity_type, name)

    def find(self, names, vendors=DEFAULT_VENDOR_PREFIXES) -> tuple[int, str, str] | None:
        for text in names:
            for key in spec_match_keys(text, vendors):
                if key in self.nodes and key not in self.ambiguous:
                    return self.nodes[key]
        return None


def validate_page_graph(graph: PageGraph, schema: ExtractionSchema, spec_index: SpecIndex | None = None,
                        vendors=DEFAULT_VENDOR_PREFIXES) -> tuple[PageGraph, dict[str, int]]:
    """걸러낸 그래프와 사유별로 버린 수. 입력 graph는 바꾸지 않는다."""
    dropped = {reason: 0 for reason in DROP_REASONS}
    allowed_types = set(schema.entity_keys)
    kept = []
    for original in graph.entities:
        entity = original.model_copy(deep=True)
        names = [entity.name, *entity.aliases]
        attached = spec_index.find(names, vendors) if spec_index else None
        if attached is not None:
            node_id, node_type, node_name = attached
            if normalize(node_name) != normalize(entity.name):
                entity.aliases = list(dict.fromkeys([entity.name, *entity.aliases]))
            entity.type, entity.name = node_type, node_name
            spec_index.attached[(node_type, normalize(node_name))] = node_id
        if entity.type not in allowed_types:
            dropped["type"] += 1
            continue
        row = schema.all_entity_types.get(entity.type) or {}
        if attached is None and row.get("requires_identifier") and not has_identifier([entity.name, *entity.aliases]):
            dropped["identifier"] += 1
            continue
        kept.append(entity)

    type_of: dict[str, str] = {}
    for entity in kept:
        for text in (entity.name, *entity.aliases):
            type_of.setdefault(normalize(text), entity.type)
    relation_rules = {r["key"]: r for r in schema.relation_types}
    relations, seen = [], set()
    for relation in graph.relations:
        source_type = type_of.get(normalize(relation.source))
        target_type = type_of.get(normalize(relation.target))
        if source_type is None or target_type is None:
            dropped["relation_endpoint"] += 1
            continue
        if normalize(relation.source) == normalize(relation.target) or _same_entity(kept, relation.source, relation.target):
            dropped["relation_endpoint"] += 1
            continue
        rule = relation_rules.get(relation.type)
        if rule is None:
            dropped["relation_type"] += 1
            continue
        sources, targets = set(rule["source_entity_types"]), set(rule["target_entity_types"])
        if source_type in sources and target_type in targets:
            item = ExtractedRelation(source=relation.source, type=relation.type, target=relation.target)
        elif target_type in sources and source_type in targets:
            item = ExtractedRelation(source=relation.target, type=relation.type, target=relation.source)
        else:
            dropped["relation_type"] += 1
            continue
        key = (normalize(item.source), item.type, normalize(item.target))
        if key not in seen:
            seen.add(key)
            relations.append(item)
    return PageGraph(entities=kept, relations=relations), dropped


def _same_entity(entities, left: str, right: str) -> bool:
    """두 이름이 같은 개체(이름·별칭)를 가리키면 True."""
    left_norm, right_norm = normalize(left), normalize(right)
    for entity in entities:
        names = {normalize(n) for n in (entity.name, *entity.aliases)}
        if left_norm in names and right_norm in names:
            return True
    return False
