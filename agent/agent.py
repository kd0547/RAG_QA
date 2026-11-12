import json
import time
from collections import Counter
from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

from langchain.agents import create_agent
from dotenv import load_dotenv
from pathlib import Path

import config
import repository
from agent.evidence_context import Owner, current_owner, owner_scope, run_scope
from agent.llm_provider import get_llm_model
from agent.prompt import render_prompt
from entity.type import Attachment, DocumentType
from parser.file_parser import parse_file
from repository import graph_repo, group_repo, prompt_repo
from tools.tool import (
    check_answerability, graph_search, grep_documents, list_documents, read_pages, rerank_documents, search_documents,
)
from langchain.agents.middleware import dynamic_prompt, ModelRequest
import logging
import yaml
load_dotenv()

logger = logging.getLogger(__name__)

TOOLS = [graph_search, list_documents, grep_documents, read_pages, search_documents, rerank_documents, check_answerability]


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


def new_session_owner() -> Owner:
    """메일이 아닌 질문(/ask)은 호출마다 새 세션을 근거 소유자로 쓴다."""
    return Owner("session", uuid4().hex)


def run_agent(
        question: str,
        mode: Literal["claude", "local"] = "claude",
        *,
        owner: Owner | None = None,
) -> dict:
    agent = get_agent(mode)

    with owner_scope(owner or new_session_owner()):
        result = _invoke_logged(
            agent, [{"role": "user", "content": question}], mode, label="질문",
        )

    return {
        "answer": result["messages"][-1].content,
        "sources": _collect_sources(result["messages"]),
    }


def run_agent_temp_attachments(
        question: str,
        mode: Literal["claude", "local"] = "claude",
        attachments: list[Attachment] | None = None,
        review_feedback: str | None = None,
        *,
        owner: Owner | None = None,
) -> dict:
    """첨부가 있는 질문. 메일은 owner=Owner("task", task_id), /ask/attachments는 새 세션."""
    agent = get_agent(mode)

    with owner_scope(owner or new_session_owner()):
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


def _model_name(mode: str) -> str:
    return config.LLM_MODEL if mode == "local" else config.CLAUDE_MODEL


def _selected_prompt_id() -> int | None:
    try:
        selected = repository.prompt_repo.get_selected()
    except Exception:
        logger.warning("선택된 프롬프트 조회 실패", exc_info=True)
        return None
    return selected.id if selected else None


def _invoke_logged(agent, messages: list[dict], mode: str, label: str) -> dict:
    """에이전트를 실행하고 실행 기록(run)과 소요시간·도구 호출 수 로그를 남긴다.

    현재 근거 소유자(owner_scope) 안에서 불러야 한다. 결과 dict에 run_id를 더해 돌려준다.
    예외는 실행 기록을 error로 남긴 뒤 호출부가 처리하도록 다시 던진다.
    """
    owner = current_owner()
    if owner is None:
        raise RuntimeError("근거 소유자 없이 에이전트를 실행할 수 없습니다 (owner_scope 안에서 호출)")
    started = time.perf_counter()
    run_id = repository.evidence_repo.start_run(owner.type, owner.id, _model_name(mode), _selected_prompt_id())
    try:
        with run_scope(run_id):
            groups = group_repo.list_all()
            concepts = _graph_concepts()
            result = agent.invoke(
                {"messages": messages},
                context=AgentContext(system_prompt=render_prompt(prompt_repo.get_system_prompt(), ALIASES, groups, concepts)),
                config={"recursion_limit": 40})
    except Exception as exc:
        repository.evidence_repo.finish_run(run_id, "error", [], None, None, f"{type(exc).__name__}: {exc}")
        # 트레이스백은 호출부(소비자 루프, uvicorn)가 남기므로 여기서는 소요시간과 예외 종류만 남긴다
        logger.warning(
            "에이전트 실행 실패: %s, mode=%s, run=%s, %.1f초, %s: %s",
            label, mode, run_id, time.perf_counter() - started, type(exc).__name__, exc,
        )
        raise

    tool_calls = Counter(
        msg.name for msg in result["messages"] if getattr(msg, "type", None) == "tool"
    )
    repository.evidence_repo.finish_run(run_id, "ok", [], None, None)
    logger.info(
        "에이전트 실행 완료: %s, mode=%s, run=%s, owner=%s:%s, %.1f초, messages=%d, tools=%s",
        label, mode, run_id, owner.type, owner.id, time.perf_counter() - started, len(result["messages"]),
        dict(tool_calls) or "없음",
    )
    return {**result, "run_id": run_id}

def _graph_concepts() -> list[dict] | None:
    """프롬프트 힌트용 상위 개념 목록. 그래프를 못 읽어도 답변은 계속한다."""
    try:
        return graph_repo.list_concepts()
    except Exception:
        logger.warning("그래프 상위 개념 조회 실패, 힌트 없이 진행", exc_info=True)
        return None


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
    """검색·리랭크·그래프 도구 결과 메시지에서 출처 목록을 모은다.

    검색 결과를 리랭크하면 같은 청크가 두 번 나오므로 청크 ID 기준으로 한 번만 남긴다.
    그래프 결과는 문서의 페이지마다 한 건씩 넣는다 (본문 대신 그 페이지에서 찾은 개체 이름).
    """
    sources: list[dict] = []
    seen: set = set()

    def _add(doc) -> None:
        if not isinstance(doc, dict):
            return
        key = doc.get("id") or (doc.get("source"), doc.get("page"), doc.get("text"))
        if key in seen:
            return
        seen.add(key)
        sources.append(doc)

    for msg in messages:
        name = getattr(msg, "name", None)
        if name not in ("search_documents", "rerank_documents", "graph_search"):
            continue
        content = msg.content
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except json.JSONDecodeError:
                continue
        if name == "graph_search":
            for doc in _graph_sources(content):
                _add(doc)
        elif isinstance(content, list):
            for doc in content:
                _add(doc)
    return sources


def _graph_sources(result) -> list[dict]:
    """graph_search 결과의 documents[*]를 페이지 단위 출처로 바꾼다."""
    if not isinstance(result, dict):
        return []
    sources = []
    for doc in result.get("documents") or []:
        file_id = doc.get("file_id")
        text = "개체: " + ", ".join(doc.get("entities") or [])
        for page in doc.get("pages") or []:
            sources.append({
                "id": f"graph:{file_id}:{page}",
                "file_id": file_id,
                "source": doc.get("original_name") or doc.get("source") or "",
                "page": page,
                "text": text,
                "score": None,
            })
    return sources

_agents: dict[str, object] = {}


def get_agent(mode: Literal["claude", "local"] = "local"):
    """모드별로 에이전트를 최초 1회 빌드해 재사용한다."""
    if mode not in _agents:
        _agents[mode] = build_agent(mode)
    return _agents[mode]
