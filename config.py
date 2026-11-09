"""환경(개발 PC / 릴리스 PC)마다 달라지는 설정.

기본값은 릴리스 서버(14.38.199.190) 기준이고, PC마다 .env 또는 환경변수로 덮어쓴다.
키 목록은 .env.example 참고.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ---------- LLM / 임베딩 ----------
# vLLM OpenAI 호환 엔드포인트와 served-model-name
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://14.38.199.190:9090/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3.8-flash-next")
# Ollama 임베딩 모델 (Ollama 주소는 langchain-ollama가 OLLAMA_HOST로 읽는다)
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "bge-m3:latest")

#LLM API-KEY
VLLM_API_KEY = os.getenv("VLLM_API_KEY", "")

CLAUDE_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Claude 모드 모델 (API 키는 langchain-anthropic이 ANTHROPIC_API_KEY로 읽는다)
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5")

# ---------- OCR ----------
# 환경변수/.env 변경 후 프로세스를 재시작한다. 기본값은 기존 LLM 방식.
OCR_BACKEND = os.getenv("OCR_BACKEND", "llm")
_PROJECT_ROOT = Path(__file__).resolve().parent
PADDLEOCR_HOME = Path(os.getenv("PADDLEOCR_HOME", str(_PROJECT_ROOT.parent / "paddleocr_vl_test")))
PADDLEOCR_PYTHON = os.getenv("PADDLEOCR_PYTHON", str(
    PADDLEOCR_HOME / (".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python")
))
PADDLEOCR_VL_MODEL_DIR = os.getenv("PADDLEOCR_VL_MODEL_DIR", str(
    PADDLEOCR_HOME / "models/paddlex/official_models/PaddleOCR-VL-1.6"
))
PADDLEOCR_LAYOUT_MODEL_DIR = os.getenv("PADDLEOCR_LAYOUT_MODEL_DIR", str(
    PADDLEOCR_HOME / "models/paddlex/official_models/PP-DocLayoutV3"
))
PADDLEOCR_DEVICE = os.getenv("PADDLEOCR_DEVICE", "gpu:0")
PADDLEOCR_TIMEOUT = float(os.getenv("PADDLEOCR_TIMEOUT", "300"))
PADDLEOCR_CACHE_DIR = _PROJECT_ROOT / os.getenv("PADDLEOCR_CACHE_DIR", "temp/paddleocr")



# ---------- 메일 ----------
# 검토 요청 메일에 넣는 링크의 기준 주소 (담당자가 브라우저로 여는 주소)
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://14.38.199.190:9092")
# 검토 담당자 메일 주소
REVIEWER_EMAIL = os.getenv("REVIEWER_EMAIL", "dongwook.kim@trigem.co.kr")

# ---------- 청킹 ----------
DEFAULT_CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "2000"))
DEFAULT_CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "200"))

# ---------- 문서 그래프 (Graph RAG) ----------
# 업로드·페이지 검수 저장 뒤 백그라운드로 개체·관계를 뽑을지 (0이면 끈다. /graph/rebuild로 따로 뽑을 수 있다)
GRAPH_EXTRACT_ENABLED = os.getenv("GRAPH_EXTRACT_ENABLED", "1") not in ("0", "false", "False", "")
# LLM에 넘기는 페이지 텍스트 최대 길이
GRAPH_EXTRACT_MAX_CHARS = int(os.getenv("GRAPH_EXTRACT_MAX_CHARS", "12000"))

# ---------- 로그 ----------
# 로그 파일 폴더 (기본: 프로젝트 루트의 logs/). 상대 경로면 프로젝트 루트 기준.
LOG_DIR = Path(__file__).resolve().parent / os.getenv("LOG_DIR", "logs")
# DEBUG / INFO / WARNING / ERROR
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
# 날짜별로 교체된 로그 파일을 며칠치 남길지
LOG_BACKUP_DAYS = int(os.getenv("LOG_BACKUP_DAYS", "30"))
