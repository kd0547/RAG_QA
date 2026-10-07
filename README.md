# rag_QA

사내 PDF를 인덱싱해 문서 근거로 답하는 RAG 웹 앱입니다. FastAPI, React/Vite, ChromaDB, SQLite를 사용하며 Outlook 메일 수신과 답변 초안 생성, 승인 후 발송 흐름을 개발 중입니다.

> **진행 현황 기준: 2026-09-29 작업 트리의 소스 코드.** 아래 상태는 코드와 프론트엔드 호출을 대조한 결과이며, 외부 LLM·메일 서버를 연결한 종단 간 동작을 보증하지 않습니다. 커밋되지 않은 변경도 포함합니다.

## 현재 진행 현황

| 영역 | 현재 구현 | 남은 작업 / 확인된 문제 |
| --- | --- | --- |
| PDF 인제스트와 검색 | `/upload`가 `pymupdf4llm` 레이아웃 추출 → 이미지 설명 → 청킹 → Ollama 임베딩 → Chroma 저장을 호출합니다. `/search`와 `/ask` 라우트가 있습니다. | 이미지 설명과 질의에는 별도 LLM 서버가 필요합니다. 업로드 중복·실패 처리와 실제 질의 결과는 종단 간 검증이 필요합니다. |
| 파일 관리 | SQLite `file` 테이블, `GET /files`, `DELETE /file/{file_id}`, 프론트 문서 목록과 삭제 버튼이 추가됐습니다. Chroma 청크에 `file_id`를 저장하고 삭제 시 해당 임베딩을 지웁니다. | 삭제 API는 업로드한 원본 PDF를 지우지 않습니다. 중복 업로드는 파일을 먼저 덮어쓴 뒤 응답 항목 없이 건너뜁니다. 파일 행과 벡터 저장은 한 트랜잭션이 아닙니다. |
| 메일 수신과 초안 | POP3 수신 메일을 `mails`/`tasks`에 저장합니다. 소비자 루프는 `pending` 태스크를 조회해 로컬 LLM으로 초안을 생성하고, 지정된 담당자에게 검토 요청 메일을 보낸 뒤 `drafted`로 저장하는 코드가 있습니다. | 실서버 검증 전입니다. 빈 본문 태스크는 `pending`에 남고, 오류는 `failed`가 됩니다. 재시도 횟수 증가와 반려 후 재작성은 연결되지 않았습니다. |
| 메일 승인 API | `GET /mails`는 메일과 태스크를 조인해 `task_id`를 포함한 목록의 핵심 5개 필드를 반환합니다. `GET /mails/{task_id}`는 해당 태스크의 원문·상태·초안을 조회합니다. `POST /mails/{task_id}/approve`는 저장된 초안을 SMTP 발송합니다. | 목록 검색·정렬·페이지네이션은 미구현입니다. 상세 응답의 모델·검색 정보·근거는 아직 저장되지 않아 빈 값입니다. 통계·초안 수정·반려·담당 지정/해제·재시도 API는 없습니다. |
| 웹 UI | `/` RAG 콘솔에 PDF 업로드, 파일 목록/삭제, 질의 화면이 있고 `/mail` 승인 대시보드, `/ocr` OCR 화면이 있습니다. History API 경로 라우팅과 기존 `#/mail` 등의 링크 변환이 구현됐습니다. | `/mail`은 API 오류 시 예시 데이터로 전환합니다. 화면의 여러 승인 동작은 백엔드가 미구현이거나 계약이 맞지 않아 실제 워크플로우로 사용할 수 없습니다. `/ocr`은 별도 OCR 서버가 필요합니다. |
| 배포와 의존성 | Dockerfile과 Compose 파일이 있습니다. | Docker 진입점과 볼륨 경로가 현재 코드와 맞지 않습니다. `requirements.txt`에 직접 사용하는 일부 패키지가 빠져 있습니다. |

### README와 코드 사이에서 바뀐 점

- 메일 소비자 루프는 예전 큐 기반 코드에서 `get_pending_tasks()` 조회 방식으로 바뀌었습니다. `get_mail_by_id()`, `update_status()`, `save_draft()`, `assign_task()`도 구현됐습니다. 다만 이 경로가 실제 환경에서 정상 작동하는지는 확인되지 않았습니다.
- `POST /mails/{task_id}/approve`가 새로 추가됐습니다. 식별자는 프론트와 `task_id`로 통일됐지만 요청 본문과 응답 계약은 아직 맞지 않습니다.
- 파일 메타데이터용 `file` 테이블과 목록·삭제 API가 추가됐습니다. 기존 README의 “원본도 삭제” 또는 “같은 문서 재업로드 시 자동 교체” 설명은 현재 구현과 맞지 않습니다.
- 로컬 모드 LLM은 현재 `main.py`에서 OpenAI 호환 `ChatOpenAI(model="qwen3.8-flash-next", base_url="http://14.38.199.190:9090/v1")`로 설정합니다. 임베딩은 여전히 Ollama `bge-m3:latest`를 사용합니다. Claude 모드는 `ChatAnthropic(model="claude-sonnet-5")`입니다.
- 이전 README가 가리키던 `docs/mail_approval_api.md`는 현재 작업 트리에 없습니다. 프론트가 기대하는 요청·응답은 `frontend/src/mail/api.ts`와 `frontend/src/mail/types.ts`에서 확인할 수 있습니다.

## 구성과 데이터 흐름

```text
PDF 업로드 ──► 레이아웃/이미지 추출 ──► 청킹 ──► Ollama 임베딩 ──► ChromaDB
     └──────► SQLite file 메타데이터                         │
질문(/ask) ──► RAG 에이전트 ──► 검색·선택적 리랭킹·답변 가능성 확인 ──► 답변/근거

POP3 수신 ──► SQLite mails/tasks ──► pending 태스크의 AI 초안
                                      └──► 담당자 검토 요청 메일
승인 API ──► SMTP 전송 (프론트 연동과 나머지 승인 동작은 미완성)
```

- 진입점 `main.py`: FastAPI 라우터 등록, 프론트 빌드 서빙, 모델 초기화와 메일 생산자/소비자 스레드 시작.
- `retrieval/`: `pypdf` 기반 단순 경로(`ingest_pdf`)와 현재 `/upload`가 호출하는 `pymupdf4llm` 경로(`ingest_pdf_image`)가 공존합니다. 후자는 박스 유형별 텍스트를 조립하고 그림을 LLM으로 설명합니다.
- `repository/embedding_repository.py`: `storage/chroma/`의 `rag_chunks` 컬렉션 사용. 검색은 `source` 기준 `doc_id` 필터를 지원하며, 파일 삭제는 `file_id` 기준입니다.
- `agent/`: 검색, CrossEncoder 리랭킹(`BAAI/bge-reranker-v2-m3`), 로컬 LLM의 답변 가능성 확인 도구를 묶은 LangChain 에이전트. 프롬프트가 도구 사용을 지시합니다.
- `mail/`, `tasks/`, `repository/`: 메일 수신·초안·발신, SQLite 상태 저장. `repository/__init__.py`가 DB와 저장소 인스턴스를 공유합니다.
- `frontend/`: React 19, Vite, Tailwind v4. `/` RAG 콘솔, `/mail` 승인 대시보드, `/ocr` 별도 OCR 도구.

## HTTP API 상태

| 메서드·경로 | 코드 기준 상태 |
| --- | --- |
| `POST /upload` | 여러 PDF를 처리해 청크 미리보기 반환. 현재 레이아웃 인제스트 사용. 파일별 파싱·임베딩 예외는 응답의 `error`로 기록. |
| `GET /files` | SQLite에 기록된 `file_id`, `original_name` 목록 반환. |
| `DELETE /file/{file_id}` | SQLite 행과 Chroma 임베딩 삭제. 원본 파일은 보존. |
| `GET /search` | 쿼리 임베딩으로 Chroma 검색. `q`, `top_k`, `doc_id` 지원. |
| `POST /ask` | `question`, `mode`(`claude`/`local`), 필수 `query_top_n`·`rerank_top_n` 수신. 마지막 두 값은 현재 사용하지 않음. |
| `GET /mails` | 상태 필터에 맞는 메일 태스크 목록을 조회. 핵심 5개 필드(`task_id`, `subject`, `sender`, `received_at`, `status`) 반환. 검색·정렬·페이지네이션은 미구현. |
| `GET /mails/{task_id}` | 해당 태스크의 메일 원문·상태·초안 조회. 없는 task_id는 404. 저장되지 않는 모델·검색·근거 정보는 빈 값. |
| `POST /mails/{task_id}/approve` | `drafted` 태스크의 저장된 초안을 SMTP 전송하고 `sent`/`failed`로 변경. 프론트 요청 본문과는 아직 불일치. |
| 메일 통계·초안 수정·반려·담당 지정/해제·재시도 | 프론트 호출만 있으며 백엔드 라우트 없음. |

## 실행

### 필요한 서비스와 설정

- Python 3.11, Node.js/npm.
- Ollama 임베딩 모델 `bge-m3:latest`.
- `main.py`에 설정된 OpenAI 호환 LLM 서버(`qwen3.8-flash-next`, `http://14.38.199.190:9090/v1`). PDF 그림 설명, 메일 초안, 답변 가능성 확인, `/ask`의 `local` 모드가 이 설정을 사용합니다. 주소는 현재 코드에 고정돼 있습니다.
- Claude 모드용 `ANTHROPIC_API_KEY`.
- 메일 사용 시 `.env`에 `CLIENT_ID`, `TENANT_ID`, `MAIL_ID`, `MAIL_PW`. POP3 수신에는 MSAL OAuth2, 발신에는 SMTP 로그인을 사용합니다. `main.py` 실행 시 메일 루프도 시작됩니다.

### 로컬 구동 명령어 (PowerShell)

프로젝트 루트에서 **첫 번째 터미널**을 열고 백엔드를 실행합니다. 가상환경을 활성화하지 않고 그 안의 Python을 직접 호출합니다.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install langchain msal beautifulsoup4 pymupdf4llm
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

직접 임포트하는 `langchain`, `msal`, `beautifulsoup4`, `pymupdf4llm`은 현재 `requirements.txt`에 없어 별도 설치 명령에 포함했습니다. 실행 전에 위의 Ollama·LLM 서버와 `.env` 메일 설정이 필요합니다. 서버 시작 시 메일 루프도 실행됩니다.

프로젝트 루트에서 **두 번째 터미널**을 열고 프론트 개발 서버를 실행합니다.

```powershell
cd frontend
npm ci
npm run dev
```

브라우저에서 `http://localhost:5173/`(RAG 콘솔), `http://localhost:5173/mail`(메일 대시보드)을 엽니다. 백엔드 API 문서는 `http://127.0.0.1:8000/docs`에서 볼 수 있습니다.

Vite는 `/upload`, `/files`, `/file/`, `/ask`, `/search`, `/mails`를 기본 `127.0.0.1:8000`으로 프록시합니다. 다른 백엔드 주소는 `VITE_PROXY_TARGET`으로 설정합니다. API 요청의 기본 URL은 same-origin이며 `VITE_API_BASE`로 변경할 수 있습니다. `npm run build`로 생성한 `frontend/dist`가 있으면 FastAPI가 `/`, `/mail`, `/ocr`에서 SPA를 서빙합니다. 빌드가 없으면 `/`에서 안내 JSON을 반환합니다.

### Docker 현황

현재 `Dockerfile`의 `uvicorn app.main:app`은 실제 진입점 `main:app`과 다릅니다. `docker-compose.yml`의 Chroma 볼륨도 실제 `storage/chroma/`와 맞지 않습니다. 컨테이너 실행은 이 경로들과 누락 의존성을 정리한 뒤 검증해야 합니다.

## 우선 해결할 항목

1. 메일 목록 조회에 메일 원문 정보를 결합하고 응답을 프론트 타입에 맞춰 구현.
2. 메일 승인 API의 남은 요청·응답 계약을 통일하고 통계·수정·반려·담당·재시도 라우트 구현.
3. 중복 업로드, 원본 삭제, SQLite·Chroma 저장의 실패 처리 정리.
4. 런타임 의존성, LLM 서버 설정, Docker 경로를 정리하고 실제 PDF·질의·메일 흐름 검증.

`tests/test_mail_list.py`는 임시 SQLite DB로 메일 목록의 상태 필터와 상세 조회·404를 확인합니다. 실행에는 `pytest`와 FastAPI `TestClient`용 `httpx`가 필요합니다. 외부 서비스까지 포함한 종단 간 테스트는 확인되지 않았습니다.
