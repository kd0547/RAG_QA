"""RAG 웹 앱 진입점 (FastAPI). 앱 조립만 담당하고 로직은 controller/에 있다."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from langchain_ollama import OllamaEmbeddings, ChatOllama

from agent.reranker import load_rerank
from app.controller.file_controller import router as file_router
from app.controller.mail_controller import router as mail_router
from app.controller.question_controller import router as question_router
from app.controller.search_controller import router as search_router
from mail.email_service import email_loop_build
from rag.embedder import set_embedding_model
from agent.llm_provider import set_llm_model
from agent.rag_agent import get_agent
from repository import db, email_repo, task_repo

STATIC_DIR = Path(__file__).resolve().parent / "app" / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):

    embedding_model = OllamaEmbeddings(
        model="bge-m3:latest")

    set_embedding_model(embedding_model)

    llm = ChatOllama(
        model="qwen3.8:27b",
        num_ctx=65536,
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
app.mount("/app/static", StaticFiles(directory=STATIC_DIR), name="static")
app.include_router(file_router)
app.include_router(search_router)
app.include_router(question_router)
app.include_router(mail_router)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
