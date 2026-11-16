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
# 검토 알림 메일의 SMTP 시간 제한(초). 알림은 별도 스레드라 처리 루프를 막지 않지만, 장애 때 스레드가 오래 남지 않게 짧게 둔다.
# 승인 발송은 mail/email_send.py의 SMTP_TIMEOUT_SECONDS(60)를 쓴다.
NOTIFY_SMTP_TIMEOUT_SECONDS = float(os.getenv("NOTIFY_SMTP_TIMEOUT_SECONDS", "20"))
# 메일 수신(POP3) 연결·응답 대기 시간(초). 없으면 메일 서버 장애 때 수신 스레드가 무기한 멈춰 서버 종료를 막는다
POP3_TIMEOUT_SECONDS = float(os.getenv("POP3_TIMEOUT_SECONDS", "30"))
# MS 토큰 요청(msal) HTTP 대기 시간(초). 대화형 로그인(브라우저)에는 적용되지 않는다
MSAL_TIMEOUT_SECONDS = float(os.getenv("MSAL_TIMEOUT_SECONDS", "30"))

# ---------- 청킹 ----------
DEFAULT_CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "2000"))
DEFAULT_CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "200"))

# ---------- 에이전트 검색 기본값 ----------
# search_documents·rerank_documents 도구의 기본값. 화면(/ask)의 query_top_n·rerank_top_n은 더 이상 쓰지 않는다.
SEARCH_TOP_K = int(os.getenv("SEARCH_TOP_K", "5"))
RERANK_TOP_N = int(os.getenv("RERANK_TOP_N", "3"))

# ---------- 에이전트 맥락 예산 (agent/agent.py 미들웨어) ----------
# 로컬 모델(qwen3.8-flash-next)의 최대 컨텍스트는 262,144토큰(vLLM /v1/models max_model_len)이다.
# 아래 값은 모델 한계가 아니라 비용·지연 예산이다. 2026-11-12 실제 질문 1건이 모델 호출 9회에 입력 63,264토큰을 썼다.
# 오래된 도구 결과를 자리표시자로 바꾸는 기준 (모델 입력의 대략적 토큰 수)
CTX_CLEAR_TRIGGER_TOKENS = int(os.getenv("CTX_CLEAR_TRIGGER_TOKENS", "24000"))
# 대화가 이보다 길어지면 앞부분을 요약한다
CTX_SUMMARY_TRIGGER_TOKENS = int(os.getenv("CTX_SUMMARY_TRIGGER_TOKENS", "40000"))
# 그래프 단계 한도. 미들웨어 노드 때문에 모델 호출 1회에 약 7단계를 쓴다.
# 모델 호출 한도(20회, ModelCallLimitMiddleware)가 먼저 걸리도록 넉넉히 둔다 (40이면 도구 9회 호출에서 끊긴다)
AGENT_RECURSION_LIMIT = int(os.getenv("AGENT_RECURSION_LIMIT", "200"))

# 웹 질문(/ask)의 근거·실행 기록 보관 기간(일). 서버 시작 때 이보다 오래된 것을 지운다 (메일 기록은 지우지 않는다)
SESSION_EVIDENCE_RETENTION_DAYS = int(os.getenv("SESSION_EVIDENCE_RETENTION_DAYS", "14"))

# ---------- 문의 분석과 절차 초안 (지시서 I, agent/request_analysis.py · agent/skill_author.py) ----------
# 저장된 메일 문의를 답변 뒤에 따로 분석한다 (유형·맡는 절차). 0이면 분석 스레드가 아무것도 하지 않는다
REQUEST_ANALYSIS_ENABLED = os.getenv("REQUEST_ANALYSIS_ENABLED", "1") not in ("0", "false", "False", "")
# 분석 스레드 주기(초)와 한 주기에 분석하는 최대 건수. 대기·처리 중 메일이 있으면 그 주기는 쉰다
REQUEST_ANALYSIS_INTERVAL_SECONDS = float(os.getenv("REQUEST_ANALYSIS_INTERVAL_SECONDS", "30"))
REQUEST_ANALYSIS_BATCH = int(os.getenv("REQUEST_ANALYSIS_BATCH", "5"))
# 분석·초안 생성 모델 호출 1회의 시간 제한(초)
REQUEST_ANALYSIS_TIMEOUT_SECONDS = float(os.getenv("REQUEST_ANALYSIS_TIMEOUT_SECONDS", "120"))
SKILL_DRAFT_TIMEOUT_SECONDS = float(os.getenv("SKILL_DRAFT_TIMEOUT_SECONDS", "300"))
# 절차가 없는 유형의 분석이 이만큼 쌓이면 절차 초안을 자동으로 만든다 (한 유형에 한 번만. 승인은 R&D가 화면에서)
SKILL_DRAFT_MIN_CASES = int(os.getenv("SKILL_DRAFT_MIN_CASES", "3"))
SKILL_DRAFT_AUTO = os.getenv("SKILL_DRAFT_AUTO", "1") not in ("0", "false", "False", "")

# ---------- 기능 끄기 (통합 지시서 0-4. 문제가 생긴 기능만 끌 수 있게, 기본값은 모두 켬) ----------
def _flag(name: str, default: str = "1") -> bool:
    return os.getenv(name, default) not in ("0", "false", "False", "")


# 0이면 사양 도구 4개(list_spec_attributes, search_spec_items, get_specs, compare_specs)가 도구 목록에서 빠진다
SPEC_TOOLS_ENABLED = _flag("SPEC_TOOLS_ENABLED")
# 0이면 사양 DB를 문서 그래프에 심지 않고(seed_specs), 그래프 추출에 사양 DB의 정식 이름을 넘기지 않는다
GRAPH_SPEC_SEED_ENABLED = _flag("GRAPH_SPEC_SEED_ENABLED")
# 0이면 get_customer_history가 도구 목록에서 빠지고, 메일 첫 메시지에 이전 문의·메모 건수 안내 줄을 붙이지 않는다
CUSTOMER_HISTORY_ENABLED = _flag("CUSTOMER_HISTORY_ENABLED")
# 고객 이력에 싣는 문의의 기간(일). 끝난 입찰 조건이 지금 문의에 섞이지 않게 오래된 문의는 뺀다
CUSTOMER_HISTORY_DAYS = int(os.getenv("CUSTOMER_HISTORY_DAYS", "90"))

# ---------- 문서 그래프 (Graph RAG) ----------
# 업로드·페이지 검수 저장 뒤 백그라운드로 개체·관계를 뽑을지 (0이면 끈다. /graph/rebuild로 따로 뽑을 수 있다)
GRAPH_EXTRACT_ENABLED = os.getenv("GRAPH_EXTRACT_ENABLED", "1") not in ("0", "false", "False", "")
# LLM에 넘기는 페이지 텍스트 최대 길이
GRAPH_EXTRACT_MAX_CHARS = int(os.getenv("GRAPH_EXTRACT_MAX_CHARS", "12000"))
GRAPH_EDIT_ENABLED = _flag("GRAPH_EDIT_ENABLED")
# 사양 DB 대조용 이름 키에서 앞에 붙으면 뗄 제조사 이름 (지시서 GR3-4, graph_rag/rules.py). 쉼표로 구분
GRAPH_VENDOR_PREFIXES = tuple(v.strip() for v in os.getenv(
    "GRAPH_VENDOR_PREFIXES",
    "NVIDIA,AMD,Intel,Qualcomm,Samsung,SK hynix,Micron,Kingston,WD,Seagate,Realtek,MediaTek",
).split(",") if v.strip())
GRAPH_EDIT_NAME_LIMIT = int(os.getenv("GRAPH_EDIT_NAME_LIMIT", "100"))
GRAPH_EDIT_TEXT_LIMIT = int(os.getenv("GRAPH_EDIT_TEXT_LIMIT", "4000"))
GRAPH_EDIT_PROPERTY_LIMIT = int(os.getenv("GRAPH_EDIT_PROPERTY_LIMIT", "50"))

# ---------- 로그 ----------
# 로그 파일 폴더 (기본: 프로젝트 루트의 logs/). 상대 경로면 프로젝트 루트 기준.
LOG_DIR = Path(__file__).resolve().parent / os.getenv("LOG_DIR", "logs")
# DEBUG / INFO / WARNING / ERROR
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
# 날짜별로 교체된 로그 파일을 며칠치 남길지
LOG_BACKUP_DAYS = int(os.getenv("LOG_BACKUP_DAYS", "30"))
# DB(access_log)에 남긴 HTTP 접속 기록을 며칠치 보관할지
ACCESS_LOG_RETENTION_DAYS = int(os.getenv("ACCESS_LOG_RETENTION_DAYS", "90"))
