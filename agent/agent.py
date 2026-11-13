import json
import sqlite3
import threading
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import uuid4

from langchain.agents import create_agent
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite import SqliteSaver
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
from langchain.agents.middleware import (
    ClearToolUsesEdit, ContextEditingMiddleware, ModelCallLimitMiddleware, ModelRequest, SummarizationMiddleware,
    ToolCallLimitMiddleware, dynamic_prompt,
)
from langchain.agents.middleware.summarization import DEFAULT_SUMMARY_PROMPT
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

# 대화 기록(checkpoint) 저장소. main.py lifespan이 열고(set_checkpointer) 닫는다. 없으면 기록 없이 동작한다.
_checkpointer: SqliteSaver | None = None
AGENT_THREADS_DB = Path(__file__).resolve().parents[1] / "storage" / "agent_threads.db"
# 한 번의 실행에서 그래프가 밟을 수 있는 최대 단계 수 (config.AGENT_RECURSION_LIMIT 설명 참고)
RECURSION_LIMIT = config.AGENT_RECURSION_LIMIT

# 실행 한도 (서버 코드로 강제한다. 프롬프트에는 횟수를 쓰지 않는다)
SEARCH_CALLS_PER_RUN = 6
TOOL_CALLS_PER_RUN = 25
MODEL_CALLS_PER_RUN = 20
# ModelCallLimitMiddleware(exit_behavior="end")가 한도에 걸리면 마지막에 넣는 메시지의 앞부분
MODEL_LIMIT_MESSAGE_PREFIX = "Model call limits exceeded"

CLEARED_TOOL_PLACEHOLDER = "[축약됨 — list_evidence로 근거 ID를 다시 조회하세요]"
SUMMARY_PROMPT = DEFAULT_SUMMARY_PROMPT.replace(
    "<messages>",
    "IMPORTANT: Keep these exactly as written, never paraphrase or drop them: evidence IDs (e followed by hex, "
    "e.g. e1a2b3c4d), product model names, numbers with units, certification numbers, and reviewer rejection "
    "reasons ([검토 담당자 반려]). 근거 ID(e…), 제품 모델명, 수치, 인증번호, 반려 사유는 반드시 원문 그대로 보존한다.\n\n<messages>",
    1,
)


def open_checkpointer(path: str | Path = AGENT_THREADS_DB) -> SqliteSaver:
    """대화 기록 DB를 연다. 메일 처리 스레드와 API 스레드가 같이 쓰므로 check_same_thread=False."""
    conn = sqlite3.connect(str(path), check_same_thread=False)
    return SqliteSaver(conn)


def set_checkpointer(checkpointer: SqliteSaver | None) -> None:
    """get_agent가 만드는 에이전트들이 같은 checkpointer를 쓰게 한다. 이미 만든 에이전트는 버리고 다시 만든다."""
    global _checkpointer
    _checkpointer = checkpointer
    _agents.clear()


def build_middleware(summary_model) -> list:
    """맥락 예산·실행 한도 미들웨어 (순서 중요: 시스템 프롬프트 → 도구 결과 축약 → 요약 → 한도).

    - ContextEditing: 입력이 CTX_CLEAR_TRIGGER_TOKENS를 넘으면 최근 3개를 뺀 오래된 도구 결과를 자리표시자로.
      list_evidence 결과는 지우지 않는다 (자리표시자로 바뀐 결과의 근거 ID를 다시 볼 곳).
    - Summarization: 대화가 CTX_SUMMARY_TRIGGER_TOKENS를 넘으면 앞부분 요약, 최근 12개 메시지는 그대로.
      로컬 모델에 profile이 없어 비율 기준은 쓰지 않는다.
    - 실행당 한도: search_documents 6회, 도구 25회, 모델 호출 20회(넘으면 종료 → 답변으로 쓰지 않음).
    """
    return [
        _system_prompt,
        ContextEditingMiddleware(edits=[ClearToolUsesEdit(
            trigger=config.CTX_CLEAR_TRIGGER_TOKENS,
            keep=3,
            exclude_tools=("list_evidence",),
            placeholder=CLEARED_TOOL_PLACEHOLDER,
        )]),
        SummarizationMiddleware(
            model=summary_model,
            trigger=("tokens", config.CTX_SUMMARY_TRIGGER_TOKENS),
            keep=("messages", 12),
            summary_prompt=SUMMARY_PROMPT,
        ),
        ToolCallLimitMiddleware(tool_name="search_documents", run_limit=SEARCH_CALLS_PER_RUN),
        ToolCallLimitMiddleware(run_limit=TOOL_CALLS_PER_RUN),
        ModelCallLimitMiddleware(run_limit=MODEL_CALLS_PER_RUN, exit_behavior="end"),
    ]


def create_rag_agent(llm, *, checkpointer=None, summary_model=None):
    """도구·미들웨어·대화 기록을 붙인 에이전트. 테스트는 대역 모델로 이 함수를 그대로 쓴다."""
    return create_agent(
        model=llm,
        tools=TOOLS,
        middleware=build_middleware(summary_model or llm),
        context_schema=AgentContext,
        checkpointer=checkpointer,
    )


def build_agent(mode: Literal["claude", "local"], checkpointer: SqliteSaver | None = None):
    # 요약은 모드와 관계없이 로컬 모델로 한다 (메일 처리는 항상 local)
    return create_rag_agent(get_llm_model(mode), checkpointer=checkpointer, summary_model=get_llm_model("local"))


# 같은 대화(thread)를 두 실행이 동시에 이어 쓰지 않게 한다 (메일 소비자는 하나지만 /ask와 공유 대비)
_thread_locks: dict[str, threading.Lock] = {}
_thread_locks_guard = threading.Lock()


def _thread_lock(thread_id: str) -> threading.Lock:
    with _thread_locks_guard:
        return _thread_locks.setdefault(thread_id, threading.Lock())


def new_ask_thread_id() -> str:
    """/ask는 호출마다 새 대화다 (웹 멀티턴은 이번 범위가 아니다)."""
    return f"ask:{uuid4().hex}"


def task_thread_id(task_id: str) -> str:
    return f"task:{task_id}"


def new_session_owner() -> Owner:
    """메일이 아닌 질문(/ask)은 호출마다 새 세션을 근거 소유자로 쓴다."""
    return Owner("session", uuid4().hex)


def run_agent(
        question: str,
        mode: Literal["claude", "local"] = "claude",
        *,
        owner: Owner | None = None,
        thread_id: str | None = None,
) -> dict:
    agent = get_agent(mode)

    with owner_scope(owner or new_session_owner()) as current:
        result = _invoke_logged(
            agent, [{"role": "user", "content": question}], mode, label="질문",
            thread_id=thread_id or new_ask_thread_id(),
        )
        return _finish_answer(result, current)


def run_agent_temp_attachments(
        question: str,
        mode: Literal["claude", "local"] = "claude",
        attachments: list[Attachment] | None = None,
        review: tuple[int, str] | None = None,
        *,
        owner: Owner | None = None,
        thread_id: str | None = None,
) -> dict:
    """첨부가 있는 질문. 메일은 owner=Owner("task", task_id)·thread_id="task:{task_id}", /ask/attachments는 새 세션·새 대화.

    review: 아직 반영하지 않은 담당자 반려 (가장 큰 review_id, 반려 안내문). 메일만 쓴다.
    - 대화 기록이 있으면: 같은 대화에 반려 안내문만 새 user 메시지로 넣는다 (이전 초안·읽은 근거는 대화에 있다)
    - 대화 기록이 없으면(마이그레이션 전 task): 첫 실행처럼 질문·첨부를 넣고 반려 안내문을 두 번째 user 메시지로
    - 반려 없이 대화 기록만 있으면(생성 중 서버 재시작): 새 메시지 없이 마지막 checkpoint에서 이어 간다
    메시지 ID를 대화·review_id로 고정해, 같은 반려를 두 번 처리해도 메시지가 한 번만 들어간다.
    """
    agent = get_agent(mode)
    thread_id = thread_id or new_ask_thread_id()
    has_history = bool(_message_ids(agent, {"configurable": {"thread_id": thread_id}}))

    with owner_scope(owner or new_session_owner()) as current:
        preread: list[str] = []
        if has_history and review:
            messages = [_review_message(thread_id, review)]
            label = f"메일 반려 반영(review_id={review[0]}, 같은 대화)"
        elif has_history:
            messages = None
            label = "메일 이어서 실행(대화 기록에서 재개)"
        else:
            # 첨부 본문은 메시지에 넣지 않는다. 안내 한 줄만 넣고 모델이 read_attachment로 필요한 페이지를 읽는다.
            content: list[dict] = [{"type": "text", "text": question}]
            for index, attachment in enumerate(attachments or [], start=1):
                content.extend(_attachment_to_blocks(attachment, index, preread))
            messages = [HumanMessage(content=content, id=f"question:{thread_id}")]
            if review:
                messages.append(_review_message(thread_id, review))
            label = f"메일(첨부 {len(attachments or [])}건, 반려 {'있음, 대화 기록 없음' if review else '없음'})"

        result = _invoke_logged(agent, messages, mode, label=label, preread=preread, thread_id=thread_id)
        return _finish_answer(result, current)


def _review_message(thread_id: str, review: tuple[int, str]) -> HumanMessage:
    """반려 안내 user 메시지. ID가 같으면 대화 기록에서 덮어써져 두 번 쌓이지 않는다."""
    review_id, text = review
    return HumanMessage(content=text, id=f"review:{thread_id}:{review_id}")


def _finish_answer(result: dict, owner: Owner) -> dict:
    """최종 답변의 근거 줄을 검증·기록하고 본문·출처·검증 결과를 돌려준다."""
    validation = validate_answer(result["run_id"], owner, result["answer"])
    if not validation.ok:
        logger.warning("답변 근거 검증 경고: run=%s, errors=%s", result["run_id"], validation.errors)
    return {
        "answer": validation.answer,
        "sources": evidence_sources(result["run_id"], owner),
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


def _invoke_logged(
        agent, messages: list[dict] | None, mode: str, label: str,
        preread: list[str] | None = None, thread_id: str | None = None,
) -> dict:
    """에이전트를 실행하고 실행 기록(run)과 소요시간·도구 호출 수 로그를 남긴다.

    현재 근거 소유자(owner_scope) 안에서 불러야 한다. 결과 dict에 run_id를 더해 돌려준다.
    preread: 실행 전에 모델에 이미 보여 준 근거 (이미지 첨부). 이번 실행에서 읽은 것으로 기록한다.
    thread_id: 대화 기록(checkpoint)의 키. 같은 thread_id면 이전 메시지에 이어서 실행한다.
    messages가 None이면 새 메시지 없이 마지막 checkpoint에서 이어 간다.
    예외는 실행 기록을 error로 남긴 뒤 호출부가 처리하도록 다시 던진다.
    """
    owner = current_owner()
    if owner is None:
        raise RuntimeError("근거 소유자 없이 에이전트를 실행할 수 없습니다 (owner_scope 안에서 호출)")
    started = time.perf_counter()
    run_id = repository.evidence_repo.start_run(
        owner.type, owner.id, _model_name(mode), _selected_prompt_id(), label=label,
    )
    for evidence_id in preread or []:
        repository.evidence_repo.record_use(run_id, evidence_id, "read")
    trace = _ToolTrace()
    thread_id = thread_id or new_ask_thread_id()
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": RECURSION_LIMIT, "callbacks": [trace]}
    try:
        with run_scope(run_id), _thread_lock(thread_id):
            prior_ids = _message_ids(agent, config)
            groups = group_repo.list_all()
            concepts = _graph_concepts()
            result = agent.invoke(
                {"messages": messages} if messages is not None else None,
                context=AgentContext(system_prompt=render_prompt(prompt_repo.get_system_prompt(), ALIASES, groups, concepts)),
                config=config)
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

    # 대화 기록이 있으면 결과에 이전 실행의 메시지도 들어 있다. 이번 실행에서 생긴 메시지만 센다
    new_messages = [m for m in result["messages"] if getattr(m, "id", None) not in prior_ids]
    tokens_in, tokens_out = _token_usage(new_messages)
    final = result["messages"][-1] if result["messages"] else None
    answer = answer_text(final).strip() if getattr(final, "type", None) == "ai" else ""
    if answer.startswith(MODEL_LIMIT_MESSAGE_PREFIX):
        # 모델 호출 한도로 끝난 경우: 마지막 메시지는 업무 답변이 아니다
        repository.evidence_repo.finish_run(run_id, "limit", trace.calls, tokens_in, tokens_out, answer)
        logger.warning("에이전트 실행이 모델 호출 한도로 끝남: %s, mode=%s, run=%s", label, mode, run_id)
        raise AgentRunError(f"모델 호출 한도({MODEL_CALLS_PER_RUN}회)를 넘어 답변을 만들지 못했습니다")
    if not answer or getattr(final, "tool_calls", None):
        # 마지막이 도구 호출이거나 본문이 비면 업무 답변이 아니다
        repository.evidence_repo.finish_run(run_id, "error", trace.calls, tokens_in, tokens_out, "빈 답변")
        logger.warning("에이전트 실행 결과가 빈 답변: %s, mode=%s, run=%s", label, mode, run_id)
        raise AgentRunError("에이전트가 답변을 만들지 못했습니다 (빈 답변)")

    tool_calls = Counter(
        msg.name for msg in new_messages if getattr(msg, "type", None) == "tool"
    )
    repository.evidence_repo.finish_run(run_id, "ok", trace.calls, tokens_in, tokens_out)
    logger.info(
        "에이전트 실행 완료: %s, mode=%s, run=%s, thread=%s, %.1f초, messages=%d(새 %d), tools=%s, tokens=%s/%s",
        label, mode, run_id, thread_id, time.perf_counter() - started, len(result["messages"]), len(new_messages),
        dict(tool_calls) or "없음", tokens_in, tokens_out,
    )
    return {**result, "run_id": run_id, "answer": answer, "thread_id": thread_id}


def _message_ids(agent, config: dict) -> set:
    """이 대화에 이미 저장된 메시지 ID들. 대화 기록이 없으면 빈 집합."""
    if getattr(agent, "checkpointer", None) is None:
        return set()
    state = agent.get_state(config)
    return {getattr(m, "id", None) for m in (state.values or {}).get("messages", [])} - {None}


def thread_message_count(thread_id: str, mode: str = "local") -> int:
    """대화 기록에 저장된 메시지 수 (기록이 없거나 checkpointer가 없으면 0)."""
    agent = get_agent(mode)
    if getattr(agent, "checkpointer", None) is None:
        return 0
    state = agent.get_state({"configurable": {"thread_id": thread_id}})
    return len((state.values or {}).get("messages", []))

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


def evidence_sources(run_id: str, owner: Owner | None = None) -> list[dict]:
    """실행의 출처 목록. 답변이 인용한 근거(cite)가 있으면 그것만, 없으면 이번 실행에서 읽은 근거(read).

    반려 후 재작성처럼 이번 실행에서 새로 읽은 것이 없으면 같은 소유자(같은 메일의 대화)에서 읽은 근거를 쓴다.
    검색 결과(청크)는 읽은 것이 아니므로 들어가지 않는다. 그래프 검색 결과도 근거가 아니다.
    """
    evidence_repo = repository.evidence_repo
    cited = evidence_repo.uses_for_run(run_id, "cite")
    used = cited or evidence_repo.uses_for_run(run_id, "read")
    if not used and owner is not None:
        used = evidence_repo.uses_for_owner(owner.type, owner.id, "read")
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
        _agents[mode] = build_agent(mode, _checkpointer)
    return _agents[mode]
