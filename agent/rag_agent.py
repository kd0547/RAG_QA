from typing import Literal

from langchain_core.tools import tool
from langchain.agents import create_agent
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from agent.llm_provider import get_llm_model
from rag.embedder import get_embedding_model
from repository.embedding_repository import search
from agent.reranker import rerank

load_dotenv()


# ---------- 판단용 구조화 출력 ----------

class AnswerabilityCheck(BaseModel):
    is_answerable: bool = Field(description="검색된 문서만으로 질문에 답할 수 있는지 여부")
    reason: str = Field(description="판단 근거를 한두 문장으로")


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
    return  [{
        "id": doc["id"],
        "source": doc["source"],
        "page": doc["page"],
        "text": doc["text"],
    } for doc in docs if doc]


@tool
def rerank_documents(query: str, documents: list[dict], top_n: int = 3) -> list[dict]:
    """검색된 문서 후보들을 질문과의 관련성 기준으로 재정렬해 상위 top_n개만 반환합니다.

    후보 문서가 많거나(예: 10개 이상) 여러 번 검색해서 중복/잡음이 섞였을 때 사용하세요.
    """
    results = rerank(query, documents, top_n)
    print(f"[rerank_documents] {len(documents)}건 -> {len(results)}건")
    return results


@tool
def check_answerability(question: str, documents: list[dict]) -> dict:
    """현재까지 검색된 문서들로 질문에 실제로 답할 수 있는지 판단합니다.

    **최종 답변을 작성하기 전에 반드시 이 도구를 먼저 호출해야 합니다.**
    is_answerable=false가 나오면 답변을 작성하지 말고, 다른 검색어로 재검색하세요.
    is_answerable=true가 나온 경우에만 문서 내용을 근거로 답변을 작성하세요.
    """
    llm = get_llm_model("local")  # 판단은 안정적인 모델로 고정
    structured_llm = llm.with_structured_output(AnswerabilityCheck)

    content = "\n\n".join(
        f'<content index="{i}">\n{doc.get("text")}\n</content>'
        for i, doc in enumerate(documents, start=1)
    )

    system_prompt = """당신은 사용자의 질문과 <content></content>의 내용을 비교 후 적합성을 평가하는 AI입니다.

    아래 기준으로 판단하세요:
    - <content>에 사용자 질문에 대한 답을 구성할 수 있는 정보가 포함되어 있으면 answerable
    - 질문과 무관하거나, 일부만 겹치고 핵심 답변 정보가 없으면 not answerable
    - 여러 content 중 하나라도 충분한 정보를 제공하면 answerable로 판단

    반드시 지정된 형식(is_answerable, reason)으로만 응답하세요."""

    user_prompt = f"""질문: {question}

    {content}"""

    result = structured_llm.invoke(
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
    )

    print(f"[check_answerability] is_answerable={result.is_answerable}, reason={result.reason}")
    return {"is_answerable": result.is_answerable, "reason": result.reason}


TOOLS = [search_documents, rerank_documents, check_answerability]


# ---------- Agent ----------

SYSTEM_PROMPT = """당신은 RAG 에이전트입니다. 사용자 질문에 문서 근거로 직접 답변하는 것이 유일한 임무입니다.

**실행 절차 (사용자에게 설명하지 말고 그대로 실행만 하세요)**
1. search_documents를 호출해 질문과 관련된 문서를 검색한다. query는 사용자 질문의 핵심 키워드를 그대로 사용한다.
2. 후보 문서가 많거나(10개 이상) 여러 번 검색해 후보가 섞였으면 rerank_documents로 관련성 높은 것만 추린다.
3. **답변을 작성하기 전에 반드시 check_answerability를 호출해 현재 문서로 답할 수 있는지 확인한다.**
   - is_answerable=false면 절대 답변하지 말고, 다른 표현으로 재검색한다 (최대 2회).
   - 2회 재검색 후에도 is_answerable=false면, "문서에서 관련 정보를 찾지 못했습니다"라고 짧게 답한다.
   - is_answerable=true인 경우에만 문서 내용을 근거로 답변을 작성한다.
4. 검색된 문서 내용만 근거로 삼아 질문에 직접 답변한다.

**절대 규칙**
- 너 자신의 역할, 능력, 절차를 사용자에게 설명하지 마라.
- 인사말이나 자기소개로 답변을 시작하지 마라. 바로 답변 내용으로 시작하라.
- check_answerability를 거치지 않고 바로 답변을 작성하지 마라.
- 검색된 문서에 없는 내용은 답변에 포함하지 마라.

**출력 형식**
- 답변만 작성한다. 절차 설명, 인사말, 메타 코멘트를 포함하지 않는다.
"""


def build_agent(mode: Literal["claude", "local"]):
    llm = get_llm_model(mode)
    return create_agent(
        model=llm,
        tools=TOOLS,
        system_prompt=SYSTEM_PROMPT,
    )


def run_agent(question: str, mode: Literal["claude", "local"] = "claude") -> dict:
    print(f"[run_agent] 시작 - question={question!r}, mode={mode}")

    agent = get_agent(mode)
    result = agent.invoke(
        {"messages": [{"role": "user", "content": question}]},
        config={"recursion_limit": 15},
    )

    print("=" * 80)
    for i, msg in enumerate(result["messages"]):
        msg_type = type(msg).__name__
        content_preview = str(msg.content)[:300]
        tool_calls = getattr(msg, "tool_calls", None)
        name = getattr(msg, "name", None)

        print(f"[{i}] {msg_type} name={name}")
        if tool_calls:
            print(f"    tool_calls={tool_calls}")
        print(f"    content={content_preview}")
        print("-" * 80)
    print("=" * 80)

    final_message = result["messages"][-1]

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