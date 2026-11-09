"""페이지 텍스트에서 개체·관계를 뽑는다. 로컬 LLM 구조화 출력 + 인증번호 정규식."""
from __future__ import annotations

import logging
import re

import config
from graph_rag.types import (
    ENTITY_TYPES, RELATION_ENDPOINT_TYPES, RELATION_TYPES, ExtractedEntity, PageGraph, normalize,
)

logger = logging.getLogger(__name__)

_ENTITY_GUIDE = "\n".join(f"- {k}: {v}" for k, v in ENTITY_TYPES.items() if k != "concept")
_RELATION_GUIDE = "\n".join(f"- {k}: {v}" for k, v in RELATION_TYPES.items() if k != "part_of")

EXTRACT_PROMPT = f"""당신은 사내 문서(제품 제안서, 세일즈 가이드, 인증서, 시험성적서)에서 검색용 지식 그래프를 만드는 추출기입니다.
주어진 페이지에서 아래 종류의 개체와 관계만 뽑으세요.

## 개체 종류
{_ENTITY_GUIDE}

## 관계 종류 (source -> target)
{_RELATION_GUIDE}

## 규칙
- 페이지에 실제로 적힌 표기만 쓰세요. 추측하거나 일반 지식으로 채우지 마세요.
- 일반 명사(노트북, 제품, 인증서, 회사 등)만 있는 것은 개체가 아닙니다. 모델명·고유 이름·번호가 있어야 합니다.
- 같은 대상을 다르게 쓴 표기는 aliases에 넣고 하나의 개체로 뽑으세요.
- relations의 source와 target은 entities의 name과 똑같이 쓰세요.
- 뽑을 것이 없으면 빈 목록을 돌려주세요."""

_CONCEPT_GUIDE = """

## 상위 개념
certification 개체가 아래 상위 개념에 속하면 concept에 상위 개념 이름을 그대로 적으세요. 표기가 달라도 같은 인증이면 속합니다
(예: "KC 안전확인"은 "안전확인 신고"와 같은 인증). 속하지 않거나 확실하지 않으면 null로 두세요.
{concepts}"""

# KC 전파 적합성 등록번호 (R-R-TGE-N5800, R-C-..., 옛 형식 MSIP-REM-..., KCC-REM-...)
_KC_REGISTRATION = re.compile(r"\b(?:R|MSIP|KCC)-[A-Z]{1,3}-[A-Za-z0-9]{2,6}-[A-Za-z0-9][A-Za-z0-9\-]{1,30}\b")


def extract_page_graph(text: str, llm=None, concepts: list[dict] | None = None) -> PageGraph:
    """한 페이지 텍스트의 개체·관계. LLM이 실패하면 예외를 그대로 던진다 (호출부가 기록).

    concepts는 graph_repo.list_concepts() 결과다. 주면 인증 종류마다 속하는 상위 개념을 같이 고르게 한다.
    """
    text = (text or "").strip()
    if not text:
        return PageGraph()

    if llm is None:
        from agent.llm_provider import get_llm_model  # 서버 부트스트랩이 주입한 모델
        llm = get_llm_model("local")
    structured = llm.with_structured_output(PageGraph)
    result = structured.invoke([
        {"role": "system", "content": _system_prompt(concepts)},
        {"role": "user", "content": text[:config.GRAPH_EXTRACT_MAX_CHARS]},
    ])
    graph = result if isinstance(result, PageGraph) else PageGraph.model_validate(result or {})
    _add_relation_endpoints(graph)
    _add_registration_numbers(graph, text)
    graph = _keep_grounded(graph, text)
    _keep_known_concepts(graph, concepts)
    return graph


def _system_prompt(concepts: list[dict] | None) -> str:
    if not concepts:
        return EXTRACT_PROMPT
    lines = "\n".join(f"- {c['name']}: {', '.join(c['members'])}" for c in concepts)
    return EXTRACT_PROMPT + _CONCEPT_GUIDE.format(concepts=lines)


def _add_relation_endpoints(graph: PageGraph) -> None:
    """관계에는 있는데 entities에서 빠진 이름을 관계 종류로 개체 종류를 정해 채운다 (예: has_component의 target -> component)."""
    known = {normalize(e.name) for e in graph.entities}
    for e in graph.entities:
        known.update(normalize(a) for a in e.aliases)
    for relation in graph.relations:
        source_type, target_type = RELATION_ENDPOINT_TYPES.get(relation.type, (None, None))
        for name, entity_type in ((relation.source, source_type), (relation.target, target_type)):
            if entity_type and normalize(name) and normalize(name) not in known:
                graph.entities.append(ExtractedEntity(type=entity_type, name=name))
                known.add(normalize(name))


def _keep_known_concepts(graph: PageGraph, concepts: list[dict] | None) -> None:
    """상위 개념은 이미 있는 것만 쓴다. LLM이 새로 지어낸 개념이나 인증이 아닌 개체의 개념은 지운다."""
    names = {normalize(c["name"]): c["name"] for c in concepts or []}
    for entity in graph.entities:
        if entity.concept is None:
            continue
        entity.concept = names.get(normalize(entity.concept)) if entity.type == "certification" else None


def _add_registration_numbers(graph: PageGraph, text: str) -> None:
    """LLM이 놓치기 쉬운 KC 등록번호를 정규식으로 보탠다."""
    known = {normalize(e.name) for e in graph.entities}
    for match in dict.fromkeys(m.group(0) for m in _KC_REGISTRATION.finditer(text)):
        if normalize(match) not in known:
            graph.entities.append(ExtractedEntity(type="cert_number", name=match))
            known.add(normalize(match))


def _keep_grounded(graph: PageGraph, text: str) -> PageGraph:
    """페이지에 실제로 없는 이름(LLM이 지어낸 것)은 버린다. 비교는 공백·기호를 뺀 정규화 키로 한다."""
    text_norm = normalize(text)
    entities = []
    dropped = []
    for entity in graph.entities:
        if normalize(entity.name) and normalize(entity.name) in text_norm:
            entity.aliases = [a for a in entity.aliases if normalize(a) and normalize(a) in text_norm]
            entities.append(entity)
        else:
            dropped.append(entity.name)
    if dropped:
        logger.debug("페이지에 없는 개체 이름 제외: %s", dropped)
    graph.entities = entities
    return graph
