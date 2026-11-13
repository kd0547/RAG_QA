"""두 구성(현재 엔진·deepagents 시제품)이 함께 쓰는 실행 준비 (통합 지시서 F). 운영 코드가 아니다.

- 운영 storage/mail.db는 mode=ro로 열어 sqlite backup으로 작업 폴더에 복사하고, 운영 경로로 가는 연결을 모두 사본으로 돌린다.
  대화 기록(agent_threads.db)도 작업 폴더의 새 파일로 돌린다.
- 벡터DB(storage/chroma)도 작업 폴더로 복사해 그 사본을 연다 (운영 벡터DB 파일을 열지 않는다).
- 로컬 모델(config.LLM_*)과 임베딩(Ollama)은 서버와 같은 설정으로 만든다. 메일은 보내지 않는다 (메일 처리 루프를 쓰지 않는다).

반드시 프로젝트 모듈(repository 등)을 임포트하기 전에 setup()을 부른다.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EVAL_SET = ROOT / "tests" / "eval" / "eval_set.json"
PROD_DB = (ROOT / "storage" / "mail.db").resolve()
PROD_THREADS = (ROOT / "storage" / "agent_threads.db").resolve()
PROD_CHROMA = (ROOT / "storage" / "chroma").resolve()


def setup(work: Path) -> dict:
    """작업 폴더에 사본을 만들고 연결을 돌린다. 이미 사본이 있으면 다시 만들지 않는다 (두 구성이 같은 사본에서 시작하도록 호출부가 폴더를 나눈다)."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    work.mkdir(parents=True, exist_ok=True)
    copy_db = work / "mail.db"
    original_connect = sqlite3.connect
    if not copy_db.exists():
        with original_connect(f"file:{PROD_DB.as_posix()}?mode=ro", uri=True) as src, original_connect(copy_db) as dst:
            src.backup(dst)
    copy_chroma = work / "chroma"
    if not copy_chroma.exists():
        shutil.copytree(PROD_CHROMA, copy_chroma)

    def guarded(database, *args, **kwargs):
        try:
            target = Path(database).resolve()
        except (TypeError, OSError):
            target = None
        if target == PROD_DB:
            database = str(copy_db)
        elif target == PROD_THREADS:
            database = str(work / "agent_threads.db")
        return original_connect(database, *args, **kwargs)

    sqlite3.connect = guarded

    import chromadb

    original_client = chromadb.PersistentClient

    def client(path=None, *args, **kwargs):
        if path is not None and Path(path).resolve() == PROD_CHROMA:
            path = str(copy_chroma)
        return original_client(path, *args, **kwargs)

    chromadb.PersistentClient = client
    return {"db": copy_db, "chroma": copy_chroma, "threads": work / "agent_threads.db"}


def load_models() -> None:
    """서버 lifespan과 같은 로컬 모델·임베딩을 주입한다."""
    import config
    from langchain_ollama import OllamaEmbeddings
    from langchain_openai import ChatOpenAI

    from agent.llm_provider import set_local_model
    from retrieval.embedder import set_embedding_model

    set_embedding_model(OllamaEmbeddings(model=config.EMBEDDING_MODEL))
    set_local_model(ChatOpenAI(model=config.LLM_MODEL, base_url=config.LLM_BASE_URL, api_key=config.VLLM_API_KEY))


def cases() -> list[dict]:
    """평가 문항 중 질문이 있는 것 (주간판매 문항은 기준선에 없어 빈 자리다)."""
    data = json.loads(EVAL_SET.read_text(encoding="utf-8"))
    return [c for c in data["cases"] if (c.get("question") or "").strip() and c.get("mail_uid")]


def mail_input(case: dict):
    """메일 처리 루프와 같은 입력: 메일 본문과 첨부 (사본 DB에서 읽는다)."""
    import repository

    mail = repository.email_repo.get_mail_by_id(case["mail_uid"])
    if mail is None:
        return None, []
    return mail.body, list(mail.attachments or [])


def tool_messages(messages: list) -> list:
    return [m for m in messages if getattr(m, "type", None) == "tool"]


def is_tool_error(message) -> bool:
    content = str(getattr(message, "content", "") or "")
    head = content.lstrip()[:120]
    return (getattr(message, "status", None) == "error" or head.startswith("오류") or head.startswith("Error")
            or head.startswith('{"error"') or "'error':" in head[:20])


def token_usage(messages: list) -> tuple[int | None, int | None]:
    usages = [getattr(m, "usage_metadata", None) for m in messages if getattr(m, "type", None) == "ai"]
    usages = [u for u in usages if u]
    if not usages:
        return None, None
    return sum(u.get("input_tokens", 0) for u in usages), sum(u.get("output_tokens", 0) for u in usages)


def record(case: dict, *, answer: str | None, validation: dict | None, sources: list[dict], messages: list,
           started: float, error: str | None = None, model_calls: int | None = None) -> dict:
    tools = tool_messages(messages)
    tokens_in, tokens_out = token_usage(messages)
    return {
        "eval_title": case["eval_title"],
        "task_id": case.get("task_id"),
        "seconds": round(time.perf_counter() - started, 1),
        "error": error,
        "answer": answer,
        "validation": validation,
        "cited": [f"{s.get('source')} p{s.get('page')}" if s.get("page") is not None else s.get("source")
                  for s in sources if s.get("cited")],
        "tool_calls": len(tools),
        "tool_names": [getattr(m, "name", "?") for m in tools],
        "tool_errors": sum(1 for m in tools if is_tool_error(m)),
        "model_calls": model_calls if model_calls is not None else sum(1 for m in messages if getattr(m, "type", None) == "ai"),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
    }
