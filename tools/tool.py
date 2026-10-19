import logging
from functools import lru_cache
from pathlib import Path

from langchain_core.tools import tool

from agent.llm_provider import get_llm_model
from agent.type import AnswerabilityCheck
from retrieval.embedder import get_embedding_model
from repository.embedding_repository import search
from agent.reranker import rerank
from parser.file_parser import parse_file

logger = logging.getLogger(__name__)
# ---------- Tools ----------

@tool
def search_documents(
    query: str,
    top_k: int = 5,
    page: int = -1,
    file_id: str | None = None,
    score_threshold: float = 0.2,
) -> list[dict]:
    """
문서 근거가 필요한 질문에 대해 벡터DB에서 관련 청크를 찾습니다.

Args:
    query:
        검색할 질문이나 핵심 키워드.

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
        이후 rerank_documents 및 check_answerability를 통해 검증해야 합니다.

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
        8. 최종 검색 결과는 rerank_documents 및 check_answerability로 검증합니다.

Returns:
    관련 청크의 목록.

    각 항목은 다음 값을 포함합니다.
    - id: 청크 ID
    - file_id: 파일 ID
    - source: 원본 문서 경로 (read_source_document에 그대로 전달)
    - page: 페이지 번호
    - chunk_index: 청크 번호
    - text: 본문
    - score: 유사도 점수
"""

    rag_retriever = get_embedding_model()

    # 질문 임베딩
    embedding = rag_retriever.embed_query(query)

    docs = search(
        query_embedding=embedding,
        top_k=top_k,
        score_threshold=score_threshold,
        page=page,
        file_id=file_id,
    )

    logger.info(
        "[search_documents] query=%r file_id=%r page=%d top_k=%d score_threshold=%s -> %d건",
        query, file_id, page, top_k, score_threshold, len(docs),
    )

    return [
        {
            "id": doc["id"],
            "file_id": doc["file_id"],
            "source": doc["source"],
            "page": doc["page"],
            "chunk_index": doc["chunk_index"],
            "text": doc["text"],
            "score": doc["score"],
        }
        for doc in docs
        if doc
    ]

@tool
def rerank_documents(query: str, documents: list[dict], top_n: int = 3) -> list[dict]:
    """검색된 청크가 많을 때 질문과의 관련성으로 다시 정렬해 후보를 줄입니다.

    search_documents의 결과가 많거나 여러 검색 결과를 합쳤을 때 사용합니다.
    검색을 대신하지 않으며, 후보가 적다면 생략할 수 있습니다.

    Args:
        query: 후보 청크와 비교할 원래 사용자 질문.
        documents: search_documents가 반환한 청크 목록. 각 항목에 최소한
            text가 있어야 하며 id, source, page도 유지해 전달합니다.
        top_n: 관련성이 높은 순서로 남길 최대 청크 수. 기본값은 3입니다.

    Returns:
        관련성 순으로 정렬된 최대 top_n개의 원본 청크. 반환값에 점수는
        추가되지 않습니다. 재정렬 모델을 사용할 수 없으면 빈 목록입니다.
    """
    results = rerank(query, documents, top_n)
    logger.info("[rerank_documents] %d건 -> %d건", len(documents), len(results))
    return results



system_prompt = """당신은 사용자의 질문과 <content></content>의 내용을 비교 후 적합성을 평가하는 AI입니다.

    아래 기준으로 판단하세요:
    - <content>에 사용자 질문에 대한 답을 구성할 수 있는 정보가 포함되어 있으면 answerable
    - 질문과 무관하거나, 일부만 겹치고 핵심 답변 정보가 없으면 not answerable
    - 여러 content 중 하나라도 충분한 정보를 제공하면 answerable로 판단

    반드시 지정된 형식(is_answerable, reason)으로만 응답하세요."""

@tool
def check_answerability(question: str, documents: list[dict]) -> dict:
    """검색된 청크만으로 사용자 질문에 답할 수 있는지 확인합니다.

    최종 답변 전에 호출합니다. 검색 또는 재정렬을 거쳐 실제 답변에 사용할
    청크를 전달해야 하며, 이 도구는 문서를 새로 검색하지 않습니다.

    Args:
        question: 답하려는 원래 사용자 질문.
        documents: 근거 후보 청크 목록. 각 항목의 text가 판단에 사용됩니다.

    Returns:
        is_answerable(bool)과 reason(str)을 담은 딕셔너리.
        is_answerable이 true일 때만 전달한 문서 내용을 근거로 답합니다.
        false이면 표현을 바꿔 재검색하고 다시 확인합니다. 재검색 후에도
        근거가 없으면 문서에서 답을 찾지 못했다고 알립니다.
    """
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

# 업로드된 원본 문서 폴더 (app/routers/files.py의 UPLOAD_DIR과 같은 위치)
DOCS_ROOT = (Path(__file__).resolve().parent.parent / "data" / "uploads").resolve()
MAX_READ_CHARS = 20000


@lru_cache(maxsize=16)
def _extract_text(path_str: str, mtime_ns: int) -> str:
    """파일을 파싱해 페이지 구분자를 붙인 전체 텍스트를 반환한다.

    파싱 비용이 크므로 (경로, 수정시각) 기준으로 캐시한다. 파일이 바뀌면 mtime이 달라져 다시 파싱된다.
    """
    pages = parse_file(path_str)
    return "\n\n".join(f"[page {page.page}]\n{page.text}" for page in pages if page.text)


@tool
def read_source_document(source: str, start: int = 0, max_chars: int = 8000) -> str:
    """검색 결과의 source에 해당하는 원본 문서 전체 텍스트를 순서대로 읽습니다.

    검색된 청크가 잘려 앞뒤 맥락이 부족하거나, 문서 전체 흐름(목차, 표, 여러 페이지에 걸친
    설명)을 봐야 할 때 사용합니다. 문서를 검색하지는 않으므로 먼저 search_documents로
    관련 문서를 찾은 뒤 호출합니다.

    Args:
        source: search_documents 결과의 source 값을 그대로 전달합니다.
        start: 읽기 시작할 글자 위치. 처음에는 0입니다.
        max_chars: 한 번에 읽을 최대 글자 수. 기본값은 8000, 최대 20000입니다.

    Returns:
        본문 일부와 마지막 줄의 위치 정보 [파일명: 시작~끝 / 전체 N자].
        본문에는 [page N] 표시가 있어 페이지를 알 수 있습니다.
        끝 < 전체이면 start=끝으로 다시 호출해 이어서 읽습니다.
    """
    path = Path(source)
    if not path.is_absolute():
        path = DOCS_ROOT / path  # 파일명만 넘어온 경우
    path = path.resolve()
    if not path.is_relative_to(DOCS_ROOT) or not path.is_file():
        logger.info("[read_source_document] 거부: source=%r", source)
        return "허용되지 않거나 존재하지 않는 경로입니다. search_documents 결과의 source 값을 그대로 전달하세요."

    try:
        text = _extract_text(str(path), path.stat().st_mtime_ns)
    except Exception:
        logger.exception("[read_source_document] 파싱 실패: %s", path)
        return f"{path.name} 문서를 읽지 못했습니다."

    start = max(0, start)
    max_chars = min(max(1, max_chars), MAX_READ_CHARS)
    if start >= len(text):
        return f"[{path.name}: 읽을 내용이 없습니다. 전체 {len(text)}자]"

    chunk = text[start:start + max_chars]
    end = start + len(chunk)
    logger.info("[read_source_document] %s %d~%d / %d자", path.name, start, end, len(text))
    return f"{chunk}\n\n[{path.name}: {start}~{end} / 전체 {len(text)}자]"
