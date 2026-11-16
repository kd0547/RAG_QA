"""문서 그래프 만들기(페이지 텍스트 -> 개체·관계)와 검색(질문 -> 관련 개체·문서)."""
from __future__ import annotations

import logging
import time
from collections import defaultdict

import config
from graph_rag.extractor import extract_page_graph
from graph_rag.types import normalize
from repository import file_repo, graph_repo, page_repo

logger = logging.getLogger(__name__)

MAX_DOCUMENTS = 8
MAX_RELATIONS = 30
# 관계 행을 이만큼까지 읽어 같은 관계(출발·종류·도착)를 한 줄로 묶는다. 문서 관계는 근거 페이지마다 한 행이다
MAX_RELATION_ROWS = 300


# ------------------------------------------------------------ 만들기

def spec_names() -> dict | None:
    """사양 DB의 정식 이름 (설정이 꺼져 있으면 None). 파일 하나를 뽑는 동안 한 번만 읽는다."""
    if not config.GRAPH_SPEC_SEED_ENABLED:
        return None
    try:
        return graph_repo.spec_names()
    except Exception:
        logger.warning("사양 DB 이름을 읽지 못해 정식 이름 없이 뽑습니다", exc_info=True)
        return None


def known_names(names: dict | None, text: str) -> list[dict] | None:
    """추출 프롬프트에 넘길 정식 이름 (지시서 H3). 제품은 전부, 부품은 그 페이지에 정규화 문자열로 나오는 것만.

    제품 이름은 모델명을 담을 때만 다른 표기로 넣는다 (project_specs의 별칭 규칙과 같다).
    """
    if names is None:
        return None
    text_norm = normalize(text)
    known = [
        {"type": "product", "name": p["name"],
         "aliases": [a for a in p.get("aliases") or [] if normalize(p["name"]) in normalize(a)]}
        for p in names.get("product", [])
    ]
    known += [
        {"type": "component", "name": c["name"], "aliases": []}
        for c in names.get("component", [])
        if normalize(c["name"]) and normalize(c["name"]) in text_norm
    ]
    return known


def _known_kwargs(names: dict | None, text: str) -> dict:
    """설정이 꺼져 있으면 추출 호출이 예전과 똑같도록 known 인자 자체를 넘기지 않는다."""
    return {} if names is None else {"known": known_names(names, text)}


def index_page(file_id: str, page: int) -> dict:
    """검수 저장 뒤 그 페이지만 다시 뽑는다. xlsx처럼 같은 page 번호의 블록이 여럿이면 합쳐서 뽑는다."""
    rows = page_repo.pages_with_number(file_id, page)
    text = "\n\n".join(r["text"] for r in rows if r["text"])
    names = spec_names()
    graph = extract_page_graph(text, schema=graph_repo.extraction_schema(), **_known_kwargs(names, text))
    result = graph_repo.replace_page(file_id, page, graph, link_specs=names is not None)
    logger.info("그래프 페이지 추출: file_id=%s, page=%s, %s", file_id, page, result)
    return result


def index_file(file_id: str) -> dict:
    """파일의 저장된 페이지 텍스트 전체에서 그래프를 다시 만든다. 페이지 하나가 실패해도 나머지는 계속한다."""
    started = time.perf_counter()
    texts: dict[int, list[str]] = defaultdict(list)
    for row in page_repo.list_pages(file_id):
        if row["text"]:
            texts[row["page"]].append(row["text"])

    graph_repo.delete_file(file_id)
    names = spec_names()
    schema = graph_repo.extraction_schema()  # 파일 하나를 뽑는 동안 같은 종류 목록을 쓴다
    entities = relations = failed = 0
    dropped: dict[str, int] = defaultdict(int)
    for page, parts in sorted(texts.items()):
        try:
            text = "\n\n".join(parts)
            graph = extract_page_graph(text, schema=schema, **_known_kwargs(names, text))
            result = graph_repo.replace_page(file_id, page, graph, link_specs=names is not None)
        except Exception:
            failed += 1
            logger.warning("그래프 추출 실패: file_id=%s, page=%s", file_id, page, exc_info=True)
            continue
        entities += result["entities"]
        relations += result["relations"]
        for reason, count in result.get("dropped", {}).items():
            dropped[reason] += count

    summary = {"file_id": file_id, "pages": len(texts), "failed_pages": failed, "entities": entities, "relations": relations,
               "dropped": dict(dropped)}
    logger.info("그래프 파일 추출: %s, %.1f초", summary, time.perf_counter() - started)
    return summary


def index_all() -> list[dict]:
    """등록된 모든 파일의 그래프를 다시 만든다. 페이지 텍스트가 없는 옛 파일은 건너뛴다."""
    results = []
    for file in file_repo.file_list():
        if not page_repo.has_pages(file["file_id"]):
            logger.info("그래프 추출 건너뜀(페이지 텍스트 없음): %s", file["original_name"])
            continue
        results.append(index_file(file["file_id"]))
    return results


# ------------------------------------------------------------ 검색

def _evidence(relation: dict) -> str:
    """관계의 근거. 사람이 근거 문서 없이 넣은 관계는 '담당자 확인', 사양 DB에서 심은 관계는 '사양 DB'로 적는다."""
    if relation.get("origin") == "spec":
        return "사양 DB, 옵션" if relation.get("is_option") else "사양 DB"
    if relation.get('origin') == 'manual':
        return '사용자 입력 · read_graph_facts로 현재 근거 확인'
    if relation.get("file_id") and relation.get("original_name"):
        page = f' p{relation["page"]}' if relation.get("page") is not None else ""
        suffix = ", 담당자 확인" if relation.get("origin") == "manual" else ""
        return f'{relation["original_name"]}{page}{suffix}'
    return "담당자 확인"


def _evidence_group(rows: list[dict]) -> str:
    """같은 관계의 여러 출처를 한 근거 문장으로: 문서는 파일별로 페이지를 모은다 (예: "인증서.pdf p3, p5; 사양 DB")."""
    parts: list[str] = []
    pages: dict[str, list[str]] = {}
    for row in rows:
        if row.get("origin") not in ("spec", "manual") and row.get("file_id") and row.get("original_name"):
            name = row["original_name"]
            if name not in pages:
                pages[name] = []
                parts.append(f"\x00{name}")
            if row.get("page") is not None and f'p{row["page"]}' not in pages[name]:
                pages[name].append(f'p{row["page"]}')
        else:
            text = _evidence(row)
            if text not in parts:
                parts.append(text)
    return "; ".join(
        (f"{part[1:]} {', '.join(pages[part[1:]])}".rstrip() if part.startswith("\x00") else part) for part in parts
    )


def relation_lines(relations: list[dict], limit: int = MAX_RELATIONS) -> list[str]:
    """같은 관계(출발·종류·도착)를 한 줄로 묶은 "출발 -[종류]-> 도착 (근거)" 목록. 처음 나온 순서, 최대 limit줄."""
    groups: dict[tuple, list[dict]] = {}
    for relation in relations:
        groups.setdefault((relation["source_id"], relation["type"], relation["target_id"]), []).append(relation)
    lines = [f'{rows[0]["source_name"]} -[{rows[0]["type"]}]-> {rows[0]["target_name"]} ({_evidence_group(rows)})'
             for rows in groups.values()]
    return lines[:limit]


def search_graph(query: str, group_id: str | None = None, max_documents: int = MAX_DOCUMENTS) -> dict:
    """질문에 나온 개체를 찾고, 관계와 그 개체가 나온 문서 페이지를 돌려준다.

    문서는 질문에서 찾은 개체를 더 많이 담은 순서로 정렬한다. "N5800 안전확인 신고"면 N5800과 안전확인 신고가
    함께 나온 문서가 앞에 온다. 인증 묶음 이름(예: KC 인증)을 속한 종류로 펼치지 않는다 (지시서 GR1).

    matched에는 사양 DB 대상(ref_type, ref_id)을 싣는다. 모델은 이 값을 get_specs에 그대로 넘길 수 있다.
    파생 모델을 물으면 variant_of로 상위 모델이 나온 문서를 documents 뒤에 **후보로** 더하고 via("상위 모델 ○○")를 표시한다.
    상위 모델의 관계(인증 등)는 relations에 넣지 않는다 — 상위 모델의 인증을 파생 모델에 적용된 것으로 보이지 않게 한다.
    """
    matched = graph_repo.find_entities(query)
    if not matched:
        return {"matched": [], "documents": [], "message": "그래프에서 질문과 맞는 개체를 찾지 못했습니다. search_documents로 검색하세요."}

    # 문서 순위는 '질문에서 찾은 개체를 몇 개 담았는지'로 매긴다
    term_of: dict[int, int] = {e["id"]: e["id"] for e in matched}
    target_ids = list(term_of)

    # 사양 값 관계(has_spec)는 질문이 사양 값 노드일 때만 싣는다. 나머지는 개수만 (문서·부품·인증 관계를 밀어내지 않게, GR4-9)
    value_ids = [e["id"] for e in matched if e["type"] == "spec_value"]
    other_ids = [e["id"] for e in matched if e["type"] != "spec_value"]
    relations = graph_repo.relations_of(other_ids, group_id=group_id, limit=MAX_RELATION_ROWS, exclude_types=("has_spec",))
    if value_ids:
        known = {r["id"] for r in relations}
        relations += [r for r in graph_repo.relations_of(value_ids, group_id=group_id, limit=MAX_RELATION_ROWS)
                      if r["id"] not in known]
    spec_values = graph_repo.count_relations(other_ids, "has_spec")

    documents: dict[str, dict] = {}

    def _doc(file_id: str, original_name: str, stored_path: str | None) -> dict:
        if file_id not in documents:
            documents[file_id] = {
                "file_id": file_id, "source": stored_path, "original_name": original_name,
                "pages": set(), "entities": set(), "terms": set(),
            }
        return documents[file_id]

    for mention in graph_repo.mentions_of(target_ids, group_id=group_id):
        doc = _doc(mention["file_id"], mention["original_name"], mention["stored_path"])
        doc["pages"].add(mention["page"])
        doc["entities"].add(mention["entity_name"])
        doc["terms"].add(term_of[mention["entity_id"]])

    # 관계의 근거 페이지도 문서 후보다 (예: N5800 -> 안전확인 신고가 적힌 인증서 페이지)
    for relation in relations:
        if relation["file_id"] in documents:
            doc = documents[relation["file_id"]]
            doc["pages"].add(relation["page"])
            doc["entities"].update((relation["source_name"], relation["target_name"]))
            for end in ("source_id", "target_id"):
                if relation[end] in term_of:
                    doc["terms"].add(term_of[relation[end]])

    ranked = sorted(documents.values(), key=lambda d: (-len(d["terms"]), -len(d["entities"]), d["original_name"]))

    # 파생 모델이면 상위 모델이 나온 문서를 후보로 (이미 나온 문서는 그대로 두고, via를 붙여 뒤에 둔다)
    matched_ids = {e["id"] for e in matched}
    parents = [p for p in graph_repo.parents_of([e["id"] for e in matched if e["type"] == "product"])
               if p["parent_id"] not in matched_ids]
    via_documents: dict[str, dict] = {}
    for parent in parents:
        for mention in graph_repo.mentions_of([parent["parent_id"]], group_id=group_id):
            if mention["file_id"] in documents:
                continue
            doc = via_documents.setdefault(mention["file_id"], {
                "file_id": mention["file_id"], "source": mention["stored_path"], "original_name": mention["original_name"],
                "pages": set(), "entities": set(), "terms": set(), "via": f"상위 모델 {parent['parent_name']}",
            })
            doc["pages"].add(mention["page"])
            doc["entities"].add(mention["entity_name"])
    ranked += sorted(via_documents.values(), key=lambda d: d["original_name"])
    missing_paths = {d["file_id"] for d in ranked if not d["source"]}
    if missing_paths:
        logger.warning("그래프 문서의 저장 경로 없음: %s", missing_paths)

    return {
        "matched": [{"id":e["id"], "name": e["name"], "type": e["type"], "ref_type": e.get("ref_type"), "ref_id": e.get("ref_id")}
                    for e in matched],
        "relations": relation_lines(relations),
        "spec_values": spec_values,
        "documents": [
            {
                "file_id": d["file_id"],
                "source": d["source"],
                "original_name": d["original_name"],
                "pages": sorted(d["pages"]),
                "entities": sorted(d["entities"]),
                "matched_terms": len(d["terms"]),
                **({"via": d["via"]} if d.get("via") else {}),
            }
            for d in ranked[:max_documents]
        ],
        "total_documents": len(ranked),
    }
