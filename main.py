"""RAG 웹 앱 진입점 (FastAPI). 앱 조립만 담당하고 로직은 controller/에 있다."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from langchain_ollama import OllamaEmbeddings, ChatOllama
from langchain_openai import ChatOpenAI

import config
from agent.reranker import load_rerank
from app.controller.file_controller import router as file_router
from app.controller.mail_controller import router as mail_router
from app.controller.question_controller import router as question_router
from app.controller.search_controller import router as search_router
from mail.email_service import email_loop_build
from retrieval.embedder import set_embedding_model
from agent.llm_provider import set_llm_model
from agent.rag_agent import get_agent
from repository import db, email_repo, task_repo

# 프론트엔드는 frontend/ 의 React(Vite) 앱이다.
# - 개발: `npm run dev` (5173) + vite proxy로 이 서버를 호출
# - 배포: `npm run build` 결과물(frontend/dist)을 여기서 그대로 서빙
FRONTEND_DIST = Path(__file__).resolve().parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):

    embedding_model = OllamaEmbeddings(
        model=config.EMBEDDING_MODEL)

    set_embedding_model(embedding_model)

    llm = ChatOpenAI(
        model=config.LLM_MODEL,  # vLLM 실행 시 지정한 served-model-name
        base_url=config.LLM_BASE_URL,
        api_key="dummy",  # vLLM은 인증 안 하지만 파라미터는 필수라 아무 값이나 넣어야 함
        #max_tokens=65536,  # num_ctx 대신 이렇게, 필요시 조정
    )
    set_llm_model(llm)

    load_rerank()

    graph = get_agent()
    producer, consumer, stop_event = email_loop_build(email_repo, task_repo,db)
    yield

    # 서버 종료 시 정리
    stop_event.set()
    producer.join(timeout=5)
    consumer.join(timeout=5)


app = FastAPI(title="RAG PDF Uploader", lifespan=lifespan)
app.include_router(file_router)
app.include_router(search_router)
app.include_router(question_router)
app.include_router(mail_router)

if FRONTEND_DIST.is_dir():
    # 라우터보다 뒤에 등록해야 /upload, /ask 등 API 경로가 가려지지 않는다.
    # dist 안에 실제 파일이 있으면 그 파일을, 없으면 index.html을 돌려준다.
    # /mail, /ocr 은 서버에 없는 경로이므로 여기서 index.html을 받아 클라이언트 라우터가 처리한다.
    @app.get("/{spa_path:path}", include_in_schema=False)
    def frontend(spa_path: str) -> FileResponse:
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
