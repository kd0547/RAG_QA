from typing import Literal

from langchain_ollama import ChatOllama
from langchain_anthropic import ChatAnthropic
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent
from dotenv import load_dotenv

from rag.embedder import get_embedding_model
from repository.embedding_repository import search
from agent.reranker import rerank

load_dotenv()

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


# ---------- Tools ----------

@tool
def search_documents(query: str, top_k: int = 5) -> list[dict]:
    """벡터DB에서 질문과 관련된 문서 청크를 검색합니다.

    질문을 표현만 바꿔서 여러 번 호출하면(다른 어휘/문장 구조) 검색 커버리지가 넓어집니다.
    검색 결과가 질문에 답하기 부족하다고 판단되면, 다른 표현의 query로 다시 호출하세요.
    """
    rag_retriever = get_embedding_model()
    embedding = rag_retriever.embed_query(query)
    docs = search(embedding, top_k)
    print(f"[search_documents] query={query!r} top_k={top_k} -> {len(docs)}건")
    return docs


@tool
def rerank_documents(query: str, documents: list[dict], top_n: int = 3) -> list[dict]:
    """검색된 문서 후보들을 질문과의 관련성 기준으로 재정렬해 상위 top_n개만 반환합니다.

    후보 문서가 많거나(예: 10개 이상) 여러 번 검색해서 중복/잡음이 섞였을 때 사용하세요.
    """
    results = rerank(query, documents, top_n)
    print(f"[rerank_documents] {len(documents)}건 -> {len(results)}건")
    return results


TOOLS = [search_documents, rerank_documents]


# ---------- Agent ----------

SYSTEM_PROMPT = """당신은 사용자의 질문에 문서 기반으로 답변하는 RAG 에이전트입니다.

다음 절차를 스스로 판단하여 수행하세요:
1. search_documents로 질문과 관련된 문서를 검색하세요. 한 번의 검색으로 부족하다고 판단되면, 표현을 바꿔 여러 번 검색하세요.
2. 검색 결과가 많거나(10개 이상) 여러 번 검색해 후보가 섞였다면, rerank_documents로 관련성 높은 것만 추려내세요.
3. 검색 결과가 질문에 답하기에 불충분하다고 판단되면, 다른 검색어로 다시 search_documents를 호출하세요. (최대 3회 재검색)
4. 충분한 근거가 모이면, 그 근거만 사용해 답변하세요.

답변 시 규칙:
- 근거로 사용한 문장 끝에 [출처파일명 pN] 형식으로 표시하세요.
- 문서에 없는 내용은 답변에 포함하지 마세요.
- 여러 번 검색해도 답을 찾을 수 없으면, 정보가 부족하다고 솔직히 답하세요.
"""


def build_agent(mode: Literal["claude", "local"]):
    llm = get_llm_model(mode)
    return create_react_agent(
        model=llm,
        tools=TOOLS,
        prompt=SYSTEM_PROMPT,
    )


def run_agent(question: str, mode: Literal["claude", "local"] = "claude") -> dict:
    print(f"[run_agent] 시작 - question={question!r}, mode={mode}")

    agent = build_agent(mode)
    result = agent.invoke(
        {"messages": [{"role": "user", "content": question}]},
        config={"recursion_limit": 15},
    )

    final_message = result["messages"][-1]

    # 이번 실행에서 실제로 사용된(도구 결과로 반환된) 문서들을 messages에서 추려서 sources로 반환
    sources = []
    for msg in result["messages"]:
        if getattr(msg, "name", None) in ("search_documents", "rerank_documents"):
            content = msg.content
            if isinstance(content, list):
                sources.extend(content)

    print(f"[run_agent] 종료 - answer 길이={len(final_message.content)}, sources={len(sources)}")
    return {
        "answer": final_message.content,
        "sources": sources,
    }


_agents: dict[str, object] = {}


def get_agent(mode: Literal["claude", "local"] = "claude"):
    """모드별로 에이전트를 최초 1회 빌드해 재사용한다."""
    if mode not in _agents:
        _agents[mode] = build_agent(mode)
    return _agents[mode]