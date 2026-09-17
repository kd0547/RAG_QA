# rag_QA

사내 PDF 문서를 근거로 질문에 답하는 RAG(Retrieval-Augmented Generation) 시스템.
FastAPI 웹 API + LangChain 에이전트 + ChromaDB 벡터 저장소로 구성되며,
Outlook 메일함을 폴링해 문의 메일에 자동 답장하는 배치 루프를 함께 기동한다.

> 이 문서는 리포지토리를 스캔해 **현재 코드에 실제로 구현된 기능**만 정리한 것이다.
> 커밋되지 않은 작업 내용까지 포함해 "지금 어디까지 했는지"를 기준으로 작성했다 (2026-09-17 기준, working tree 스캔).

---

## 지금 진행 중인 작업 (커밋 안 됨)

현재 working tree에 **두 갈래 작업이 동시에 진행 중**이고, 둘 다 미완성 상태다.

### A. 메일 승인 대시보드 백엔드 — 프론트/API 명세는 있음, 백엔드 구현 중

이전 커밋(`88112eb feat(frontend): 메일 전송 승인 대시보드 + API 명세`)에서 프론트엔드(`frontend/src/mail/`)와
[docs/mail_approval_api.md](docs/mail_approval_api.md)(엔드포인트 9개 계약서)를 이미 만들어뒀고,
지금은 그 계약을 만족시키는 **백엔드 구현 중**이다.

이번에 **"기능이 여기저기 흩어져 있다"는 문제 자체를 한 차례 정리**했다 — 같은 역할(메일→태스크 처리)을
하려던 파일이 `app/service/`, `app/controller/`, `mail/`, `tasks/` 네 군데로 나뉘어 있었는데,
계층(Java식 controller/service) 방식과 기능별 패키지(`mail/`, `tasks/`) 방식이 섞여서 생긴 문제였다.
→ **API 라우터(`app/controller/`)만 계층으로 남기고, 실제 로직/데이터 접근은 기능별 패키지(`mail/`, `tasks/`, `repository/`)로 통일**하는 방향으로 맞췄다.

**이번에 정리한 것:**
- 🗑️ `app/service/mail_service.py` 삭제 — `TaskRepository()`를 인자 없이 생성해 바로 깨지던 죽은 코드였고, `tasks/task_service.py`와 역할이 완전히 겹쳤음
- 🔧 `repository/email_repository.py`, `repository/task_repository.py`의 `from repo_connect import Database` 임포트 경로 버그 수정(`repository.repo_connect`로)
- 🔧 `repository/repo_connect.py`의 `SCHEMA_PATH`가 `repository/storage/schema.sql`(존재하지 않는 경로)을 가리키던 버그 수정 → 실제 경로 `storage/schema.sql`로. 이 버그 때문에 `Database()` 생성 시 항상 `FileNotFoundError`가 났었음
- 🔧 `db`/`email_repo`/`task_repo` 싱글턴 생성 위치를 `main.py`에서 [repository/\_\_init\_\_.py](repository/__init__.py)로 이동 — `main.py`는 다시 "앱 조립만" 담당하고, API 라우터(`mail_controller.py`)도 순환 임포트 없이 같은 DB 커넥션/락을 공유해서 쓸 수 있게 함
- 🔧 `app/controller/mail_controller.py`를 `main.py`에 라우터로 등록, 파라미터 기본값을 API 명세(`docs/mail_approval_api.md`)와 맞춤(`status` 기본값 `drafted,in_review,failed` 등). `GET /mails`가 이제 실제로 `200`을 응답함(실제 조회 로직은 아직 스텁이라 빈 목록)

**아직 스텁/미완성으로 남은 것** (이번엔 "정리"만 했고 기능 구현은 안 함, 다음 작업 대상):
- 🚧 `repository/task_repository.py` — `create_task`만 구현. `update_status` / `save_draft` / `view_all` / `get_task_status`는 스텁(`pass`) 또는 파라미터 바인딩·`fetchall`·반환문 누락으로 호출하면 깨짐 → `mail_controller.py`의 `GET /mails`가 실제 데이터를 못 돌려주는 이유
- 🚧 `repository/email_repository.py::get_mail_by_id` — 스텁(`pass`)
- 🚧 `tasks/task_service.py::TaskService.process_task` — 위 스텁들에 의존해 실행 불가. 재시도 카운트 증가 로직도 없음
- ❌ `mail/email_service.py::email_consumer_loop` — 예전 큐 기반 코드 흔적(`mail_queue`, `repo`, `MailStatus`, 정의 안 된 `mail`/`answer` 변수)이 남아있어 스레드 시작 즉시 오류로 죽음. `pending` 태스크를 가져와 `TaskService.process_task()`를 호출하도록 다시 짜야 함 (승인 API가 호출되기 전엔 전송하지 않아야 함, 명세 0번 섹션 참고)
- ❌ `GET /mails`를 제외한 나머지 8개 엔드포인트(`/mails/stats`, `/mails/{uid}`, `PATCH .../draft`, `POST .../approve|reject|claim|release|retry`) 미착수
- ⚠️ `storage/schema.sql`의 `mails` 테이블에 API 명세가 요구하는 `confidence`/`assignee`/`sources`/`model`/`retrieval`/`reviewed_at`/`edited`/`reject_reason` 컬럼이 아직 없음 (마이그레이션 필요, 명세 0번 섹션 표 참고)
- ⚠️ FastAPI에 CORS 미들웨어 미적용 — 프론트(`:5173`)와 연동하려면 `main.py`에 추가해야 함 (명세 상단 코드 참고)

### B. PDF 레이아웃 인식 인제스트 (pymupdf4llm 기반) — 핵심 로직은 동작, 마무리 덜 됨

기존 `pypdf` 단순 텍스트 추출과 별도로, 레이아웃(제목/표/그림/캡션 등)을 보존하고
이미지 안의 텍스트·다이어그램까지 로컬 LLM으로 설명을 붙이는 새 파이프라인이 추가되는 중이다.

- ✅ `rag/type.py` — `pymupdf4llm.to_json()` 스키마를 그대로 반영한 Pydantic 모델(`Box`, `Page`, `Document` 등)
- ✅ `rag/pdf_loader.py::pdf_pages()` — PDF → `Document`(페이지별 박스 + 이미지 파일 추출)
- ✅ `rag/pdf_loader.py::build_page_content()` — 박스 종류별(`text`/`title`/`table`/`picture`/`caption`/`footnote` 등)로 마크다운 텍스트 재조립
- ✅ `rag/image_to_text.py::image_to_text_from_pdf()` — 페이지 내 이미지들을 로컬 LLM(vision)에 태워 OCR/설명 생성 후 `box.image_description`에 채움
- ✅ `rag/ingest.py::ingest_pdf_image()` — 위 파이프라인으로 청킹(기본 `chunk_size=2000`)
- ✅ `app/controller/file_controller.py`의 `/upload`가 기존 `ingest_pdf` 대신 `ingest_pdf_image`를 호출하도록 **임시 교체됨**(코드 주석에 "테스트용으로 교체"라고 명시 — 정식 전환 여부는 아직 결정 안 됨)
- ❌ `ocr/detection_visualizer.py` — **빈 파일**. 박스 탐지 결과 시각화용으로 만든 것으로 보이나 아직 아무 코드도 없음
- ⚠️ `requirements.txt`에 `pymupdf4llm`이 빠져 있음(코드에서는 import함). `msal`, `beautifulsoup4`, `langchain`, `pillow`도 여전히 누락(기존 이슈, 아래 실행 섹션 참고)

### C. `rag/` 구조 검토 결과

`rag/` 폴더를 구조 관점에서 검토한 결과. 이 중 위 두 개는 **이미 수정 완료**, 나머지는 기록만 해둔 상태(다음에 손댈 때 참고).

- ✅ **(수정 완료) `rag/` ↔ `agent/` 양방향 의존** — `set_llm_model`/`get_llm_model`을 `agent/rag_agent.py`에서 분리해 [agent/llm_provider.py](agent/llm_provider.py)라는 중립 모듈로 옮겼다. `agent/rag_agent.py`, [rag/image_to_text.py](rag/image_to_text.py), [rag/pdf_loader.py](rag/pdf_loader.py)(`__main__` 블록), `main.py`, `tests/ingest_pdf_test.py`가 모두 이 새 모듈에서 가져다 쓰도록 변경. 이제 `rag/`가 에이전트 빌드 로직(`create_agent`, `SYSTEM_PROMPT`, 툴 등)을 몰라도 되고, LLM 프로바이더 상태(`_local_llm`/`_claude_llm`)는 한 곳에만 있다
- ✅ **(수정 완료) `Chunk`/`EmbeddedChunk` 중복 선언** — 둘 다 [rag/type.py](rag/type.py)로 옮기고 `EmbeddedChunk(Chunk)`가 상속하도록 바꿨다(`@dataclass(kw_only=True)`로 필드 순서 제약 없이 상속). `rag/ingest.py`, `rag/embedder.py`, `repository/embedding_repository.py`는 이제 `rag.type`에서 임포트. 부수 효과로 `rag/embedder.py`가 `rag/ingest.py`를 몰라도 되게 됐고(타입 때문에만 걸려있던 의존), `embed_chunks()`가 `chunk_type` 필드를 더 이상 누락시키지 않는다. `agent/reranker.py`에 있던 미사용 `EmbeddedChunk`/`Any` 임포트도 같이 정리
- ❌ **버그**: [rag/pdf_loader.py:88](rag/pdf_loader.py:88)과 [92](rag/pdf_loader.py:92)에 `return "\n\n".join(parts)`가 두 번 있음(92번째 줄은 도달 불가능한 죽은 코드)
- ⚠️ **프로덕션 모듈에 개인 테스트 코드**: [rag/pdf_loader.py:101-113](rag/pdf_loader.py:101)의 `__main__` 블록에 로컬 절대경로 하드코딩, [tests/ingest_pdf_test.py](tests/ingest_pdf_test.py)에도 같은 패턴이 중복 존재(둘 다 pytest 아님, 그냥 실행 스크립트). [rag/pdf_loader.py:39](rag/pdf_loader.py:39)에 `print(image_dir_abs)` 디버그 프린트도 남아있음
- ⚠️ **경로 왕복 변환**: [rag/pdf_loader.py:34-43](rag/pdf_loader.py:34) — 절대경로를 만들어놓고 cwd 기준 상대경로로 바꿔 `pymupdf4llm`에 넘긴 뒤, `image_to_text_from_pdf`가 그 상대경로로 다시 파일을 읾음. 서버 실행 위치(cwd)가 바뀌면 깨짐
- ⚠️ **죽은 타입/필드**: `PageImage`([rag/type.py:13](rag/type.py:13))는 import만 되고 어디서도 생성 안 됨. `Chunk.chunk_type`([rag/ingest.py:18](rag/ingest.py:18))은 항상 기본값 `"text"`로 고정, 표/그림 청크 구분 용도로 보이나 채워주는 로직이 없음
- 참고: `ingest_pdf`(단순, pypdf)와 `ingest_pdf_image`(레이아웃, pymupdf4llm)가 나란히 존재하는 건 위 "B" 항목과 동일 — `/upload`가 후자만 쓰므로 전자는 사실상 죽은 코드에 가까움

### 그 외 인프라 변경

- `storage/` 디렉터리 신설 — ChromaDB persist 경로가 `repository/data/` → `storage/chroma/`로, 메일 DB가 `storage/mail.db`로 이동
- `Dockerfile` / `docker-compose.yml` / `.dockerignore` 신규 추가 (단, `CMD`가 아직 `app.main:app`으로 되어 있어 실제 진입점 `main:app`과 안 맞음 — 실행 섹션 참고)
- `.idea/` DataGrip 연결 설정 추가 (`storage/mail.db`용 `identifier.sqlite` 데이터소스 등)

---

## 아키텍처 개요

```
PDF 업로드 ──► 텍스트 추출(pypdf) ──► 청킹 ──► 임베딩(Ollama bge-m3) ──► ChromaDB(persist)
                                                                            │
질문(/ask) ──► RAG 에이전트 ──► search_documents ─┐                          │
                              ├─ rerank_documents │◄── 벡터 검색 ────────────┘
                              └─ check_answerability (로컬 LLM 판단)
                                        │
                                        ▼
                                   근거 기반 답변 + sources

메일 루프(진행중) : POP3 수신(OAuth2) ──► mails/tasks SQLite 저장 ──► [승인 대시보드에서 검토] ──► SMTP 전송

  ※ 위 "승인" 단계는 현재 프론트/API 명세만 있고 백엔드 소비자 루프는 미완성 (자세한 내용은 "지금 진행 중인 작업" 참고)
```

주요 진입점: [main.py](main.py) — FastAPI 앱 조립 + `lifespan`에서 모델 로딩, 에이전트 프리빌드, 메일 루프 기동.

`lifespan` 부팅 순서:
1. `OllamaEmbeddings(model="bge-m3:latest")` 로드 → `set_embedding_model()` 주입
2. `ChatOllama(model="qwen3.8:27b", num_ctx=65536)` 로드 → `set_llm_model()` 주입 (로컬 LLM)
3. `load_rerank()` — CrossEncoder 리랭커 로드
4. `get_agent()` — `claude` 모드 에이전트 1회 빌드 후 캐시
5. `db`/`email_repo`/`task_repo`는 [repository/\_\_init\_\_.py](repository/__init__.py)에서 모듈 최초 임포트 시 한 번만 생성(공유 싱글턴) → `main.py`는 이를 가져다 `email_loop_build(email_repo, task_repo, db)`로 메일 생산자/소비자 스레드 시작
6. 서버 종료 시 `stop_event.set()` 후 스레드 join

> `app/controller/mail_controller.py`(승인 대시보드용 라우터)는 `main.py`에 등록되어 있다(`GET /mails`만 동작, 나머지 8개 엔드포인트는 미착수).

---

## 기능 목록

### 1. PDF 인제스트 파이프라인 (`rag/`)

두 가지 경로가 공존한다 — 단순 텍스트 추출(`ingest_pdf`, 원래 있던 것)과 레이아웃 인식 추출(`ingest_pdf_image`, 진행 중, 현재 `/upload`가 실제로 쓰는 쪽).

| 단계 | 파일 | 내용 |
|------|------|------|
| 텍스트 추출(단순) | [rag/pdf_loader.py](rag/pdf_loader.py) `load_pdf_text()` | `pypdf`로 페이지별(1-based) 텍스트만 추출. 이미지/표 레이아웃은 무시. 파일 없으면 `FileNotFoundError` |
| 텍스트 추출(레이아웃 인식, 진행중) | [rag/pdf_loader.py](rag/pdf_loader.py) `pdf_pages()` / `build_page_content()` | `pymupdf4llm.to_json()`으로 페이지별 박스(제목/본문/표/그림/캡션/각주 등, [rag/type.py](rag/type.py) 참고)를 파싱하고, 그림 박스는 [rag/image_to_text.py](rag/image_to_text.py)의 로컬 vision LLM 호출로 `image_description`을 채운 뒤 순서대로 마크다운 재조립. 이미지 파일은 `data/images/{파일stem}/`에 저장 |
| 청킹 | [rag/chunker.py](rag/chunker.py) | 문자 수 기준 슬라이딩 윈도우 (기본 `chunk_size=1000`, `chunk_overlap=200`; 레이아웃 경로는 `ingest_pdf_image` 기본값 `chunk_size=2000` 사용). 줄바꿈 → 공백 순으로 경계 절단, 경계 없으면 그대로 절단. 항상 전진해 무한 루프 방지 |
| 청크 조립 | [rag/ingest.py](rag/ingest.py) | `ingest_pdf()`(단순) / `ingest_pdf_image()`(레이아웃 인식) 둘 다 페이지 텍스트 → `Chunk` 리스트로 변환. id 규칙: `{파일stem}-p{페이지}-c{인덱스}`. `source`는 파일명 |
| 임베딩 | [rag/embedder.py](rag/embedder.py) | 주입식 임베딩 모델(`set_embedding_model`)로 청크/쿼리 벡터화. `Protocol` 기반 인터페이스, `EmbeddedChunk` 반환. 모델 미주입 시 `RuntimeError` |

### 2. 벡터 저장소 ([repository/embedding_repository.py](repository/embedding_repository.py))

- ChromaDB `PersistentClient`, persist 경로 `storage/chroma/`(기존 `repository/data/`에서 이동), 단일 컬렉션 `rag_chunks`
- `save_embeddings(doc_id, chunks)` — 같은 `source`(doc_id)는 삭제 후 재삽입(업서트). 저장 후 `DATA_DIR` 경로 반환
- `load_embeddings(doc_id)` — 문서 단위 청크 조회(임베딩 포함)
- `list_documents()` — 저장된 `source` 목록 정렬 반환
- `search(query_embedding, top_k=5, doc_id=None)` — 코사인 거리 오름차순 top_k 검색, `doc_id`로 문서 범위 제한. 결과에 `distance`·`embedding` 포함

### 3. HTTP API (`app/controller/`)

| 메서드 & 경로 | 파일 | 설명 |
|---------------|------|------|
| `POST /upload` | [file_controller.py](app/controller/file_controller.py) | PDF 다중 업로드. 파일명 정제(`[^\w.\-]` → `_`, 경로 조작 방지), `.pdf`만 허용, 파일별 실패 격리. `data/uploads/`에 저장 후 인제스트→임베딩→저장. 응답은 청크 미리보기(임베딩 벡터 제외). **현재 `ingest_pdf_image`(레이아웃 인식 경로)를 임시로 사용 중**(코드 주석 "테스트용으로 교체") |
| `GET /search` | [search_controller.py](app/controller/search_controller.py) | 쿼리 문자열 유사도 검색. `q`(필수), `top_k`(1~50, 기본 5), `doc_id`(선택). 임베딩 모델 미로드 시 503 |
| `POST /ask` | [question_controller.py](app/controller/question_controller.py) | RAG 에이전트 질의. body: `question`, `mode`(`claude`\|`local`, 기본 `claude`), `rerank_top_n`·`query_top_n`(**필수 int, 현재 미사용** — 프롬프트 주입 코드는 주석 처리됨). 응답: `question`, `answer`, `sources`(source/page/text) |
| `GET /` | [main.py](main.py) | `static/index.html` 서빙 + `/static` 정적 마운트 (※ 현재 리포에 `static/` 디렉터리 없음 → 실행 시 해당 경로 준비 필요) |

### 4. RAG 에이전트 ([agent/rag_agent.py](agent/rag_agent.py))

LangChain `create_agent` 기반. 시스템 프롬프트로 아래 절차를 강제한다.

- **툴**
  - `search_documents(query, top_k=5)` — 임베딩 후 벡터 검색. 표현을 바꿔 반복 호출해 커버리지 확대 유도
  - `rerank_documents(query, documents, top_n=3)` — CrossEncoder 재정렬 ([agent/reranker.py](agent/reranker.py), `BAAI/bge-reranker-v2-m3`, `max_length=512`). 모델 미로드 시 빈 리스트 반환(`rerank()` 자체 기본값은 `top_n=5`)
  - `check_answerability(question, documents)` — **답변 작성 전 필수**. `AnswerabilityCheck`(`is_answerable`, `reason`) 구조화 출력으로 검색 문서만으로 답 가능한지 판정. 불가 시 재검색(최대 2회), 그래도 불가면 "관련 정보를 찾지 못했습니다"로 짧게 응답. **판정은 항상 로컬 Ollama 모델로 고정**(`mode`가 `claude`여도 answerability 체크에는 Ollama 필요)
- **모드 전환** — `local`: 주입된 `ChatOllama` / `claude`: `ChatAnthropic("claude-sonnet-5")` (최초 사용 시 지연 초기화)
- **재사용** — `get_agent(mode)`가 모드별 에이전트를 1회 빌드 후 `_agents` 딕셔너리에 캐시
- **실행** — `run_agent(question, mode="claude")`, `recursion_limit=15`. 전체 메시지 흐름을 stdout으로 덤프
- **응답 가공** — 최종 메시지를 `answer`로, `search_documents`/`rerank_documents` 툴 결과(list)를 모아 `sources`로 반환
- 역할 설명·인사말·메타 코멘트 금지, 문서 밖 내용 금지 규칙 포함

### 5. 메일 자동 응답 루프 (`mail/`, `tasks/`, `repository/`) — 승인 워크플로우로 리팩터링 진행 중

기존에는 "수신 → 에이전트 실행 → 즉시 자동 회신"이었으나, 지금은 **회신 전에 사람이 승인하는 단계**를 넣기 위해
`mails`(수신 사실) / `tasks`(처리 상태) 2테이블 구조로 바꾸는 중이다. 상세 미완성 지점은 위 "지금 진행 중인 작업 → A" 참고.

| 구성 | 파일 | 상태 |
|------|------|------|
| 수신 | [mail/email_receiver.py](mail/email_receiver.py) | ✅ 동작. Outlook/O365 POP3(SSL, `outlook.office365.com:995`). MSAL `PublicClientApplication`으로 OAuth2 `XOAUTH2` 인증, 토큰 캐시(`storage/token_cache.bin`, 최초 1회 브라우저 로그인). UIDL로 미처리 메일만 수집, MIME 헤더 디코딩, 발신자 주소 `parseaddr` 추출, `text/plain` 우선(없으면 BeautifulSoup로 HTML→텍스트) |
| 생산자 루프 | [mail/email_service.py](mail/email_service.py) `email_receiver_loop` | ✅ 동작. 60초 주기(`stop_event.wait(60)`)로 미처리 메일만 가져와 `intake_mail()`로 `mails`+`tasks` 테이블에 트랜잭션 insert(`status=pending`) |
| 소비자 루프 | [mail/email_service.py](mail/email_service.py) `email_consumer_loop` | ❌ 미완성. 예전 큐 기반 코드 잔재가 섞여 있어 스레드 시작 즉시 오류로 죽음. `pending` 태스크를 가져와 `TaskService.process_task()`를 호출하고, 승인 API가 호출되기 전까지는 전송하지 않도록 다시 짜야 함 |
| 태스크 처리 | [tasks/task_service.py](tasks/task_service.py) `TaskService.process_task` | 🚧 `run_agent()`로 초안 생성까지는 짜여 있으나, 의존하는 `EmailRepository.get_mail_by_id` / `TaskRepository.save_draft`가 스텁이라 실행 불가 |
| 발신 | [mail/email_send.py](mail/email_send.py) | ✅ 동작 (호출부만 아직 승인 API에 연결 안 됨). Outlook SMTP(`outlook.office365.com:587`, STARTTLS), `MAIL_ID`/`MAIL_PW` 로그인, `MIMEMultipart` + plain text |
| 메일 상태 저장소 | [repository/email_repository.py](repository/email_repository.py) | 🚧 `save_pending`/`get_processed_uids`만 구현, `get_mail_by_id` 스텁 |
| 태스크 상태 저장소 | [repository/task_repository.py](repository/task_repository.py) | 🚧 `create_task`만 구현, 나머지(`update_status`/`save_draft`/`view_all`/`get_task_status`) 스텁·미완성 |
| DB 연결/스키마/조립 | [repository/repo_connect.py](repository/repo_connect.py) + [repository/\_\_init\_\_.py](repository/__init__.py) + [storage/schema.sql](storage/schema.sql) | ✅ `Database` 클래스(스레드 락 + `with db.transaction() as conn`) 골격 완성. `db`/`email_repo`/`task_repo` 싱글턴은 `repository/__init__.py`에서 한 번만 생성해 `main.py`와 `mail_controller.py`가 공유(락 분리 방지). 단 `mails` 테이블에 승인 대시보드가 요구하는 컬럼(`confidence`/`assignee`/`sources`/`model`/`retrieval`/`reviewed_at`/`edited`/`reject_reason`)이 아직 없음 |

태스크 상태(`TaskStatus`, [entity/type.py](entity/type.py)): `pending` · `drafted` · `in_review` · `rejected` · `approved` · `sent` · `failed`
(목표 흐름: `pending`(수신) → `drafted`(AI 초안) → `in_review`(담당자 검토, 선택) → `approved`/`rejected` → `sent`/`failed`. 현재는 소비자 루프가 깨져 있어 `pending`에서 더 진행되지 않음)

### 6. 메일 승인 대시보드 — 프론트엔드/API 명세 (백엔드 연결 전)

- `frontend/src/mail/` — `#/mail` 해시 라우트로 붙는 승인 대시보드 화면(`MailApprovalDashboard.tsx`). 요약 타일, 최근 14일 전송량 스파크라인(`Sparkline.tsx`), 필터·검색 대기열 표, 상세 검토 드로어(승인/반려/초안 수정/담당 지정/재전송) 포함. 백엔드 미응답 시 `mockData.ts`로 자동 폴백하고 "예시 데이터" 배지 표시
- [docs/mail_approval_api.md](docs/mail_approval_api.md) — 프론트가 기대하는 9개 엔드포인트 계약서(`GET /mails`, `GET /mails/stats`, `GET /mails/{uid}`, `PATCH /mails/{uid}/draft`, `POST /mails/{uid}/approve|reject|claim|release|retry`). **`GET /mails`만 라우팅·응답 형식이 맞춰져 있고(실데이터는 아직 빈 목록), 나머지 8개는 미착수** — 위 "지금 진행 중인 작업 → A" 참고

### 7. 부수 유틸리티 / 별도 프로젝트

- [image_metadata.py](image_metadata.py) — PNG/WebP/JPEG의 기본 정보·EXIF·XMP·AI 생성 메타데이터(`parameters`, `prompt`, `workflow` 등) 덤프 스크립트. 본 RAG 파이프라인과 독립. **현재 `IMAGE_PATH` 하드코딩 + `SHOW_RAW=True`인 디버그 상태**이며 `sys.argv` 파싱은 주석 처리됨
- [ocr/detection_visualizer.py](ocr/detection_visualizer.py) — **빈 파일**. 레이아웃 박스 탐지 결과 시각화용으로 만든 것으로 보이나 아직 코드 없음
- `frontend/` — React 19 + Vite + Tailwind v4 기반 앱. 원래 있던 OCR 결과 뷰어/에디터(`tg-ocr-api`, 루트 라우트)에 위 메일 승인 대시보드(`#/mail`)가 새로 추가됨
- `models/` — 빈 플레이스홀더 디렉터리

---

## 실행

### 사전 요구
- Python 3.11
- 로컬 [Ollama](https://ollama.com)
  - 임베딩: `bge-m3:latest`
  - 로컬 LLM: `qwen3.8:27b` (`main.py` lifespan에서 로딩) — `claude` 모드로만 쓰더라도 `check_answerability`가 Ollama를 사용하므로 필요
- `.env` 파일

```
ANTHROPIC_API_KEY=...     # claude 모드 에이전트용
CLIENT_ID=...             # Azure 앱 등록 (메일 POP3 OAuth2)
TENANT_ID=...
MAIL_ID=...               # Outlook 계정 (POP3 수신 대상 / SMTP 발신자)
MAIL_PW=...               # SMTP 발신용 비밀번호
```

### 로컬 실행

```bash
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

> `requirements.txt`에는 직접 임포트하는 일부 패키지(`langchain`, `msal`, `beautifulsoup4`, `pillow`, `python-dateutil`, **`pymupdf4llm`**)가 빠져 있어 환경에 따라 추가 설치가 필요할 수 있다.
> Dockerfile에는 `app.main:app` 경로가 남아 있으나 현재 진입점은 리포 루트의 `main.py`이므로 `main:app`을 사용한다.
> `GET /` 응답을 위해 `static/index.html`이 필요하다(현재 리포에는 없음).

### Docker

```bash
docker compose up --build
```

[Dockerfile](Dockerfile) / [docker-compose.yml](docker-compose.yml)이 새로 추가됐지만 아직 최신 경로 구조와 안 맞다:

- `docker-compose.yml`의 볼륨이 `./chroma_data → /repository/data/`로 되어 있으나, 실제 ChromaDB persist 경로는 `storage/chroma/`로 이동함 → 볼륨 경로 수정 필요
- `Dockerfile`의 `CMD`가 `uvicorn app.main:app ...`로 되어 있어 현재 구조(`main:app`)와 맞지 않음 → 수정 필요
- 포트 `8000:8000`, `OLLAMA_BASE_URL=http://host.docker.internal:11434`(호스트 Ollama 사용)는 그대로 유효

---

## 기술 스택

FastAPI · Uvicorn · LangChain (`create_agent`) / LangGraph · ChromaDB ·
Ollama (`langchain-ollama`, bge-m3 임베딩 + qwen3 LLM, 이미지 캡셔닝용 vision 호출 포함) · Anthropic Claude (`langchain-anthropic`, claude-sonnet-5) ·
sentence-transformers CrossEncoder 리랭커(bge-reranker-v2-m3) · pypdf · pymupdf4llm(레이아웃 인식 PDF 파싱, 진행중) ·
MSAL(OAuth2) · poplib / smtplib · BeautifulSoup · SQLite ·
React 19 + Vite + Tailwind v4 (frontend: OCR 뷰어 + 메일 승인 대시보드)
