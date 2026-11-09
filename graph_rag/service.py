"""문서 그래프 만들기(페이지 텍스트 -> 개체·관계)와 검색(질문 -> 관련 개체·문서)."""
from __future__ import annotations

import logging
import time
from collections import defaultdict

from graph_rag.extractor import extract_page_graph
from repository import file_repo, graph_repo, page_repo

logger = logging.getLogger(__name__)

MAX_DOCUMENTS = 8
MAX_RELATIONS = 30


# ------------------------------------------------------------ 만들기

def index_page(file_id: str, page: int) -> dict:
    """검수 저장 뒤 그 페이지만 다시 뽑는다. xlsx처럼 같은 page 번호의 블록이 여럿이면 합쳐서 뽑는다."""
    rows = page_repo.pages_with_number(file_id, page)
    text = "\n\n".join(r["text"] for r in rows if r["text"])
    result = graph_repo.replace_page(file_id, page, extract_page_graph(text, concepts=graph_repo.list_concepts()))
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
    concepts = graph_repo.list_concepts()
    entities = relations = failed = 0
    for page, parts in sorted(texts.items()):
        try:
            result = graph_repo.replace_page(file_id, page, extract_page_graph("\n\n".join(parts), concepts=concepts))
        except Exception:
            failed += 1
            logger.warning("그래프 추출 실패: file_id=%s, page=%s", file_id, page, exc_info=True)
            continue
        entities += result["entities"]
        relations += result["relations"]

    summary = {"file_id": file_id, "pages": len(texts), "failed_pages": failed, "entities": entities, "relations": relations}
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
    """관계의 근거. 사람이 근거 문서 없이 넣은 관계는 '담당자 확인'으로 적는다."""
    if relation.get("file_id") and relation.get("original_name"):
        page = f' p{relation["page"]}' if relation.get("page") is not None else ""
        suffix = ", 담당자 확인" if relation.get("origin") == "manual" else ""
        return f'{relation["original_name"]}{page}{suffix}'
    return "담당자 확인"


def search_graph(query: str, group_id: str | None = None, max_documents: int = MAX_DOCUMENTS) -> dict:
    """질문에 나온 개체를 찾고, 상위 개념을 펼치고, 관계와 그 개체가 나온 문서 페이지를 돌려준다.

    문서는 질문의 개체를 더 많이 담은 순서로 정렬한다. "N5800 KC인증"이면 N5800과 KC 인증 종류가
    함께 나온 문서가 앞에 온다.
    """
    matched = graph_repo.find_entities(query)
    if not matched:
        return {"matched": [], "documents": [], "message": "그래프에서 질문과 맞는 개체를 찾지 못했습니다. search_documents로 검색하세요."}

    concepts = [e for e in matched if e["type"] == "concept"]
    members = graph_repo.concept_members([c["id"] for c in concepts])

    # 문서 순위는 '질문의 몇 가지 대상을 담았는지'로 매긴다. 상위 개념의 인증 종류들은 그 개념 하나로 센다.
    term_of: dict[int, int] = {e["id"]: e["id"] for e in matched if e["type"] != "concept"}
    for member in members:
        term_of.setdefault(member["id"], member["concept_id"])
    target_ids = list(term_of)

    relations = graph_repo.relations_of(target_ids, group_id=group_id, limit=MAX_RELATIONS)

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
    missing_paths = {d["file_id"] for d in ranked if not d["source"]}
    if missing_paths:
        logger.warning("그래프 문서의 저장 경로 없음: %s", missing_paths)

    return {
        "matched": [{"name": e["name"], "type": e["type"]} for e in matched],
        "expanded": [
            {"concept": c["name"], "members": [m["name"] for m in members if m["concept_id"] == c["id"]]}
            for c in concepts
        ],
        "relations": [
            f'{r["source_name"]} -[{r["type"]}]-> {r["target_name"]} ({_evidence(r)})'
            for r in relations
        ],
        "documents": [
            {
                "file_id": d["file_id"],
                "source": d["source"],
                "original_name": d["original_name"],
                "pages": sorted(d["pages"]),
                "entities": sorted(d["entities"]),
                "matched_terms": len(d["terms"]),
            }
            for d in ranked[:max_documents]
        ],
        "total_documents": len(ranked),
    }
