from typing import TypedDict, Literal

from langchain_ollama import ChatOllama
from pydantic import BaseModel, Field
from requests_oauthlib.compliance_fixes.douban import douban_compliance_fix

from rag.embedder import get_embedding_model
from repository.embedding_repository import search
from langgraph.graph import StateGraph, START, END
from langchain_anthropic import ChatAnthropic
from dotenv import load_dotenv
from agent.reranker import rerank
load_dotenv()
class AgentState(TypedDict):
    content: str
    search_results: list
    mode: Literal["claude", "local"]
    is_relevant: bool
    final_answer: str
    retry_count: int
    query_variants: list
    rerank_top_n :int
    query_top_n: int

class SelectedContext(BaseModel):
    selected_ids: list[int] = Field(
        description="질문에 답하기 위해 실제로 필요한 content의 번호(index) 목록"
    )

class RelevanceCheck(BaseModel):
    is_relevant: bool = Field(description="검색된 내용이 질문에 답하기에 충분한지 여부")
    reason: str = Field(description="판단 근거 간단히")


class QueryVariants(BaseModel):
    variants: list[str] = Field(
        description="원본 질문과 의미는 같지만 표현이 다른 검색용 질문 3개",
        min_length=3,
        max_length=3,
    )


_local_llm: ChatOllama | None = None
_claude_llm: ChatAnthropic | None = None


def set_llm_model(model: ChatOllama):
    global _local_llm

    _local_llm = model

def get_llm_model(mode: str) -> ChatOllama | ChatAnthropic:
    global _claude_llm

    if mode == "local":
        if _local_llm is None:
            raise RuntimeError(
                "로컬 LLM이 아직 로드되지 않았습니다. "
                "서버 시작 시 set_llm_model()로 모델을 주입해주세요."
            )
        return _local_llm

    if _claude_llm is None:
        _claude_llm = ChatAnthropic(model="claude-sonnet-5")
    return _claude_llm

def select_context(state: AgentState) -> dict:
    print(f"[select_context] 시작 - search_results 개수={len(state.get('search_results', []))}")

    llm = get_llm_model(state["mode"])
    structured_llm = llm.with_structured_output(SelectedContext)

    content = "\n\n".join(
        f'<content index="{i}">\n{doc["text"]}\n</content>'
        for i, doc in enumerate(state["search_results"], start=1)
    )

    system_prompt = """당신은 사용자의 질문에 답하기 위해 실제로 필요한 content만 선별하는 AI입니다.

    아래 <content index="N">들 중, 질문에 대한 답변을 구성하는 데 실제로 사용될 근거만 골라 번호를 반환하세요.
    - 질문과 직접 관련 없는 content는 제외하세요.
    - 중복되거나 불필요한 content는 제외하세요.
    - 최소 1개 이상은 선택하세요.
    반드시 지정된 형식(selected_ids)으로만 응답하세요."""

    user_prompt = f"""질문: {state["content"]}

    {content}"""

    result = structured_llm.invoke(
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
    )

    selected = [
        doc for i, doc in enumerate(state["search_results"], start=1)
        if i in result.selected_ids
    ]

    # 혹시 LLM이 아무것도 안 골랐으면 원본 유지 (안전장치)
    if not selected:
        selected = state["search_results"]

    print(f"[select_context] 종료 - {len(state['search_results'])}건 중 {len(selected)}건 선택, ids={result.selected_ids}")
    return {"search_results": selected}

def expand_query(state: AgentState) -> dict:
    print(f"[expand_query] 시작 - content={state['content']!r}")

    llm = get_llm_model(state["mode"])
    structured_llm = llm.with_structured_output(QueryVariants)

    system_prompt = """당신은 RAG 검색 성능을 높이기 위해 사용자 질문을 다양하게 재구성하는 AI입니다.
    원본 질문과 의미는 동일하되 표현(어휘, 문장 구조)이 다른 검색용 질문 3개를 생성하세요.
    반드시 지정된 형식(variants)으로만 응답하세요."""

    user_prompt = f"질문: {state['content']}"

    result = structured_llm.invoke(
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
    )

    query_variants = [state["content"]] + result.variants
    print(f"[expand_query] 종료 - query_variants={query_variants}")
    return {"query_variants": query_variants}

def search_rag(state: AgentState) -> dict:
    print(f"[search_rag] 시작 - retry_count={state.get('retry_count', 0)}, "
          f"query_variants={state.get('query_variants')}")

    rag_retriever = get_embedding_model()

    all_docs = []
    seen_ids = set()

    for q in state["query_variants"]:
        query = rag_retriever.embed_query(q)  # 원본 content 대신 q 사용
        top_n = state["query_top_n"] if state.get("query_top_n") else 5
        docs = search(query, top_n)

        for doc in docs:
            if doc["id"] not in seen_ids:
                seen_ids.add(doc["id"])
                all_docs.append(doc)

        print(f"[search_rag]   variant={q!r} -> {len(docs)}건 검색")

    result = {"search_results": all_docs, "retry_count": state.get("retry_count", 0) + 1}

    print(f"[search_rag] 종료 - 중복 제거 후 {len(all_docs)}건, retry_count={result['retry_count']}")
    return result

def document_reranker(state:AgentState) -> dict:

    documents = state["search_results"]
    query = state["content"]
    top_n = state["rerank_top_n"] if state.get("rerank_top_n") else 3

    results = rerank(query,documents,top_n)
    return {"search_results":results}



# rag와
def check_relevance(search_results: list, user_query: str,mode:str):
    llm = get_llm_model(mode)

    structured_llm = llm.with_structured_output(RelevanceCheck)
    content = "\n\n".join(
        f"<content>\n{doc['text']}\n</content>" for doc in search_results
    )

    system_prompt = """당신은 사용자의 질문과 <content></content>의 내용을 비교 후 적합성을 평가하는 AI입니다.

    아래 기준으로 판단하세요:
    - <content>에 사용자 질문에 대한 답을 구성할 수 있는 정보가 포함되어 있으면 relevant
    - 질문과 무관하거나, 일부만 겹치고 핵심 답변 정보가 없으면 not relevant
    - 여러 content 중 하나라도 충분한 정보를 제공하면 relevant로 판단

    반드시 지정된 형식(is_relevant, reason)으로만 응답하세요."""

    user_prompt = f"""질문: {user_query}

    {content}"""

    result = structured_llm.invoke(
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
    )

    print(f"[check_relevance] is_relevant={result.is_relevant}, reason={result.reason}")
    return result.is_relevant


def self_check(state: AgentState) -> dict:
    print(f"[self_check] 시작 - search_results 개수={len(state.get('search_results', []))}")

    # 검색 결과가 질문에 답할 수 있는지 평가
    relevant = check_relevance(state["search_results"], state["content"],state["mode"])

    print(f"[self_check] 종료 - is_relevant={relevant}")
    return {"is_relevant": relevant}


def decide_next(state: AgentState) -> str:
    next_node = "final" if state["is_relevant"] else "search_rag"
    print(f"[decide_next] is_relevant={state['is_relevant']} -> next='{next_node}'")

    if state["is_relevant"]:
        return "final"
    else:
        return "search_rag"  # 재검색 루프


def final(state: AgentState):
    print(f"[final] 시작 - content={state['content']!r}, "
          f"search_results 개수={len(state.get('search_results', []))}")

    llm = get_llm_model(state["mode"])

    content = "\n\n".join(
        f"<content id={index}>\n {doc['text']}\n</content>" for index,doc in enumerate(state["search_results"],start=1)
    )
    #print(f"[final] content 내용{state["search_results"]}")

    system_prompt = """당신은 사용자의 질문과 <content></content>의 내용을 바탕으로 답변을 생성하는 AI입니다.

        답변 시 다음 규칙을 반드시 지키세요:
        - 답변의 각 문장이나 근거가 특정 <content index="N">에서 나왔다면, 해당 문장 끝에 [N] 형식으로 표시하세요.
        - 여러 content를 참조했다면 [1][3]처럼 각각 표시하세요.
        - <content>에 없는 내용은 답변에 포함하지 마세요.
        """

    user_prompt = f"""질문: {state["content"]}
        {content}"""

    result = llm.invoke(input=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ])

    print(f"[final] 종료 - answer 길이={len(result.content)}")
    return {"final_answer": result.content}

def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("expand_query", expand_query)

    graph.add_node("search_rag", search_rag)
    graph.add_node("document_reranker", document_reranker)
    graph.add_node("self_check", self_check)
    graph.add_node("select_context", select_context)
    graph.add_node("final", final)

    graph.add_edge(START, "expand_query")
    graph.add_edge("expand_query", "search_rag")

    graph.add_edge("search_rag", "document_reranker")
    graph.add_edge("document_reranker", "self_check")

    graph.add_conditional_edges(
        "self_check",
        decide_next,
        {"final": "select_context", "search_rag": "search_rag"}
    )

    graph.add_edge("select_context", "final")
    graph.add_edge("final", END)
    return graph.compile()


_graph = None


def get_graph():
    """컴파일된 그래프를 최초 1회 빌드해 재사용한다."""
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph