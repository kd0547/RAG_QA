import json
import time
from collections import Counter
from dataclasses import dataclass
from typing import Literal

from langchain.agents import create_agent
from dotenv import load_dotenv
from pathlib import Path

from agent.llm_provider import get_llm_model
from agent.prompt import render_prompt
from entity.type import Attachment, DocumentType
from parser.file_parser import parse_file
from repository import prompt_repo
from tools.tool import search_documents, rerank_documents, check_answerability, read_source_document
from langchain.agents.middleware import dynamic_prompt, ModelRequest
import logging
import yaml
load_dotenv()

logger = logging.getLogger(__name__)

TOOLS = [search_documents, rerank_documents, check_answerability, read_source_document]


# ---------- Agent ----------

ALIAS_PATH = Path(__file__).parents[1] / "aliases.yaml"

def load_aliases(path=ALIAS_PATH) -> dict[str, list[str]]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

ALIASES = load_aliases()

@dataclass
class AgentContext:
    system_prompt: str

@dynamic_prompt
def _system_prompt(request:ModelRequest):
    return request.runtime.context.system_prompt

def build_agent(mode: Literal["claude", "local"]):
    llm = get_llm_model(mode)
    return create_agent(
        model=llm,
        tools=TOOLS,
        middleware=[_system_prompt],
        context_schema=AgentContext,
    )


def run_agent(
        question: str,
        mode: Literal["claude", "local"] = "claude",

) -> dict:
    agent = get_agent(mode)

    result = _invoke_logged(
        agent, [{"role": "user", "content": question}], mode, label="질문",
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

    result = _invoke_logged(
        agent, [{"role": "user", "content": content}], mode,
        label=f"메일(첨부 {len(attachments or [])}건, 반려피드백 {'있음' if review_feedback else '없음'})",
    )

    return {
        "answer": result["messages"][-1].content,
        "sources": _collect_sources(result["messages"]),
    }


def _invoke_logged(agent, messages: list[dict], mode: str, label: str) -> dict:
    """에이전트를 실행하고 소요시간·도구 호출 수를 로그로 남긴다. 예외는 호출부가 처리하도록 다시 던진다."""
    started = time.perf_counter()
    try:
        result = agent.invoke(
            {"messages": messages},
            context=AgentContext(system_prompt=render_prompt(prompt_repo.get_system_prompt(), ALIASES)),
            config={"recursion_limit": 40})
    except Exception as exc:
        # 트레이스백은 호출부(소비자 루프, uvicorn)가 남기므로 여기서는 소요시간과 예외 종류만 남긴다
        logger.warning(
            "에이전트 실행 실패: %s, mode=%s, %.1f초, %s: %s",
            label, mode, time.perf_counter() - started, type(exc).__name__, exc,
        )
        raise

    tool_calls = Counter(
        msg.name for msg in result["messages"] if getattr(msg, "type", None) == "tool"
    )
    logger.info(
        "에이전트 실행 완료: %s, mode=%s, %.1f초, messages=%d, tools=%s",
        label, mode, time.perf_counter() - started, len(result["messages"]),
        dict(tool_calls) or "없음",
    )
    return result

def _attachment_to_block(attachment: Attachment) -> dict | None:
    """첨부 하나를 메시지 content 블록으로 바꾼다. 처리할 수 없으면 None."""
    # 메일 수신부는 type을 "image"/"pdf"/"docx" 등 문자열로 넣으므로 Enum으로 맞춘다.
    try:
        doc_type = DocumentType(attachment.type)
    except ValueError:
        logger.warning("지원하지 않는 첨부 형식: %s (%s)", attachment.filename, attachment.type)
        return None

    if doc_type == DocumentType.IMAGE:
        if not attachment.image:
            return None
        return {"type": "image_url", "image_url": {"url": attachment.image}}

    # 이미지 외 문서(pdf, docx, xlsx, pptx, hwp, hwpx)는 확장자별 파서로 텍스트를 뽑는다.
    name = attachment.filename or f"attachment.{doc_type.value}"
    try:
        pages = parse_file(attachment.path)
    except Exception:
        logger.exception("첨부 파일 파싱 실패: %s", name)
        # 모델이 첨부가 있었다는 사실은 알도록 남긴다.
        return {"type": "text", "text": f"[첨부 파일: {name}]\n(파일을 읽지 못했습니다)"}

    text = "\n\n".join(page.text for page in pages if page.text)
    return {"type": "text", "text": f"[첨부 파일: {name}]\n{text}"}


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


def get_agent(mode: Literal["claude", "local"] = "local"):
    """모드별로 에이전트를 최초 1회 빌드해 재사용한다."""
    if mode not in _agents:
        _agents[mode] = build_agent(mode)
    return _agents[mode]
