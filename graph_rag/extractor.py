"""페이지 텍스트에서 개체·관계를 뽑는다. 로컬 LLM 구조화 출력 + 인증번호 정규식."""
from __future__ import annotations

import logging
import re

from pydantic import BaseModel

import config
from graph_rag.schema import ExtractionSchema, default_schema, page_graph_model
from graph_rag.types import RELATION_ENDPOINT_TYPES, ExtractedEntity, PageGraph, normalize

logger = logging.getLogger(__name__)

_PROMPT_TEMPLATE = """당신은 사내 문서(제품 제안서, 세일즈 가이드, 인증서, 시험성적서)에서 검색용 지식 그래프를 만드는 추출기입니다.
주어진 페이지에서 아래 종류의 개체와 관계만 뽑으세요.

## 개체 종류
{entity_guide}

## 관계 종류 (source -> target)
{relation_guide}

## 규칙
- 페이지에 실제로 적힌 표기만 쓰세요. 추측하거나 일반 지식으로 채우지 마세요.
- 일반 명사(노트북, 제품, 인증서, 회사 등)만 있는 것은 개체가 아닙니다. 모델명·고유 이름·번호가 있어야 합니다.
- 같은 대상을 다르게 쓴 표기는 aliases에 넣고 하나의 개체로 뽑으세요.
- relations의 source와 target은 entities의 name과 똑같이 쓰세요.
- 뽑을 것이 없으면 빈 목록을 돌려주세요."""



def _type_label(schema: ExtractionSchema, key: str) -> str:
    row = schema.all_entity_types.get(key)
    return f"{key}({row['label']})" if row else key


def build_extract_prompt(schema: ExtractionSchema) -> str:
    """추출 프롬프트. 종류 안내는 테이블의 description, 관계 안내는 description과 허용 출발·도착 종류로 만든다 (GR2)."""
    entity_guide = "\n".join(f"- {_type_label(schema, t['key'])}: {t['description']}" for t in schema.entity_types) or "- (없음)"
    allowed = set(schema.entity_keys)
    lines = []
    for r in schema.relation_types:
        sources = [k for k in r["source_entity_types"] if k in allowed]
        targets = [k for k in r["target_entity_types"] if k in allowed]
        ends = f" (출발: {', '.join(sources) or '-'} → 도착: {', '.join(targets) or '-'})"
        lines.append(f"- {r['key']}({r['label']}): {r['description']}{ends}")
    return _PROMPT_TEMPLATE.format(entity_guide=entity_guide, relation_guide="\n".join(lines) or "- (없음)")


# 기본 종류로 만든 프롬프트 (DB 없이 부를 때와 테스트용)
EXTRACT_PROMPT = build_extract_prompt(default_schema())

_KNOWN_GUIDE = """

## 사양 DB의 정식 이름
아래 목록의 대상과 같은 것이면 목록의 이름을 name으로 쓰고 문서 표기는 aliases에 넣는다.
목록에 없는 제품(타사 모델 등)은 지금처럼 문서 표기 그대로 뽑는다. 이름이 비슷해도 다른 모델(예: N5800과 N5800-GB70-PU02)은 다른 대상이다.
{items}"""

# KC 전파 적합성 등록번호 (R-R-TGE-N5800, R-C-..., 옛 형식 MSIP-REM-..., KCC-REM-...)
_KC_REGISTRATION = re.compile(r"\b(?:R|MSIP|KCC)-[A-Z]{1,3}-[A-Za-z0-9]{2,6}-[A-Za-z0-9][A-Za-z0-9\-]{1,30}\b")


def extract_page_graph(text: str, llm=None, known: list[dict] | None = None,
                       schema: ExtractionSchema | None = None) -> PageGraph:
    """한 페이지 텍스트의 개체·관계. LLM이 실패하면 예외를 그대로 던진다 (호출부가 기록).

    schema는 그때의 개체·관계 종류다 (graph_repo.extraction_schema()). None이면 기본 종류를 쓴다.
    활성·추출 대상 종류로 구조화 출력 형식(type Literal)을 만든다. 뽑을 종류가 없으면 LLM을 부르지 않는다.

    known은 사양 DB의 정식 이름 [{"type": "product"|"component", "name": 모델명, "aliases": [다른 표기]}]이다 (지시서 H3).
    주면 같은 대상을 정식 이름으로 뽑게 하고, 정식 이름이 페이지에 없어도 별칭 중 하나가 있으면 남긴다.
    None이면 프롬프트와 걸러내기가 예전과 같다.
    """
    text = (text or "").strip()
    schema = schema or default_schema()
    model = page_graph_model(schema)
    if not text or model is None:
        return PageGraph()

    if llm is None:
        from agent.llm_provider import get_llm_model  # 서버 부트스트랩이 주입한 모델
        llm = get_llm_model("local")
    structured = llm.with_structured_output(model)
    result = structured.invoke([
        {"role": "system", "content": _system_prompt(known, schema)},
        {"role": "user", "content": text[:config.GRAPH_EXTRACT_MAX_CHARS]},
    ])
    if isinstance(result, BaseModel):
        result = result.model_dump()
    graph = PageGraph.model_validate(result or {})
    _add_relation_endpoints(graph)
    _add_registration_numbers(graph, text)
    graph = _keep_grounded(graph, text, {normalize(k["name"]) for k in known or []} - {""})
    return graph


_KNOWN_TYPE_LABELS = {"product": "제품", "component": "부품"}


def _system_prompt(known: list[dict] | None = None, schema: ExtractionSchema | None = None) -> str:
    prompt = EXTRACT_PROMPT if schema is None else build_extract_prompt(schema)
    if known:
        items = []
        for item in known:
            line = f"- {item['type']}({_KNOWN_TYPE_LABELS.get(item['type'], item['type'])}): {item['name']}"
            aliases = [a for a in item.get("aliases") or [] if a and a != item["name"]]
            if aliases:
                line += f" (다른 표기: {', '.join(aliases)})"
            items.append(line)
        prompt += _KNOWN_GUIDE.format(items="\n".join(items))
    return prompt


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


def _add_registration_numbers(graph: PageGraph, text: str) -> None:
    """LLM이 놓치기 쉬운 KC 등록번호를 정규식으로 보탠다."""
    known = {normalize(e.name) for e in graph.entities}
    for match in dict.fromkeys(m.group(0) for m in _KC_REGISTRATION.finditer(text)):
        if normalize(match) not in known:
            graph.entities.append(ExtractedEntity(type="cert_number", name=match))
            known.add(normalize(match))


def _keep_grounded(graph: PageGraph, text: str, known_norms: set[str] | None = None) -> PageGraph:
    """페이지에 실제로 없는 이름(LLM이 지어낸 것)은 버린다. 비교는 공백·기호를 뺀 정규화 키로 한다.

    사양 DB의 정식 이름(known_norms)으로 뽑은 개체는 정식 이름이 페이지에 없어도 별칭 중 하나가 페이지에 있으면 남긴다
    (문서는 "A650 Pro"로 적고 정식 이름은 "A650-GA70-PU02"인 경우). 별칭은 페이지에 있는 것만 남긴다.
    """
    text_norm = normalize(text)
    entities = []
    dropped = []
    for entity in graph.entities:
        name_norm = normalize(entity.name)
        aliases = [a for a in entity.aliases if normalize(a) and normalize(a) in text_norm]
        grounded = bool(name_norm) and name_norm in text_norm
        if grounded or (known_norms and name_norm in known_norms and aliases):
            entity.aliases = aliases
            entities.append(entity)
        else:
            dropped.append(entity.name)
    if dropped:
        logger.debug("페이지에 없는 개체 이름 제외: %s", dropped)
    graph.entities = entities
    return graph
