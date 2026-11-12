import json
import threading
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import uuid4

from langchain.agents import create_agent
from langchain_core.callbacks import BaseCallbackHandler
from langgraph.errors import GraphRecursionError
from dotenv import load_dotenv
from pathlib import Path

import config
import repository
from agent.evidence_context import Owner, current_owner, owner_scope, run_scope, temp_attachments
from agent.llm_provider import get_llm_model
from agent.prompt import render_prompt
from agent.validation import validate_answer
from entity.type import Attachment, DocumentType
from repository import graph_repo, group_repo, prompt_repo
from tools.tool import (
    attachment_page_texts, graph_search, grep_documents, list_documents, list_evidence,
    read_attachment, read_pages, rerank_documents, search_documents,
)
from langchain.agents.middleware import dynamic_prompt, ModelRequest
import logging
import yaml
load_dotenv()

logger = logging.getLogger(__name__)

TOOLS = [
    graph_search, list_documents, grep_documents, read_pages, read_attachment,
    search_documents, rerank_documents, list_evidence,
]


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

    with owner_scope(owner or new_session_owner()) as current:
        result = _invoke_logged(
            agent, [{"role": "user", "content": question}], mode, label="질문",
        )
        return _finish_answer(result, current)


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

    with owner_scope(owner or new_session_owner()) as current:
        # 첨부 본문은 메시지에 넣지 않는다. 안내 한 줄만 넣고 모델이 read_attachment로 필요한 페이지를 읽는다.
        content: list[dict] = [{"type": "text", "text": question}]
        preread: list[str] = []
        for index, attachment in enumerate(attachments or [], start=1):
            content.extend(_attachment_to_blocks(attachment, index, preread))

        # 담당자 반려 피드백은 질문과 섞이지 않도록 별도 블록으로 붙인다.
        if review_feedback:
            content.append({"type": "text", "text": review_feedback})

        result = _invoke_logged(
            agent, [{"role": "user", "content": content}], mode,
            label=f"메일(첨부 {len(attachments or [])}건, 반려피드백 {'있음' if review_feedback else '없음'})",
            preread=preread,
        )
        return _finish_answer(result, current)


def _finish_answer(result: dict, owner: Owner) -> dict:
    """최종 답변의 근거 줄을 검증·기록하고 본문·출처·검증 결과를 돌려준다."""
    validation = validate_answer(result["run_id"], owner, result["answer"])
    if not validation.ok:
        logger.warning("답변 근거 검증 경고: run=%s, errors=%s", result["run_id"], validation.errors)
    return {
        "answer": validation.answer,
        "sources": evidence_sources(result["run_id"]),
        "run_id": result["run_id"],
        "validation": validation.to_dict(),
    }


class AgentRunError(RuntimeError):
    """실행은 끝났지만 고객 답변으로 쓸 수 없는 결과 (빈 답변·한도 초과). drafted로 저장하지 않는다."""


class _ToolTrace(BaseCallbackHandler):
    """실행 중 도구 호출을 시각과 함께 모은다 (run.tool_calls_json → 검토 화면 '에이전트가 한 일')."""

    def __init__(self):
        self.calls: list[dict] = []
        self._lock = threading.Lock()

    def on_tool_start(self, serialized, input_str, *, inputs=None, **kwargs):
        name = (serialized or {}).get("name") or kwargs.get("name") or "?"
        args = inputs if inputs is not None else input_str
        try:
            summary = json.dumps(args, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            summary = str(args)
        with self._lock:
            self.calls.append({"tool": name, "args_summary": summary[:200], "at": datetime.now().isoformat()})


def answer_text(message) -> str:
    """AI 메시지의 본문 문자열. Claude처럼 블록 목록으로 오면 text 블록만 잇는다."""
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    return str(content or "")


def _token_usage(messages: list) -> tuple[int | None, int | None]:
    usages = [getattr(m, "usage_metadata", None) for m in messages if getattr(m, "type", None) == "ai"]
    usages = [u for u in usages if u]
    if not usages:
        return None, None
    return sum(u.get("input_tokens", 0) for u in usages), sum(u.get("output_tokens", 0) for u in usages)


def _model_name(mode: str) -> str:
    return config.LLM_MODEL if mode == "local" else config.CLAUDE_MODEL


def _selected_prompt_id() -> int | None:
    try:
        selected = repository.prompt_repo.get_selected()
    except Exception:
        logger.warning("선택된 프롬프트 조회 실패", exc_info=True)
        return None
    return selected.id if selected else None


def _invoke_logged(agent, messages: list[dict], mode: str, label: str, preread: list[str] | None = None) -> dict:
    """에이전트를 실행하고 실행 기록(run)과 소요시간·도구 호출 수 로그를 남긴다.

    현재 근거 소유자(owner_scope) 안에서 불러야 한다. 결과 dict에 run_id를 더해 돌려준다.
    preread: 실행 전에 모델에 이미 보여 준 근거 (이미지 첨부). 이번 실행에서 읽은 것으로 기록한다.
    예외는 실행 기록을 error로 남긴 뒤 호출부가 처리하도록 다시 던진다.
    """
    owner = current_owner()
    if owner is None:
        raise RuntimeError("근거 소유자 없이 에이전트를 실행할 수 없습니다 (owner_scope 안에서 호출)")
    started = time.perf_counter()
    run_id = repository.evidence_repo.start_run(owner.type, owner.id, _model_name(mode), _selected_prompt_id())
    for evidence_id in preread or []:
        repository.evidence_repo.record_use(run_id, evidence_id, "read")
    trace = _ToolTrace()
    try:
        with run_scope(run_id):
            groups = group_repo.list_all()
            concepts = _graph_concepts()
            result = agent.invoke(
                {"messages": messages},
                context=AgentContext(system_prompt=render_prompt(prompt_repo.get_system_prompt(), ALIASES, groups, concepts)),
                config={"recursion_limit": 40, "callbacks": [trace]})
    except Exception as exc:
        # 재귀 한도 초과는 '한도'로 구분해 남긴다. 어느 쪽이든 답변은 저장되지 않는다 (호출부가 failed 처리)
        status = "limit" if isinstance(exc, GraphRecursionError) else "error"
        repository.evidence_repo.finish_run(run_id, status, trace.calls, None, None, f"{type(exc).__name__}: {exc}")
        # 트레이스백은 호출부(소비자 루프, uvicorn)가 남기므로 여기서는 소요시간과 예외 종류만 남긴다
        logger.warning(
            "에이전트 실행 실패: %s, mode=%s, run=%s, status=%s, %.1f초, %s: %s",
            label, mode, run_id, status, time.perf_counter() - started, type(exc).__name__, exc,
        )
        raise

    tokens_in, tokens_out = _token_usage(result["messages"])
    final = result["messages"][-1] if result["messages"] else None
    answer = answer_text(final).strip() if getattr(final, "type", None) == "ai" else ""
    if not answer or getattr(final, "tool_calls", None):
        # 마지막이 도구 호출이거나 본문이 비면 업무 답변이 아니다
        repository.evidence_repo.finish_run(run_id, "error", trace.calls, tokens_in, tokens_out, "빈 답변")
        logger.warning("에이전트 실행 결과가 빈 답변: %s, mode=%s, run=%s", label, mode, run_id)
        raise AgentRunError("에이전트가 답변을 만들지 못했습니다 (빈 답변)")

    tool_calls = Counter(
        msg.name for msg in result["messages"] if getattr(msg, "type", None) == "tool"
    )
    repository.evidence_repo.finish_run(run_id, "ok", trace.calls, tokens_in, tokens_out)
    logger.info(
        "에이전트 실행 완료: %s, mode=%s, run=%s, owner=%s:%s, %.1f초, messages=%d, tools=%s, tokens=%s/%s",
        label, mode, run_id, owner.type, owner.id, time.perf_counter() - started, len(result["messages"]),
        dict(tool_calls) or "없음", tokens_in, tokens_out,
    )
    return {**result, "run_id": run_id, "answer": answer}

def _graph_concepts() -> list[dict] | None:
    """프롬프트 힌트용 상위 개념 목록. 그래프를 못 읽어도 답변은 계속한다."""
    try:
        return graph_repo.list_concepts()
    except Exception:
        logger.warning("그래프 상위 개념 조회 실패, 힌트 없이 진행", exc_info=True)
        return None


def _attachment_to_blocks(attachment: Attachment, index: int, preread: list[str]) -> list[dict]:
    """첨부 하나를 메시지 content 블록으로 바꾼다. 처리할 수 없으면 빈 목록.

    - 문서: 본문 대신 "[첨부 1] 파일명 (pdf, attachment_id=17, 12페이지) — read_attachment로 읽으세요" 한 줄.
      페이지 수를 알려고 처음 한 번 파싱해 둔다 (메일 첨부는 attachment_page에 저장, 임시 첨부는 세션에 보관).
    - 이미지: 지금처럼 image_url 블록. 이미지도 근거로 등록하고(파일명·크기) 이미 본 것으로 기록한다.
    """
    # 메일 수신부는 type을 "image"/"pdf"/"docx" 등 문자열로 넣으므로 Enum으로 맞춘다.
    try:
        doc_type = DocumentType(attachment.type)
    except ValueError:
        logger.warning("지원하지 않는 첨부 형식: %s (%s)", attachment.filename, attachment.type)
        return []
    name = attachment.filename or f"attachment.{doc_type.value}"
    owner = current_owner()

    if doc_type == DocumentType.IMAGE:
        if not attachment.image:
            return []
        size_kb = len(attachment.image) * 3 // 4 // 1024
        evidence_id = repository.evidence_repo.register(
            owner.type, owner.id, "attachment", f"이미지 첨부: {name} (약 {size_kb}KB)",
            attachment_id=attachment.attachment_id, source_name=name,
        )
        preread.append(evidence_id)
        return [
            {"type": "text", "text": f"[첨부 {index}] {name} (이미지, evidence_id={evidence_id})"},
            {"type": "image_url", "image_url": {"url": attachment.image}},
        ]

    if attachment.attachment_id is not None:
        entry = {"attachment_id": attachment.attachment_id, "filename": name, "type": doc_type.value,
                 "path": attachment.path, "temp": False}
    else:
        # /ask/attachments의 임시 첨부: 이번 세션 안에서만 음수 번호로 찾는다 (메일 첨부 번호와 겹치지 않게)
        registry = temp_attachments()
        temp_id = -(len(registry) + 1)
        entry = {"attachment_id": temp_id, "filename": name, "type": doc_type.value,
                 "path": attachment.path, "temp": True, "pages": None}
        registry[temp_id] = entry

    try:
        page_count = len(attachment_page_texts(entry))
    except Exception:
        logger.exception("첨부 파일 파싱 실패: %s", name)
        # 모델이 첨부가 있었다는 사실은 알도록 남긴다.
        return [{"type": "text", "text": f"[첨부 {index}] {name} ({doc_type.value}) — 파일을 읽지 못했습니다"}]
    return [{"type": "text", "text": (
        f"[첨부 {index}] {name} ({doc_type.value}, attachment_id={entry['attachment_id']}, {page_count}페이지)"
        " — read_attachment로 읽으세요"
    )}]


# 출처 목록에 담는 근거 본문 길이
SOURCE_TEXT_CHARS = 500


def evidence_sources(run_id: str) -> list[dict]:
    """실행의 출처 목록. 답변이 인용한 근거(cite)가 있으면 그것만, 없으면 이번 실행에서 읽은 근거(read).

    검색 결과(청크)는 읽은 것이 아니므로 들어가지 않는다. 그래프 검색 결과도 근거가 아니다.
    """
    cited = repository.evidence_repo.uses_for_run(run_id, "cite")
    used = cited or repository.evidence_repo.uses_for_run(run_id, "read")
    return [
        {
            "evidence_id": e["evidence_id"],
            "file_id": e["file_id"],
            "source": e["source_name"] or "",
            "page": e["page"],
            "text": (e["text"] or "")[:SOURCE_TEXT_CHARS],
            "origin_type": e["origin_type"],
            "cited": bool(cited),
        }
        for e in used
    ]

_agents: dict[str, object] = {}


def get_agent(mode: Literal["claude", "local"] = "local"):
    """모드별로 에이전트를 최초 1회 빌드해 재사용한다."""
    if mode not in _agents:
        _agents[mode] = build_agent(mode)
    return _agents[mode]
