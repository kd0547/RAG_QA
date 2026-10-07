"""환경(개발 PC / 릴리스 PC)마다 달라지는 설정.

기본값은 릴리스 서버(14.38.199.190) 기준이고, PC마다 .env 또는 환경변수로 덮어쓴다.
키 목록은 .env.example 참고.
"""
import os

from dotenv import load_dotenv

load_dotenv()

# ---------- LLM / 임베딩 ----------
# vLLM OpenAI 호환 엔드포인트와 served-model-name
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://14.38.199.190:9090/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3.8-flash-next")
# Ollama 임베딩 모델 (Ollama 주소는 langchain-ollama가 OLLAMA_HOST로 읽는다)
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "bge-m3:latest")

# ---------- 메일 ----------
# 검토 요청 메일에 넣는 링크의 기준 주소 (담당자가 브라우저로 여는 주소)
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://14.38.199.190:8000")
# 검토 담당자 메일 주소
REVIEWER_EMAIL = os.getenv("REVIEWER_EMAIL", "dongwook.kim@trigem.co.kr")

# ---------- 청킹 ----------
DEFAULT_CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "2000"))
DEFAULT_CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "200"))
