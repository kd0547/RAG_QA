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
from app.controller.question_controller import router as question_router
from app.controller.search_controller import router as search_router
from rag.embedder import set_embedding_model
from agent.rag_agent import set_llm_model, get_graph

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):

    embedding_model = OllamaEmbeddings(
        model="bge-m3:latest")

    set_embedding_model(embedding_model)

    llm = ChatOllama(
        model="gemma4:31b-it-qat"
    )
    set_llm_model(llm)

    load_rerank()

    graph = get_graph()
    graph.get_graph().draw_png(
        output_file_path="./data/graph.png"
    )


    yield


app = FastAPI(title="RAG PDF Uploader", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.include_router(file_router)
app.include_router(search_router)
app.include_router(question_router)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
