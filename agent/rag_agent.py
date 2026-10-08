import json
from typing import Literal

from langchain.agents import create_agent
from dotenv import load_dotenv

from agent.llm_provider import get_llm_model
from agent.prompt import SYSTEM_PROMPT
from entity.type import Attachment, DocumentType
from parser.pdf import pdf_parser
from tools.tool import search_documents, rerank_documents, check_answerability
import logging

load_dotenv()

logger = logging.getLogger(__name__)

TOOLS = [search_documents, rerank_documents, check_answerability]


# ---------- Agent ----------

def build_agent(mode: Literal["claude", "local"]):
    llm = get_llm_model(mode)
    return create_agent(
        model=llm,
        tools=TOOLS,
        system_prompt=SYSTEM_PROMPT,
    )


def run_agent(
        question: str,
        mode: Literal["claude", "local"] = "claude",

) -> dict:
    agent = get_agent(mode)

    result = agent.invoke(
        {"messages": [{"role": "user", "content": question}]},
        config={"recursion_limit": 40},
    )

    final_message = result["messages"][-1]

    sources = []
    for msg in result["messages"]:
        if getattr(msg, "name", None) in ("search_documents", "rerank_documents"):
            content = msg.content

            if isinstance(content, str):
                try:
                    content = json.loads(content)
                    sources.extend(content)
                except json.JSONDecodeError:
                    continue
            if isinstance(content, list):
                sources.extend(content)

    return {
        "answer": final_message.content,
        "sources": sources,
    }


def run_agent_temp_attachments(
        question: str,
        mode: Literal["claude", "local"] = "claude",
        attachments: list[Attachment] | None = None,
        review_feedback: str | None = None,
) -> dict:
    agent = get_agent(mode)

    content: list[dict] = [{"type": "text", "text": question}]
    for attachment in attachments or []:
        block = _attachment_to_block(attachment)
        if block is not None:
            content.append(block)

    # 담당자 반려 피드백은 질문과 섞이지 않도록 별도 블록으로 붙인다.
    if review_feedback:
        content.append({"type": "text", "text": review_feedback})

    result = agent.invoke(
        {"messages": [{"role": "user", "content": content}]},
        config={"recursion_limit": 40},
    )

    return {
        "answer": result["messages"][-1].content,
        "sources": _collect_sources(result["messages"]),
    }

def _attachment_to_block(attachment: Attachment) -> dict | None:
    """첨부 하나를 메시지 content 블록으로 바꾼다. 처리할 수 없으면 None."""
    # 메일 수신부는 type을 "image"/"pdf" 문자열로 넣으므로 Enum으로 맞춘다.
    try:
        doc_type = DocumentType(attachment.type)
    except ValueError:
        logger.warning("지원하지 않는 첨부 형식: %s (%s)", attachment.filename, attachment.type)
        return None

    if doc_type == DocumentType.IMAGE:
        if not attachment.image:
            return None
        return {"type": "image_url", "image_url": {"url": attachment.image}}

    if doc_type == DocumentType.PDF:
        name = attachment.filename or "attachment.pdf"
        try:
            text = pdf_parser.parser_pdf_md(attachment.path)
        except Exception:
            logger.exception("첨부 PDF 파싱 실패: %s", name)
            # 모델이 첨부가 있었다는 사실은 알도록 남긴다.
            return {"type": "text", "text": f"[첨부 파일: {name}]\n(파일을 읽지 못했습니다)"}


        return {"type": "text", "text": f"[첨부 파일: {name}]\n{text}"}

    return None


def _collect_sources(messages: list) -> list:
    """검색/리랭크 도구 결과 메시지에서 출처 목록을 모은다."""
    sources = []
    for msg in messages:
        if getattr(msg, "name", None) not in ("search_documents", "rerank_documents"):
            continue
        content = msg.content
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except json.JSONDecodeError:
                continue
        if isinstance(content, list):
            sources.extend(content)
    return sources

_agents: dict[str, object] = {}


def get_agent(mode: Literal["claude", "local"] = "claude"):
    """모드별로 에이전트를 최초 1회 빌드해 재사용한다."""
    if mode not in _agents:
        _agents[mode] = build_agent(mode)
    return _agents[mode]
