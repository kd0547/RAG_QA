import logging
import re
from pathlib import PureWindowsPath

from langchain_core.tools import tool

import repository
from agent.evidence_context import current_owner, current_run

from agent.llm_provider import get_llm_model
from agent.type import AnswerabilityCheck
from retrieval.embedder import get_embedding_model
from repository.embedding_repository import search
from agent import reranker
from parser.file_parser import parse_file

logger = logging.getLogger(__name__)

# search_documents가 모델에 보여 주는 청크 앞부분 길이 (전문은 근거 저장소에)
SNIPPET_CHARS = 300
# ---------- Tools ----------

@tool
def search_documents(
    query: str,
    top_k: int = 5,
    page: int = -1,
    file_id: str | None = None,
    score_threshold: float = 0.2,
    group_id: str | None = None,
) -> list[dict] | dict:
    """
문서 근거가 필요한 질문에 대해 벡터DB에서 관련 청크를 찾습니다.

Args:
    query:
        검색할 질문이나 핵심 키워드.

    group_id:
        문서 그룹으로 검색 범위를 제한할 때 사용하는 그룹 ID입니다. None이면 모든 그룹을 검색합니다.
        현재 사용 가능한 ID와 각 그룹의 설명은 시스템 프롬프트의 문서 그룹 검색 힌트를 참고하세요.
        질문이 특정 그룹을 명확히 가리킬 때만 지정하고, 결과가 0건이면 group_id=None으로 다시 검색합니다.

    top_k:
        가져올 청크의 최대 개수.
        기본값은 5입니다.

    page:
        특정 페이지의 내용을 집중해서 확인할 때 사용하는 페이지 번호입니다.
        -1이면 전체 페이지를 검색합니다.

        다음과 같은 경우 page를 사용할 수 있습니다.
        - 검색된 청크가 문장 중간에서 잘려 앞뒤 맥락이 필요한 경우
        - 같은 문서의 특정 페이지 전체 내용을 다시 확인해야 하는 경우
        - 표, 회의록, 사양표처럼 한 페이지 안의 여러 항목을 함께 봐야 하는 경우
        - 이전 검색 결과의 page 값이 확인되었고, 해당 페이지를 더 자세히 조사할 때

        page를 처음부터 임의로 지정하지 마세요.
        특정 페이지라는 근거가 없는 경우에는 -1로 전체 범위를 검색합니다.

    file_id:
        특정 파일 내부로 검색 범위를 제한할 때 사용하는 파일 ID입니다.
        None이면 전체 파일을 검색합니다.

        다음과 같은 경우 file_id를 사용할 수 있습니다.
        - 이전 검색 결과에서 관련 문서가 명확하게 확인된 경우
        - 같은 제품명이나 키워드가 여러 문서에 존재하여 다른 문서가 섞이는 경우
        - 검색된 청크의 앞뒤 내용 또는 같은 문서의 추가 근거를 찾아야 하는 경우
        - 한 문서 전체를 대상으로 추가 검색해야 하는 경우
        - 사용자가 특정 파일을 명시적으로 지정한 경우

        file_id를 처음부터 추측해서 지정하지 마세요.
        관련 파일이 확인되지 않은 상태에서는 None으로 전체 문서를 검색합니다.

    score_threshold:
        최소 유사도 점수.
        기본값은 0.2입니다.

        검색 결과가 0건이거나 충분하지 않은 경우,
        0.15 -> 0.10 -> 0.05 순으로 낮춰 재검색할 수 있습니다.

        너무 낮은 threshold의 결과는 관련성이 떨어질 수 있으므로
        이후 근거로 쓰려면 해당 페이지를 read_pages로 읽어 확인해야 합니다.

    Search strategy:
        1. 처음에는 file_id=None, page=-1로 전체 문서를 대상으로 검색합니다.
        2. 관련 문서가 확인되면 file_id를 사용하여 해당 문서 안에서 추가 검색합니다.
        3. 검색 결과가 문장 중간에서 잘렸거나 앞뒤 맥락이 필요하면,
            검색 결과의 page 값을 사용해 해당 페이지를 다시 검색합니다.
        4. 표나 회의록처럼 한 페이지의 전체 흐름이 중요한 경우에도 page를 활용합니다.
        5. 특정 파일의 여러 페이지를 확인해야 하는 경우에는 file_id만 지정하고
            page=-1 상태로 해당 파일 전체를 검색합니다.
        6. page와 file_id는 검색 범위를 지나치게 좁힐 수 있으므로,
            관련 파일이나 페이지가 확인된 이후에만 사용합니다.
        7. 검색 결과가 부족하면 먼저 score_threshold를 완화하고,
            그래도 부족한 경우 query를 바꿔 다시 검색합니다.
        8. 후보가 많으면 rerank_documents에 evidence_id 목록을 넘겨 줄입니다.

Returns:
    관련 청크의 목록.

    각 항목은 다음 값을 포함합니다.
    - evidence_id: 이 청크의 근거 ID (rerank_documents에 넘긴다)
    - file_id: 파일 ID
    - source: 문서 파일명
    - page: 페이지 번호 (페이지 전체는 read_pages에 file_id와 page를 넘겨 읽는다)
    - chunk_index: 청크 번호
    - snippet: 청크 앞부분 300자 (전문이 아니다)
    - score: 유사도 점수
"""

    error = _context_error()
    if error:
        return error
    rag_retriever = get_embedding_model()

    # 질문 임베딩
    embedding = rag_retriever.embed_query(query)

    docs = search(
        query_embedding=embedding,
        top_k=top_k,
        score_threshold=score_threshold,
        page=page,
        file_id=file_id,
        group_id=group_id,
    )

    logger.info(
        "[search_documents] query=%r group_id=%r file_id=%r page=%d top_k=%d score_threshold=%s -> %d건",
        query, group_id, file_id, page, top_k, score_threshold, len(docs),
    )

    owner = current_owner()
    results = []
    for doc in docs:
        if not doc:
            continue
        name = PureWindowsPath(doc.get("source") or "").name
        # 청크 전문은 근거 저장소에만 두고 모델에는 스니펫과 ID만 준다 (리랭크·검증은 ID로 서버에서 본문을 읽는다)
        evidence_id = repository.evidence_repo.register(
            owner.type, owner.id, "chunk", doc["text"] or "",
            file_id=doc.get("file_id"), page=doc.get("page"), source_name=name,
        )
        results.append({
            "evidence_id": evidence_id,
            "file_id": doc.get("file_id"),
            "group_id": doc.get("group_id"),
            "source": name,
            "page": doc.get("page"),
            "chunk_index": doc.get("chunk_index"),
            "snippet": (doc["text"] or "")[:SNIPPET_CHARS],
            "score": doc.get("score"),
        })
    return results

def _owned_evidence(evidence_ids: list[str], tool_name: str) -> list[dict]:
    """현재 소유자의 근거만 요청 순서대로. 다른 소유자·없는 ID는 빼고 경고를 남긴다."""
    owner = current_owner()
    ids = [i for i in evidence_ids or [] if isinstance(i, str)]
    found = repository.evidence_repo.get_many(ids, owner.type, owner.id)
    ignored = sorted(set(ids) - {e["evidence_id"] for e in found})
    if ignored:
        logger.warning("[%s] 현재 소유자(%s:%s)의 근거가 아니어서 무시: %s", tool_name, owner.type, owner.id, ignored)
    return found


@tool
def rerank_documents(query: str, evidence_ids: list[str], top_n: int = 3) -> list[str] | dict:
    """검색된 청크가 많을 때 질문과의 관련성으로 다시 정렬해 후보를 줄입니다.

    search_documents 결과가 많거나 여러 검색 결과를 합쳤을 때 사용합니다.
    본문은 넘기지 않습니다. 서버가 evidence_id로 본문을 찾아 비교합니다.

    Args:
        query: 후보와 비교할 원래 사용자 질문.
        evidence_ids: search_documents 결과의 evidence_id 목록.
        top_n: 남길 최대 개수. 기본값은 3입니다.

    Returns:
        관련성이 높은 순서의 evidence_id 목록 (최대 top_n개).
        재정렬 모델을 쓸 수 없으면 넘긴 순서 그대로 돌려줍니다.
    """
    error = _context_error()
    if error:
        return error
    candidates = _owned_evidence(evidence_ids, "rerank_documents")
    top_n = max(1, int(top_n or 1))
    if reranker.model is None:
        logger.warning("[rerank_documents] 리랭커가 없어 입력 순서를 유지: %d건", len(candidates))
        ranked = candidates[:top_n]
    else:
        ranked = reranker.rerank(query, candidates, top_n)
    run_id = current_run()
    for evidence in ranked:
        repository.evidence_repo.record_use(run_id, evidence["evidence_id"], "rerank")
    logger.info("[rerank_documents] %d건 -> %d건", len(candidates), len(ranked))
    return [e["evidence_id"] for e in ranked]


system_prompt = """당신은 사용자의 질문과 <content></content>의 내용을 비교 후 적합성을 평가하는 AI입니다.

    아래 기준으로 판단하세요:
    - <content>에 사용자 질문에 대한 답을 구성할 수 있는 정보가 포함되어 있으면 answerable
    - 질문과 무관하거나, 일부만 겹치고 핵심 답변 정보가 없으면 not answerable
    - 여러 content 중 하나라도 충분한 정보를 제공하면 answerable로 판단

    반드시 지정된 형식(is_answerable, reason)으로만 응답하세요."""

@tool
def check_answerability(question: str, evidence_ids: list[str]) -> dict:
    """읽은 근거만으로 사용자 질문에 답할 수 있는지 확인합니다.

    최종 답변 전에 호출합니다. 답변에 쓸 근거의 evidence_id를 넘깁니다 (본문은 서버가 찾습니다).
    이 도구는 문서를 새로 검색하지 않습니다.

    Args:
        question: 답하려는 원래 사용자 질문.
        evidence_ids: read_pages·search_documents 결과의 evidence_id 목록.

    Returns:
        is_answerable(bool)과 reason(str)을 담은 딕셔너리.
        is_answerable이 true일 때만 전달한 문서 내용을 근거로 답합니다.
        false이면 표현을 바꿔 재검색하고 다시 확인합니다. 재검색 후에도
        근거가 없으면 문서에서 답을 찾지 못했다고 알립니다.
    """
    error = _context_error()
    if error:
        return error
    documents = _owned_evidence(evidence_ids, "check_answerability")
    if not documents:
        return {"is_answerable": False, "reason": "확인할 근거가 없습니다. 문서를 먼저 읽으세요."}
    llm = get_llm_model("local")  # 판단은 안정적인 모델로 고정
    structured_llm = llm.with_structured_output(AnswerabilityCheck)

    content = "\n\n".join(
        f'<content index="{i}">\n{doc.get("text")}\n</content>'
        for i, doc in enumerate(documents, start=1)
    )



    user_prompt = f"""질문: {question}

    {content}"""

    result = structured_llm.invoke(
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
    )

    logger.info("[check_answerability] is_answerable=%s, reason=%s", result.is_answerable, result.reason)
    return {
        "is_answerable": result.is_answerable,
        "reason": result.reason
    }

@tool
def graph_search(query: str, group_id: str | None = None) -> dict:
    """문서 그래프에서 질문에 나온 제품·부품·인증·규격·기관을 찾고, 연결된 개체와 그 개체가 나온 문서를 돌려줍니다.

    다음 질문에 먼저 사용합니다.
    - 제품 모델명(예: N5800), 부품, 인증번호, 규격이 나오는 질문
    - "KC인증 자료"처럼 여러 인증 종류를 묶는 상위 개념을 묻는 질문 (속한 인증 종류로 펼쳐서 찾습니다)
    - 한 제품의 인증·부품·시험 문서를 모아야 하는 질문

    결과 documents의 file_id와 pages를 read_pages에 넘겨 원본 페이지를 읽은 뒤 답합니다.
    documents가 비었거나 질문과 맞지 않으면 search_documents로 검색합니다.

    Args:
        query: 사용자 질문 또는 핵심 키워드. 모델명·인증 이름을 빼지 말고 넣습니다.
        group_id: 문서 그룹으로 범위를 좁힐 때만 지정합니다. None이면 전체 문서를 봅니다.

    Returns:
        - matched: 질문에서 찾은 개체
        - expanded: 펼친 상위 개념과 그에 속한 인증 종류. 답변에는 각 인증 종류의 문서를 모두 포함합니다.
        - relations: "출발 -[관계]-> 도착 (파일 p페이지)" 형식의 관계
        - documents: 관련 문서. matched_terms가 클수록 질문의 대상을 더 많이 담은 문서입니다.
          각 항목의 source, original_name, pages(개체가 나온 페이지), entities
    """
    from graph_rag.service import search_graph  # DB 저장소는 사용 시점에 연다

    result = search_graph(query, group_id=group_id)
    logger.info(
        "[graph_search] query=%r group_id=%r -> matched=%d, documents=%d",
        query, group_id, len(result["matched"]), len(result["documents"]),
    )
    return result


# ---------- 문서 페이지 읽기 (근거 등록) ----------

# read_pages·read_attachment 한 번에 돌려줄 최대 글자 수
MAX_READ_CHARS = 20000
MAX_LIST_LIMIT = 200


def _context_error() -> dict | None:
    """근거를 등록할 실행 컨텍스트가 없으면 오류 dict. 에이전트 밖에서 도구를 직접 부른 경우다."""
    if current_owner() is None or current_run() is None:
        return {"error": "실행 컨텍스트가 없습니다 (에이전트 실행 중에만 쓸 수 있는 도구입니다)."}
    return None


def _register_read(origin_type: str, text: str, **fields) -> str:
    """근거를 현재 소유자로 등록하고 이번 실행에서 읽었다고 기록한다."""
    owner = current_owner()
    evidence_id = repository.evidence_repo.register(owner.type, owner.id, origin_type, text, **fields)
    repository.evidence_repo.record_use(current_run(), evidence_id, "read")
    return evidence_id


def _page_numbers(pages) -> list[int]:
    """요청 페이지 번호를 중복 없이 순서대로 (1 이상 정수만)."""
    if isinstance(pages, int):
        pages = [pages]
    numbers = []
    for page in pages or []:
        try:
            number = int(page)
        except (TypeError, ValueError):
            continue
        if number >= 1:
            numbers.append(number)
    return list(dict.fromkeys(numbers))


def read_page_texts(page_texts, max_chars: int, register) -> dict:
    """[(page, text, register_kwargs)]를 max_chars 안에서 잘라 근거로 등록한다. read_pages·read_attachment 공통.

    한 페이지가 남은 분량보다 길면 그 페이지는 앞부분만 보여 주고 truncated=True. 등록하는 근거는 페이지 전체다.
    """
    budget = min(max(1, int(max_chars or 1)), MAX_READ_CHARS)
    items: list[dict] = []
    truncated = False
    next_pages: list[int] = []
    for index, (page, text, fields) in enumerate(page_texts):
        if budget <= 0:
            truncated = True
            next_pages = [p for p, _, _ in page_texts[index:]]
            break
        evidence_id = register(text, page, fields)
        shown = text[:budget]
        item = {"evidence_id": evidence_id, "page": page, "text": shown}
        if len(shown) < len(text):
            item["truncated"] = True
            item["page_chars"] = len(text)
            truncated = True
        items.append(item)
        budget -= len(shown)
    result: dict = {"pages": items, "truncated": truncated}
    if next_pages:
        result["next_pages"] = next_pages
    if truncated:
        result["message"] = (
            f"max_chars({min(max(1, int(max_chars or 1)), MAX_READ_CHARS)}자)를 넘어 일부만 돌려줬습니다. "
            + (f"남은 페이지 {next_pages}는 다시 호출해 읽으세요. " if next_pages else "")
            + "한 페이지가 길어 잘렸다면 max_chars를 늘리거나(최대 20000) grep_documents로 필요한 부분을 찾으세요."
        )
    return result


@tool
def read_pages(file_id: str, pages: list[int], max_chars: int = 6000) -> dict:
    """문서의 페이지 텍스트를 읽습니다. 답변 근거를 얻는 주 도구입니다.

    검수로 고친 최신 텍스트(file_page)를 읽으며 원본 파일을 다시 파싱하지 않습니다.
    읽은 페이지마다 evidence_id가 붙습니다. 답변에 인용하는 근거는 반드시 이 도구(또는 read_attachment)로 읽은 것이어야 합니다.

    Args:
        file_id: 문서 ID. list_documents, grep_documents, search_documents, graph_search 결과의 file_id.
        pages: 읽을 페이지 번호 목록 (1부터). 예: [3] 또는 [3, 4]. xlsx는 시트 번호입니다.
        max_chars: 이번 호출에서 돌려받을 최대 글자 수. 기본 6000, 최대 20000.

    Returns:
        - pages: [{evidence_id, page, text}] 요청 순서대로
        - missing_pages: 문서에 없는 페이지 번호
        - truncated: 분량 초과로 일부만 돌려줬으면 true. next_pages에 남은 페이지가 있습니다
        - error: 문서가 없거나 페이지 텍스트가 저장돼 있지 않은 경우
    """
    error = _context_error()
    if error:
        return error
    file = repository.file_repo.get_file_by_id(file_id)
    if file is None:
        return {"error": f"없는 file_id입니다: {file_id}. list_documents로 문서를 찾으세요."}
    if not repository.page_repo.has_pages(file_id):
        # 질의 시점에 원본을 다시 파싱하지 않는다 (페이지 텍스트는 업로드 때 저장된다)
        return {"error": f"페이지 텍스트 없음: {file.original_name}은 페이지별 텍스트가 저장돼 있지 않습니다. search_documents로 찾으세요."}

    page_texts, missing = [], []
    for number in _page_numbers(pages):
        rows = repository.page_repo.pages_with_number(file_id, number)
        if not rows:
            missing.append(number)
            continue
        text = "\n\n".join(row["text"] for row in rows)
        fields = {"page_id": rows[0]["page_id"], "revision": max(row["updated_at"] for row in rows)}
        page_texts.append((number, text, fields))

    def register(text, page, fields):
        return _register_read(
            "file_page", text, file_id=file_id, page=page, source_name=file.original_name, **fields,
        )

    result = {"file_id": file_id, "original_name": file.original_name, **read_page_texts(page_texts, max_chars, register)}
    if missing:
        result["missing_pages"] = missing
    logger.info(
        "[read_pages] file=%s pages=%s -> %d쪽, missing=%s, truncated=%s",
        file.original_name, _page_numbers(pages), len(result["pages"]), missing, result["truncated"],
    )
    return result


@tool
def list_documents(group_id: str | None = None, keyword: str | None = None, limit: int = 50) -> list[dict]:
    """등록된 문서 목록을 봅니다. 특정 문서를 읽어야 하는데 file_id를 모를 때 씁니다.

    Args:
        group_id: 문서 그룹으로 좁힐 때만. None이면 전체.
        keyword: 파일명·설명에 들어 있는 말로 좁힐 때 (대소문자 무시).
        limit: 최대 개수 (기본 50).

    Returns:
        [{file_id, original_name, group_id, description, has_pages, page_count}]
        has_pages가 false인 문서는 read_pages로 읽을 수 없습니다.
    """
    counts = repository.page_repo.page_counts()
    needle = (keyword or "").strip().lower()
    result = []
    for file in repository.file_repo.file_list():
        if group_id and file.get("group_id") != group_id:
            continue
        if needle and needle not in f"{file.get('original_name') or ''} {file.get('description') or ''}".lower():
            continue
        page_count = counts.get(file["file_id"], 0)
        result.append({
            "file_id": file["file_id"],
            "original_name": file.get("original_name"),
            "group_id": file.get("group_id"),
            "description": file.get("description") or "",
            "has_pages": page_count > 0,
            "page_count": page_count,
        })
        if len(result) >= min(max(1, limit), MAX_LIST_LIMIT):
            break
    logger.info("[list_documents] group_id=%r keyword=%r -> %d건", group_id, keyword, len(result))
    return result


@tool
def grep_documents(pattern: str, file_id: str | None = None, limit: int = 20) -> list[dict] | dict:
    """문서 페이지 텍스트에서 글자 그대로(또는 정규식) 찾습니다. 모델명·수치·인증번호처럼 정확한 표기를 찾을 때 씁니다.

    Args:
        pattern: 찾을 말. Python 정규식, 대소문자 무시. 예: "N5800", "RAM ?32 ?GB", "R-R-TGE-[A-Z0-9]+"
        file_id: 한 문서 안에서만 찾을 때.
        limit: 최대 결과 수 (기본 20).

    Returns:
        [{file_id, original_name, page, snippet}] snippet은 일치 부분 앞뒤 80자입니다.
        근거로 인용하려면 그 페이지를 read_pages로 읽으세요.
    """
    try:
        result = repository.page_repo.search_text(pattern, file_id=file_id, limit=min(max(1, limit), MAX_LIST_LIMIT))
    except re.error as exc:
        return {"error": f"정규식 오류: {exc}. ( ) [ ] . + * ? 같은 기호는 앞에 \\를 붙이세요."}
    logger.info("[grep_documents] pattern=%r file_id=%r -> %d건", pattern, file_id, len(result))
    return result
