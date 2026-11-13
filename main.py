"""RAG 웹 앱 진입점 (FastAPI). 앱 조립만 담당하고 API 라우터는 app/routers/ 에 있다."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from langchain_anthropic import ChatAnthropic
from langchain_ollama import OllamaEmbeddings, ChatOllama
from langchain_openai import ChatOpenAI

import config
from agent.reranker import load_rerank
from app import access_log, system_monitor
from app.access_log import AccessLogMiddleware
from app.routers.app_config import router as config_router
from app.routers.monitor import router as monitor_router
from app.routers.customers import router as customer_router
from app.routers.files import router as file_router
from app.routers.graph import router as graph_router
from app.routers.group import router as group_router
from app.routers.mail_links import router as mail_link_router
from app.routers.mails import router as mail_router
from app.routers.prompt import router as prompt_router
from app.routers.questions import router as question_router
from app.routers.search import router as search_router
from app.routers.skills import router as skill_router
from app.routers.spec_import import router as spec_import_router
from app.routers.specs import router as spec_router
from mail.email_service import email_loop_build
from retrieval.embedder import set_embedding_model
from agent.llm_provider import set_local_model, set_claude_model
from agent.agent import ALIASES, get_agent, open_checkpointer, set_checkpointer
from agent.skills import reload_skills
from agent.request_analysis import start_analyzer
from repository import db, email_repo, evidence_repo, graph_repo, group_repo, prompt_repo, skill_repo, task_repo
from logging_config import setup_logging

# uvicorn이 앱을 import할 때 한 번 실행된다. 이후 메일 스레드·라우터 로그가 logs/에 남는다.
setup_logging()
logger = logging.getLogger(__name__)

# 프론트엔드는 frontend/ 의 React(Vite) 앱이다.
# - 개발: `npm run dev` (5173) + vite proxy로 이 서버를 호출
# - 배포: `npm run build` 결과물(frontend/dist)을 여기서 그대로 서빙
FRONTEND_DIST = Path(__file__).resolve().parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 환경마다 .env가 달라 "어떤 설정으로 떴는지"가 장애 분석의 출발점이다. 비밀값은 유무만 남긴다.
    logger.info(
        "서버 시작: llm=%s @ %s, embedding=%s @ %s, claude=%s, public_base_url=%s, reviewer=%s, chunk=%d/%d",
        config.LLM_MODEL, config.LLM_BASE_URL,
        config.EMBEDDING_MODEL, os.getenv("OLLAMA_HOST", "(기본값)"),
        config.CLAUDE_MODEL if config.CLAUDE_API_KEY else "비활성(ANTHROPIC_API_KEY 없음)",
        config.PUBLIC_BASE_URL, config.REVIEWER_EMAIL,
        config.DEFAULT_CHUNK_SIZE, config.DEFAULT_CHUNK_OVERLAP,
    )

    # 접속 기록 저장(access_log 테이블)과 CPU·메모리·GPU 측정 스레드. 서버 상태 화면(/status)이 읽는다.
    access_log.start()
    system_monitor.start()

    # 답변 생성 중(processing)에 서버가 꺼졌던 작업은 pending으로 되돌려 다시 처리한다.
    # 발송 중(sending)이던 작업은 메일이 이미 나갔을 수 있어 pending/drafted로 되돌리지 않고 send_unknown으로 넘긴다
    # (자동 재발송 없음. 담당자가 '발송 확인됨' 또는 '재발송'을 고른다).
    try:
        restored = task_repo.reset_processing()
        if restored:
            logger.warning("생성 중이던 작업 %d건을 pending으로 되돌림", restored)
        stale = task_repo.mark_stale_sending()
        if stale:
            logger.warning("발송 중이던 작업 %d건을 send_unknown으로 넘김 (담당자 확인 필요)", stale)
    except Exception:
        logger.exception("생성·발송 중 작업 복구 실패")

    # 웹 질문(/ask)의 근거·실행 기록은 보관 기간이 지나면 지운다. 메일 기록은 지우지 않는다.
    try:
        purged = evidence_repo.purge_sessions(config.SESSION_EVIDENCE_RETENTION_DAYS)
        logger.info("오래된 웹 질문 기록 정리(%d일 초과): %s", config.SESSION_EVIDENCE_RETENTION_DAYS, purged)
    except Exception:
        logger.exception("웹 질문 기록 정리 실패")

    # 기본 프롬프트가 DB에 없으면 agent/prompt.py 내용으로 넣는다.
    # 실패해도 에이전트는 agent/prompt.py 원문으로 동작하므로 서버 시작은 막지 않는다.
    try:
        prompt_repo.ensure_default()
        # 근거 ID 방식의 프롬프트 v2를 처음 한 번 넣고 선택한다 (기존 프롬프트는 그대로 둔다)
        prompt_repo.ensure_v2()
    except Exception:
        logger.exception("기본 프롬프트 등록 실패")

    # 업무 절차(skills/*/SKILL.md)를 한 번 읽어 둔다. 문서를 바꾸면 서버를 다시 시작해야 반영된다.
    # 검사를 어긴 문서는 빼고(ERROR 로그) 서버는 계속 뜬다.
    loaded_skills = reload_skills()
    logger.info("업무 절차 %d개: %s", len(loaded_skills),
                ", ".join(f"{s.name}·{s.digest}" for s in loaded_skills.values()) or "없음")
    # 문의 유형의 기본 유형(입찰 사양 대조·인증 자료 요청·단순 사실 조회)을 없을 때만 넣는다 (지시서 I2)
    try:
        seeded = skill_repo.ensure_seed_types()
        if seeded:
            logger.info("기본 문의 유형 %d개 등록", seeded)
    except Exception:
        logger.exception("기본 문의 유형 등록 실패")

    # 과거 자동 생성된 빈 그룹만 정리한다. 사용자가 이름·설명을 바꿨거나 파일을 넣은 그룹은 보존한다.
    try:
        removed = group_repo.prune_unused_defaults()
        if removed:
            logger.info("사용하지 않는 기본 문서 그룹 %d개 정리", removed)
    except Exception:
        logger.exception("기본 문서 그룹 정리 실패")

    # aliases.yaml의 상위 개념(KC 인증 등)을 문서 그래프에 넣는다. 실패해도 그래프 검색만 덜 펼쳐질 뿐이다.
    try:
        linked = graph_repo.seed_concepts(ALIASES)
        logger.info("문서 그래프 상위 개념 등록: 연결 %d개, %s", linked, graph_repo.stats())
    except Exception:
        logger.exception("문서 그래프 상위 개념 등록 실패")

    embedding_model = OllamaEmbeddings(
        model=config.EMBEDDING_MODEL)

    set_embedding_model(embedding_model)

    local_llm = ChatOpenAI(
        model=config.LLM_MODEL,  # vLLM 실행 시 지정한 served-model-name
        base_url=config.LLM_BASE_URL,
        api_key=config.VLLM_API_KEY,  # vLLM은 인증 안 하지만 파라미터는 필수라 아무 값이나 넣어야 함
        #max_tokens=65536,  # num_ctx 대신 이렇게, 필요시 조정
    )
    set_local_model(local_llm)

    if config.CLAUDE_API_KEY:
        claude_llm = ChatAnthropic(
            model=config.CLAUDE_MODEL,  # API 키는 .env의 ANTHROPIC_API_KEY를 자동으로 읽는다
            api_key=config.CLAUDE_API_KEY,
        )

        set_claude_model(claude_llm)

    reranker_ready = load_rerank()

    # 에이전트 대화 기록(storage/agent_threads.db). 반려 후 같은 메일의 대화로 이어서 쓴다.
    checkpointer = open_checkpointer()
    set_checkpointer(checkpointer)

    graph = get_agent()
    producer, consumer, stop_event = email_loop_build(email_repo, task_repo,db)
    # 저장된 메일 문의를 답변 뒤에 따로 분석한다 (지시서 I3). 대기·처리 중 메일이 있으면 그 주기는 쉰다
    analyzer, analyzer_stop = start_analyzer()
    logger.info("서버 준비 완료: reranker=%s", "사용" if reranker_ready else "미사용(로드 실패)")
    yield

    # 서버 종료 시 정리
    logger.info("서버 종료 시작: 메일 스레드 정지 요청")
    stop_event.set()
    analyzer_stop.set()
    producer.join(timeout=5)
    consumer.join(timeout=5)
    analyzer.join(timeout=5)
    # 답변 생성 중이던 스레드는 5초 안에 끝나지 않을 수 있다 (프로세스는 끝날 때까지 기다린다)
    # 분석 스레드는 데몬이라 모델 호출 중이어도 프로세스 종료를 막지 않는다 (호출에는 시간 제한이 있다)
    still_running = [t.name for t in (producer, consumer, analyzer) if t.is_alive()]
    if still_running:
        logger.warning("종료 대기 시간 안에 끝나지 않은 스레드: %s", still_running)
    system_monitor.stop()
    access_log.stop()  # 큐에 남은 접속 기록을 저장한다
    set_checkpointer(None)
    checkpointer.conn.close()
    logger.info("서버 종료")


app = FastAPI(title="RAG PDF Uploader", lifespan=lifespan)
app.add_middleware(AccessLogMiddleware)
app.include_router(config_router)
app.include_router(monitor_router)
app.include_router(file_router)
app.include_router(group_router)
app.include_router(graph_router)
app.include_router(search_router)
app.include_router(question_router)
app.include_router(mail_router)
app.include_router(mail_link_router)
app.include_router(customer_router)
app.include_router(prompt_router)
app.include_router(skill_router)
app.include_router(spec_router)
app.include_router(spec_import_router)

if FRONTEND_DIST.is_dir():
    # 라우터보다 뒤에 등록해야 /upload, /ask 등 API 경로가 가려지지 않는다.
    # dist 안에 실제 파일이 있으면 그 파일을, 없으면 index.html을 돌려준다.
    # /mail, /ocr 은 서버에 없는 경로이므로 여기서 index.html을 받아 클라이언트 라우터가 처리한다.
    @app.get("/{spa_path:path}", include_in_schema=False)
    def frontend(spa_path: str) -> FileResponse:
        # 존재하지 않는 API 요청에 HTML을 반환하면 프론트엔드에서 JSON 파싱 오류가 난다.
        if spa_path.split("/", 1)[0] in {"file", "files", "groups", "config", "upload", "ask", "search", "mails", "prompts", "specs", "graph", "monitor", "customers", "skills"}:
            raise HTTPException(status_code=404, detail="요청한 API를 찾을 수 없습니다.")
        target = (FRONTEND_DIST / spa_path).resolve()
        # resolve() 후 dist 하위인지 확인해 경로 탈출(../)을 막는다
        if spa_path and target.is_file() and target.is_relative_to(FRONTEND_DIST.resolve()):
            return FileResponse(target)
        return FileResponse(FRONTEND_DIST / "index.html")

else:

    @app.get("/")
    def frontend_missing() -> dict:
        return {
            "detail": (
                "프론트엔드 빌드가 없습니다. frontend/ 에서 `npm run build` 를 실행하거나, "
                "개발 중이면 `npm run dev` (http://localhost:5173) 를 사용하세요."
            )
        }
