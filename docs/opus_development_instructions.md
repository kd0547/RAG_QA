# Opus 개발 지시서 — rag_QA 에이전트 고도화 (멀티턴 우선)

작성일: 2026-11-12
대상: 구현 담당 에이전트(Opus)
설계 원천: [agent_review_total_2026-11-12.md](agent_review_total_2026-11-12.md) (6장 결정표 Q1~Q14, 11-1 최소 계약, 11-5 SMTP 분기, 12장 최종 합의)
검증: 각 단계가 끝나면 Gemini가 [gemini_verification_instructions.md](gemini_verification_instructions.md)의 B 절로 검증한다. 구현자는 자기 검증 결과를 "보고 형식"으로 남기고, Gemini 판정을 기다린다.

---

## 0. 작업 규칙

1. **범위**: 이 문서의 단계 A → B → C 순서로만 진행한다. D~H는 C가 Gemini 검증을 통과한 뒤 별도 지시로 시작한다. 지시에 없는 리팩터링·이름 변경·파일 이동은 하지 않는다.
2. **커밋**: 각 항목(A1, A2, …) 시작 전에 작업 트리가 깨끗한지 확인하고, 항목 하나가 끝날 때마다 커밋 1개. 메시지는 저장소 관례 `feat(scope): 한국어 요약` / `fix(scope): …`. 끝에 `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`가 아니라 **구현 모델의 attribution**을 쓴다.
3. **금지**
   - 메일을 실제로 보내지 않는다. `send_email`·승인 API는 테스트에서 대역(mock)으로만 호출한다.
   - 운영 DB(`storage/mail.db`)에 쓰지 않는다. 테스트는 `tests/test_mail_list.py`의 `mail_data` 픽스처처럼 임시 DB로 격리한다.
   - `file_page`·원본 파일을 에이전트 도구가 쓰지 못하게 한다. 쓰기 도구는 만들지 않는다.
   - `check_answerability`를 **대체 경로가 동작하기 전에** 지우지 않는다 (Q5).
   - 자동 재발송 코드를 넣지 않는다 (Q1).
   - 프롬프트 수정만으로 문제를 "해결"하지 않는다. 수치 제한·검증은 서버 코드로 강제한다.
   - 질의 시점에 원본을 재파싱하는 fallback을 넣지 않는다 (Q10).
4. **테스트**: 항목마다 `tests/`에 pytest를 추가한다. LLM은 `langchain_core.language_models.fake_chat_models.GenericFakeChatModel` 또는 직접 만든 대역으로 대체한다. 실행은 `.venv/Scripts/python.exe -m pytest tests -q`.
5. **보고**: 항목이 끝날 때마다 `docs/dev_log/<단계>-<항목>.md`에 변경 파일, 결정 사항, 테스트 명령과 출력, 확인 못 한 것을 적는다. Gemini가 이것을 읽는다.
6. **언어**: 코드 주석·커밋·보고는 한국어. 기존 코드 스타일(docstring 한국어, 로그 메시지 한국어)을 따른다.

---

## 1. 환경 사실 (구현 전에 알고 있어야 할 것)

| 항목 | 값 |
|------|----|
| Python 가상환경 | `.venv/Scripts/python.exe` (Windows) |
| 핵심 패키지 | langchain 1.3.14, langchain-core 1.6.4, langgraph 1.2.9, langgraph-checkpoint 4.1.1, langchain-openai 1.6.3 |
| 미설치 (단계 C에서 설치) | `langgraph-checkpoint-sqlite` (3.1.3 사용 가능) |
| 설치하지 않음 | `deepagents` (단계 F에서 별도 결정) |
| 내장 미들웨어 | `langchain.agents.middleware`: `SummarizationMiddleware`, `ContextEditingMiddleware`, `ClearToolUsesEdit`, `ToolCallLimitMiddleware`, `ModelCallLimitMiddleware`, `TodoListMiddleware`, `HumanInTheLoopMiddleware` |
| LLM | 로컬 vLLM(`config.LLM_MODEL=qwen3.8-flash-next`, OpenAI 호환), Claude는 키가 있을 때만. **메일 처리는 항상 `mode="local"`** |
| DB | SQLite `storage/mail.db`. 스키마는 `storage/schema.sql`(CREATE IF NOT EXISTS) + `repository/repo_connect._migrate`(ALTER). 새 테이블은 schema.sql에, 기존 테이블의 새 컬럼은 `_migrate`에 |
| 에이전트 | `agent/agent.py` `build_agent` → `langchain.agents.create_agent(model, tools, middleware=[_system_prompt], context_schema=AgentContext)`. checkpointer 없음 |
| 도구 | `tools/tool.py`: `search_documents`, `rerank_documents`, `check_answerability`, `graph_search`, `read_source_document` |
| 메일 루프 | `mail/email_service.py`: receiver 스레드(60초) + consumer 스레드(10초). 단일 프로세스 |
| 로컬 DB 상태 | `file` 1건, `file_page` 1건, `product_component` 0건. 기준선 문서 17개는 개발 서버에만 있음 |
| 프론트 | `frontend/src/mail/` (React, TS). 상태 타입 `types.ts` `MailStatus` |

---

## 2. 공통 설계 계약 (모든 단계가 따른다)

### 2-1. 작업 상태 (entity/type.py `TaskStatus`)

```text
pending → processing → drafted → sending → sent
                     ↘ failed              ↘ send_failed   (담당자 재승인 가능)
                                           ↘ send_unknown  (담당자 확인 후 sent 처리 또는 재승인)
drafted → rejected → pending  (requeue 반려, 기존 그대로)
```

- 추가: `PROCESSING="processing"`, `SENDING="sending"`, `SEND_FAILED="send_failed"`, `SEND_UNKNOWN="send_unknown"`
- `FAILED`는 답변 생성 실패 전용으로 남긴다. 발송 실패에 쓰지 않는다.
- 프로세스 시작 시 `processing` → `pending`으로 되돌린다. `sending`은 되돌리지 않는다.
- 프론트 `MailStatus`에 같은 값을 추가하고 목록 필터·배지에 반영한다.

### 2-2. 발송 결과 (mail/email_send.py)

`send_email`은 예외를 삼키지 않고 **결과를 돌려준다**.

```python
class SendOutcome(Enum): SENT="sent"; FAILED="send_failed"; UNKNOWN="send_unknown"

@dataclass
class SendResult:
    outcome: SendOutcome
    detail: str            # SMTP 응답 코드·예외 이름
    cleanup_warning: str | None = None   # 수락 뒤 quit 실패 등

def send_email(...) -> SendResult
```

분기 기준은 **수락 확인 여부**다 (total 11-5).

| 단계 | 예외/응답 | outcome |
|------|-----------|---------|
| connect / ehlo / starttls / login | 어떤 예외든 | FAILED |
| `server.mail()`, `server.rcpt()` | 비정상 코드 또는 예외 | FAILED |
| `server.data(bytes)` | 예외(`SMTPServerDisconnected`, timeout, OSError) | **UNKNOWN** |
| `server.data(bytes)` | 반환 코드 ≠ 250 | FAILED |
| `server.data(bytes)` | 250 | SENT |
| 이후 `quit()` | 예외 | SENT 유지 + `cleanup_warning` |

구현은 `send_message` 대신 `mail`/`rcpt`/`data`를 직접 호출한다. 테스트는 `smtplib.SMTP`를 대역으로 바꿔 세 outcome을 각각 재현한다.

### 2-3. 근거(evidence) 스키마 (단계 B에서 생성)

```sql
CREATE TABLE IF NOT EXISTS evidence (
  evidence_id   TEXT PRIMARY KEY,          -- 'e' + 짧은 uuid
  owner_type    TEXT NOT NULL,             -- 'task' | 'session'
  owner_id      TEXT NOT NULL,
  origin_type   TEXT NOT NULL,             -- 'file_page' | 'chunk' | 'attachment' | 'spec_value'
  file_id       TEXT, page_id INTEGER, page INTEGER,
  attachment_id INTEGER, spec_value_id INTEGER,
  revision      TEXT,                      -- file_page.updated_at 또는 첨부 파서 버전
  content_hash  TEXT NOT NULL,
  text          TEXT NOT NULL,
  created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evidence_owner ON evidence(owner_type, owner_id);

CREATE TABLE IF NOT EXISTS run (
  run_id TEXT PRIMARY KEY, owner_type TEXT NOT NULL, owner_id TEXT NOT NULL,
  model TEXT, prompt_id INTEGER, started_at TEXT NOT NULL, ended_at TEXT,
  status TEXT NOT NULL,                    -- 'ok' | 'error' | 'limit'
  tool_calls_json TEXT, tokens_in INTEGER, tokens_out INTEGER, error TEXT
);

CREATE TABLE IF NOT EXISTS evidence_use (
  run_id TEXT NOT NULL, evidence_id TEXT NOT NULL,
  action TEXT NOT NULL,                    -- 'read' | 'rerank' | 'cite'
  at TEXT NOT NULL
);
```

- 같은 (owner, origin, file_id, page_id, revision)이면 새 행을 만들지 않고 기존 `evidence_id`를 돌려준다.
- 다른 owner의 `evidence_id`를 인용하면 서버 검증이 거부한다.
- 그래프 검색 결과는 evidence가 아니다 (trace에만 남긴다).

### 2-4. 도구 계약 (단계 B에서 교체)

| 도구 | 시그니처 | 반환 |
|------|----------|------|
| `list_documents` | `(group_id: str\|None=None, keyword: str\|None=None, limit: int=50)` | `[{file_id, original_name, group_id, description, has_pages, page_count}]` |
| `grep_documents` | `(pattern: str, file_id: str\|None=None, limit: int=20)` | `[{file_id, original_name, page, snippet}]`. `file_page.text` 대상. 정규식은 Python `re`, 대소문자 무시 |
| `read_pages` | `(file_id: str, pages: list[int], max_chars: int=6000)` | 페이지마다 `{evidence_id, page, text}`. 합계 `max_chars` 초과분은 `truncated=True`와 다음 페이지 안내. 페이지 없으면 `{"error": "페이지 텍스트 없음 …"}` 반환, 파싱하지 않음 |
| `search_documents` | 기존 인자 유지 | 항목에 `text` 대신 `snippet`(300자) + `evidence_id` |
| `rerank_documents` | `(query: str, evidence_ids: list[str], top_n: int=3)` | 정렬된 `evidence_ids` |
| `read_attachment` | `(attachment_id: int, pages: list[int]\|None=None, max_chars: int=6000)` | `read_pages`와 같은 형식. 현재 task의 첨부만 허용 |
| `list_evidence` | `()` | 현재 owner의 evidence 한 줄씩: `e12 | 파일명 p3 | rev … | 앞 60자` |
| `graph_search` | 기존 유지 | `documents[*]`에 `file_id` 포함 확인 (이미 있음) |

`read_source_document`는 B 완료 후 제거한다. `check_answerability`는 B-6 서버 검증이 동작한 뒤 제거한다.

### 2-5. 최종 답변 형식

시스템 프롬프트(새 버전)에서 답변 마지막 줄을 다음으로 고정한다.

```text
근거: e12, e15
```

문서에서 찾지 못했으면 `근거: 없음`. 서버가 이 줄을 파싱해 `evidence_use(action='cite')`에 기록하고 본문에서는 제거한다.

---

## 3. 단계 A — 0단계 결함 수정

### A1. 메일 상세 출처 복구

- 파일: `app/routers/mails.py` `view_mail_detail`, `tests/test_mail_list.py`
- 할 일: 주석 처리된 `sources` 조립을 살린다. `task_repo.get_sources(task_id)` 결과를 `{"source": 파일명(경로 아님), "page", "text"}`로 돌려준다. 디스크 경로는 내보내지 않는다 (`Path(s["source"]).name`).
- 테스트: 픽스처에서 `save_draft(..., sources=[...])`로 출처를 넣고 `sources` 길이·필드를 검사. 기존 `== []` 기대는 삭제.
- 완료: Gemini B-A "출처 복구".

### A2. 출처 수집 통일·2중 적재 제거

- 파일: `agent/agent.py`
- 할 일: `run_agent`의 인라인 수집을 지우고 `_collect_sources`만 쓴다. `_collect_sources`는 `search_documents`·`rerank_documents`에 더해 `graph_search` 결과의 `documents[*]`를 `{"id": f"graph:{file_id}:{page}", "file_id", "source", "page", "text": "개체: " + ", ".join(entities), "score": None}` 한 건씩으로 바꿔 넣는다. 청크 ID 기준으로 중복 제거.
- 테스트: 검색 1건 결과를 담은 `ToolMessage`로 `_collect_sources` 호출 → 1건. 그래프 결과 → 페이지 수만큼.
- 주의: 단계 B에서 출처 원천이 evidence로 바뀌므로 과하게 만들지 않는다.

### A3. 초안 저장 후 알림

- 파일: `mail/email_service.py` `email_consumer_loop`
- 할 일: `task_repo.save_draft(...)`를 `send_email(...)`보다 먼저 호출. 알림 발송이 실패하면 상태는 `drafted` 유지, `logger.exception`만 남긴다 (담당자는 대시보드에서 볼 수 있다).
- 테스트: `save_draft`가 예외를 던지는 대역에서 `send_email` 대역이 호출되지 않음을 확인.

### A4. 발송 상태 분기와 승인 선점

- 파일: `entity/type.py`, `storage/schema.sql`, `repository/repo_connect.py` `_migrate`, `repository/task_repository.py`, `mail/email_send.py`, `app/routers/mails.py`, `frontend/src/mail/types.ts`, `frontend/src/mail/pages/MailReviewPage.tsx`, `MailInboxPage.tsx`
- 할 일:
  1. `TaskStatus`에 2-1의 네 값 추가. 프론트 `MailStatus` 동기화.
  2. 새 테이블 `task_send(send_id INTEGER PK, task_id, body, recipient, attachments_json, attempted_at, outcome, detail, cleanup_warning)`.
  3. `TaskRepository.claim_for_send(task_id, body, recipient, attachments) -> int | None`: 한 트랜잭션에서 `UPDATE tasks SET status='sending' WHERE task_id=? AND status IN ('drafted','send_failed','send_unknown')`; rowcount 0이면 None; 1이면 `task_send` 행 삽입 후 `send_id` 반환. 본문·수신자·첨부는 이 시점에 고정된다.
  4. `send_email` → 2-2의 `SendResult` 반환으로 변경. 호출부(검토 알림 포함)는 반환값을 본다.
  5. `mail_approve`: `claim_for_send` 실패 → 409. 성공 → `send_email` → outcome을 `task_send`에 기록하고 `tasks.status`를 `sent / send_failed / send_unknown`으로. `cleanup_warning`은 로그 WARNING.
  6. 새 API `POST /mails/{task_id}/mark-sent`: `send_unknown`일 때만 `sent`로. 사유 문자열 필수. `task_reviews`에 `action='mark_sent'`로 남긴다.
  7. 프론트: 상세 화면에서 `send_failed` → "재발송" 버튼(승인 API 재호출), `send_unknown` → "발송 확인됨" + "재발송" 두 버튼, 확인 다이얼로그에 "자동 재발송은 하지 않습니다" 문구. 목록 필터에 세 상태 추가.
  8. `PROCESSING`: `email_consumer_loop`가 `get_pending_tasks` 직후 `update_status(PROCESSING)`. `main.py` lifespan 시작부에서 `task_repo.reset_processing()` (processing → pending) 호출. `sending`은 건드리지 않는다.
- 테스트:
  - SMTP 대역 3종(login 예외 / data 예외 / data 250 후 quit 예외) → outcome 각각 FAILED / UNKNOWN / SENT+warning.
  - 승인 API를 두 스레드로 동시에 호출(SMTP 대역은 0.5초 지연) → 발송 대역 1회, 409 1회.
  - `mark-sent`는 `send_unknown`에서만 200, 그 외 409.
  - `reset_processing` 후 `processing` 0건.
- 완료: Gemini B-A "발송 상태 분기".

### A5. 한국어 개체 매칭

- 파일: `repository/graph_repository.py` `find_entities`, `tests/test_graph.py`
- 할 일:
  1. 질문 토큰을 세 종류로 만든다. (a) 영숫자 식별자: `re.findall(r"[A-Za-z0-9]+(?:[-_.][A-Za-z0-9]+)*", query)`, (b) 공백·쉼표 분리 어절, (c) 어절 끝의 조사(의, 은, 는, 이, 가, 을, 를, 에, 로, 으로, 과, 와, 도, 에서, 부터, 까지) 하나를 뗀 것. 모두 `normalize` 후 길이 ≥ `MIN_PARTIAL_LEN`.
  2. SQL은 지금처럼 `instr` + `LIKE 'tok%'`로 **후보 superset**을 뽑되 `a.alias`(원문)도 SELECT한다.
  3. Python 후처리: `instr` 조건으로 잡힌 것은 그대로 통과. `LIKE`로 잡힌 것은 별칭 원문을 공백으로 나눈 토큰들을 각각 `normalize`한 집합에 질문 토큰이 **정확히 포함**될 때만 통과. (`"N5800 14세대"` → `{"n5800","14세대"}`에 `"n5800"` 포함 → 통과. `"N5800-GB70-PU02"`의 토큰 `"n5800gb70pu02"` → `"n5800"` 불포함 → 탈락.)
  4. 한글 접미사를 무조건 삭제하지 않는다. (c)는 후보 추가일 뿐이다.
- 테스트 (임시 DB에 별칭 심기): `"N5800의 사양"` → `N5800 14세대` 1건. `"N5800"` → 1건. `"N5800-GB70-PU02 인증"` → `N5800 14세대` 0건, `N5800-GB70-PU02` 1건. `"KC인증 자료"`와 `"KC 인증 자료"` 결과 동일. `"R-R-TGE-N5800"` 별칭이 `"N5800"` 질문에 잡히지 않음.
- 완료: Gemini B-A "한국어 토큰화".

### A6. 기준선 10문항 확정 (코드 아님)

- `tests/eval/baseline_2026-11-12.json`에서 [gemini_verification_instructions.md](gemini_verification_instructions.md) C-1의 10건을 골라 `tests/eval/eval_set.json`으로 복사한다. `expected_evidence`·`expected_keywords`는 비워 두고, 각 문항에 `why`(무엇을 검증하는 문항인지) 한 줄을 적는다. R&D 담당자가 채울 자리임을 README 주석으로 남긴다.

---

## 4. 단계 B — 공통 근거 서비스와 최소 registry

순서대로 B1 → B6. 각 항목이 끝나면 에이전트가 end-to-end로 돌아가야 한다(대역 모델로).

### B1. evidence 저장소

- 파일: `storage/schema.sql`(2-3 테이블), `repository/evidence_repository.py`(신규), `repository/__init__.py`에 `evidence_repo` 추가
- API: `register(owner_type, owner_id, origin_type, text, *, file_id=None, page_id=None, page=None, attachment_id=None, spec_value_id=None, revision=None) -> str`, `get(evidence_id) -> dict|None`, `get_many(ids) -> list[dict]`, `list_for_owner(owner_type, owner_id) -> list[dict]`, `record_use(run_id, evidence_id, action)`, `start_run(owner_type, owner_id, model, prompt_id) -> str`, `finish_run(run_id, status, tool_calls, tokens_in, tokens_out, error=None)`, `uses_for_run(run_id, action=None)`.
- 실행 중인 owner/run은 `contextvars`로 전달한다 (`agent/evidence_context.py`: `current_owner()`, `current_run()`). `run_agent*`가 진입 시 설정하고 종료 시 해제한다. 도구는 이 컨텍스트로 owner를 알아낸다.
- 테스트: 같은 페이지·같은 revision 재등록 시 같은 ID. 다른 owner 조회 시 None.

### B2. `read_pages` · `list_documents` · `grep_documents`

- 파일: `tools/tool.py`(기존 파일에 추가), `agent/agent.py` `TOOLS`
- `read_pages`: `page_repo.pages_with_number(file_id, page)`로 행을 모아 `"\n\n".join(text)`. `has_pages` False면 파싱하지 않고 오류 dict 반환 (2-4). revision은 행의 `updated_at`. 등록 후 `record_use(run, eid, 'read')`.
- `list_documents`: `file_repo.file_list()` + `page_repo.has_pages`. `page_count`는 `SELECT COUNT(DISTINCT page)`를 `FilePageRepository`에 추가.
- `grep_documents`: `FilePageRepository.search_text(pattern, file_id, limit)` 추가. SQL `LIKE '%'||?||'%'`로 1차 필터 후 Python `re.search(pattern, text, re.I)`로 매치 줄 ±80자를 snippet으로.
- `read_source_document` 제거, 관련 프롬프트 문구 제거.
- 테스트: 검수로 바꾼 텍스트가 `read_pages` 결과에 즉시 반영. 페이지 없는 파일에서 `parse_file` 대역 호출 0회.

### B3. `search_documents` 스니펫화 · `rerank_documents` ID화

- `search_documents`: 각 청크를 `origin_type='chunk'`로 evidence 등록(`file_id`, `page`, `text` 전체 저장), 반환에는 `snippet`(300자)와 `evidence_id`. `text` 키 제거.
- `rerank_documents(query, evidence_ids, top_n)`: `evidence_repo.get_many`로 본문을 가져와 `rerank()` 호출. 리랭커 미로드 시 **입력 순서를 그대로** 돌려준다 (빈 목록 금지). `record_use(..., 'rerank')`.
- `check_answerability`는 이 시점에 인자를 `evidence_ids`로 바꾼다 (B6에서 제거 예정이지만 그때까지 전문 복사가 없어야 함).
- 테스트: 리랭커 None일 때 입력 순서 반환. 다른 owner의 ID를 넣으면 무시되고 경고 로그.

### B4. 첨부를 도구 읽기로

- 파일: `agent/agent.py` `_attachment_to_block`, `run_agent_temp_attachments`, `tools/tool.py` `read_attachment`, `repository/email_repository.py`, `storage/schema.sql`
- 새 테이블 `attachment_page(attachment_id, seq, page, text, parser_version, created_at)`. 메일 첨부는 `mail_attachments.attachment_id`를 쓰고, `/ask/attachments`의 임시 첨부는 `owner_type='session'`의 evidence로만 등록하고 응답 후 삭제한다(현재 동작 유지).
- `_attachment_to_block`: 문서 첨부는 **텍스트를 넣지 않고** `"[첨부 1] 파일명.pdf (pdf, attachment_id=17, 12페이지) — read_attachment로 읽으세요"` 한 줄. 이미지는 지금처럼 `image_url` 블록 유지. 이미지도 `origin_type='attachment'` evidence로 등록(text는 파일명·크기).
- `read_attachment(attachment_id, pages, max_chars)`: `attachment_page`에 없으면 **그 첨부만 1회 파싱해 저장**(이것은 첨부에 한해 허용. 등록 문서의 재파싱 금지와 다르다), 이후 `read_pages`와 같은 형식. 현재 owner의 메일에 속한 첨부가 아니면 거부.
- 테스트: 50페이지 PDF 첨부 → user 메시지 길이가 500자 미만. `read_attachment(pages=[25])` → 25페이지 텍스트.

### B5. `list_evidence` 도구와 출처 수집 교체

- `list_evidence()`: `evidence_repo.list_for_owner(current_owner())` 한 줄씩.
- `_collect_sources` 제거. `run_agent*`의 `sources`는 `uses_for_run(run, 'cite')`가 있으면 그것, 없으면 `'read'`. 각 항목 `{evidence_id, file_id, source(파일명), page, text(앞 500자), origin_type}`. `task_repo.save_draft`의 `_replace_sources`는 `evidence_id`를 `chunk_id` 자리에 넣는다.
- `GET /mails/{id}`, `/ask` 응답에 `cited: bool` 필드 추가 (인용 근거인지 읽은 근거인지 화면이 구분).

### B6. 작은 서버 검증과 실행 기록

- 파일: `agent/agent.py`(`_invoke_logged` 주변), `agent/validation.py`(신규), `mail/email_service.py`, `app/routers/questions.py`
- `_invoke_logged`: `start_run` → invoke → `finish_run`. 예외·`recursion_limit` 초과·빈 답변은 `status='error'|'limit'`로 기록하고 **예외를 올린다**. consumer는 이때 `FAILED`로 둔다(현재와 같음). `drafted`로 저장되는 경우는 정상 종료뿐이다.
- `validate_answer(run_id, owner, answer) -> ValidationResult`:
  1. 마지막 줄 `근거: …` 파싱. 없으면 `warnings += ["근거 줄 없음"]`.
  2. 인용 ID가 owner 소유인지. 아니면 `errors += [...]`, 해당 ID 제거.
  3. 인용 ID가 이 run에서 `read`됐는지. 아니면 `warnings`.
  4. `근거: 없음`이 아닌데 이 run에 `read`가 0건이면 `errors += ["근거를 읽지 않고 답변"]`.
  5. 반환: `{ok: errors==[], errors, warnings, cited_ids}`. 본문에서 근거 줄은 제거한다.
- `errors`가 있으면 답변을 저장하되 `tasks.validation_json`(새 컬럼, `_migrate`)에 기록하고 상태는 `drafted`. 검토 화면 상단에 경고 배지로 보여 준다. "검증 완료" 같은 문구는 쓰지 않는다.
- 이 항목이 끝나면 `check_answerability`를 도구와 프롬프트에서 제거한다.
- 테스트: 대역 모델이 `근거: e999`(남의 ID)를 내면 errors 1건. `read` 0건 + 사실 답변 → errors. `근거: 없음` + read 0건 → ok.

### B7. 프롬프트 v2와 설정값

- 파일: `agent/prompt.py`, `repository/prompt_repository.py`, `config.py`, `app/routers/questions.py`
- `SYSTEM_PROMPT_TEMPLATE`를 새로 쓴다. 절차 번호·"start=0"·"최대 2회"·`check_answerability` 언급 삭제. 내용: 역할 1문단, 도구 역할 표(2-4), 진입 규칙 3줄(모델명·인증 → `graph_search`/`grep_documents`, 자유 서술 → `search_documents`, 특정 문서 → `list_documents`+`read_pages`), 불변 조건("인용하는 페이지는 반드시 `read_pages`/`read_attachment`로 읽은 것", "마지막 줄 `근거: …`"), 출력 형식. `GRAPH_GUIDE`는 템플릿에 흡수하고 `render_prompt`는 상위 개념 목록만 덧붙인다.
- DB: `prompt_repo`에 새 행 "v2 근거 ID"를 넣고 선택한다. 기존 행은 지우지 않는다. `ensure_default`가 기존 기본 프롬프트를 덮어쓰지 않게 확인.
- `config.py`: `SEARCH_TOP_K=5`, `RERANK_TOP_N=3`. 도구 기본값이 이를 읽는다. `QuestionRequest.query_top_n/rerank_top_n`은 Optional로 바꾸고 무시됨을 docstring에 적는다. 프론트는 손대지 않는다.

---

## 5. 단계 C — 내부 반려 루프 멀티턴

### C1. checkpointer

- 설치: `.venv/Scripts/pip install "langgraph-checkpoint-sqlite==3.1.3"` 후 `requirements.txt`에 고정.
- 파일: `agent/agent.py`, `main.py`
- `build_agent(mode, checkpointer)`: `create_agent(..., checkpointer=checkpointer)`. 저장소는 `storage/agent_threads.db`, `sqlite3.connect(path, check_same_thread=False)`로 lifespan에서 열고 종료 시 닫는다. `get_agent`가 같은 checkpointer를 공유.
- `run_agent*`에 `thread_id: str` 인자 추가. 메일은 `f"task:{task_id}"`, `/ask`는 호출마다 `f"ask:{uuid4().hex}"` (웹 멀티턴은 Q8대로 선택 범위, 이번에 넣지 않는다).
- `invoke` config: `{"configurable": {"thread_id": thread_id}, "recursion_limit": 40}`.

### C2. 맥락 예산 미들웨어

- 파일: `agent/agent.py` `build_agent`, `config.py`
- 순서대로 `middleware=[_system_prompt, ContextEditingMiddleware(...), SummarizationMiddleware(...), ToolCallLimitMiddleware(...), ModelCallLimitMiddleware(...)]`.
- `ContextEditingMiddleware(edits=[ClearToolUsesEdit(trigger=config.CTX_CLEAR_TRIGGER_TOKENS, keep=3, exclude_tools=("list_evidence",), placeholder="[축약됨 — list_evidence로 근거 ID를 다시 조회하세요]")])`.
- `SummarizationMiddleware(model=get_llm_model("local"), trigger=("tokens", config.CTX_SUMMARY_TRIGGER_TOKENS), keep=("messages", 12), summary_prompt=…)`. **비율형 트리거 금지**(vLLM 모델에 profile 없음). 요약 프롬프트는 기본문에 "evidence ID(e…), 제품 모델명, 수치, 인증번호, 반려 사유는 반드시 그대로 보존"을 추가.
- `ToolCallLimitMiddleware(tool_name="search_documents", run_limit=6)`, `ToolCallLimitMiddleware(run_limit=25)`, `ModelCallLimitMiddleware(run_limit=20, exit_behavior="end")`. 한도로 끝난 경우 마지막 메시지가 업무 답변이 아니므로 B6 규칙에 따라 `drafted`로 저장하지 않는다 (run status `limit`).
- `config.py` 기본값: `CTX_CLEAR_TRIGGER_TOKENS=24000`, `CTX_SUMMARY_TRIGGER_TOKENS=40000`. 로컬 모델 한도를 확인해 조정하고 그 근거를 dev_log에 적는다.
- 테스트: 대역 모델로 `read_pages` 결과 4개를 쌓은 뒤 5번째 모델 호출 입력에서 처음 결과가 placeholder로 바뀌어 있고 `list_evidence` 결과는 남아 있음.

### C3. 반려를 다음 턴으로

- 파일: `mail/email_service.py`, `repository/task_repository.py`, `agent/agent.py`
- `tasks.last_review_id INTEGER`(`_migrate`). `task_repo.unapplied_reject_reasons(task_id) -> list[(review_id, reason)]`: `review_id > last_review_id`인 requeue 반려만.
- consumer:
  - 미적용 반려가 없으면 첫 실행: 기존처럼 질문 + 첨부 메타 블록.
  - 있으면 **같은 thread_id로** `[{"role":"user","content": "[검토 담당자 반려]\n" + 사유들}]`만 투입. `build_review_feedback`의 이전 초안 포함은 제거(이미 thread에 있다). 성공 시 `last_review_id` 갱신.
  - checkpoint가 없는데 반려만 있는 경우(마이그레이션 전 task): 첫 실행 경로 + 반려 사유를 두 번째 user 메시지로 같이 넣는다.
- 같은 thread 동시 실행 방지: `agent/agent.py`에 `threading.Lock` 딕셔너리(thread_id별). consumer는 단일 스레드지만 `/ask` 공유 대비.
- 테스트: 반려 1회 → 두 번째 invoke 입력 메시지에 1차의 `read_pages` ToolMessage(또는 placeholder)가 있고 `search_documents` 호출이 없음(대역 모델이 바로 답변). 같은 `review_id`로 두 번 처리 → user 메시지 1개만 추가.

### C4. 재시작 복구

- `main.py` lifespan: `task_repo.reset_processing()`(A4) 뒤 checkpointer 열기. `processing`에서 `pending`으로 돌아온 task는 다음 주기에 같은 thread로 이어진다(C3 로직이 처리).
- 테스트: 임시 checkpointer DB에 thread 상태를 만든 뒤 새 `build_agent`로 같은 thread_id 호출 → 이전 메시지가 입력에 포함.

### C5. 검토 화면 보강

- `GET /mails/{id}`에 `trace: [{tool, args_summary, at}]`(run의 `tool_calls_json`)와 `validation` 추가. `MailReviewPage.tsx`에 "에이전트가 한 일" 접이식 목록과 검증 경고 배지. 근거 목록은 `cited`와 `read`를 구분해 표시.

---

## 6. 단계 D~H (개요, 별도 지시 예정)

| 단계 | 핵심 | 설계 참조 |
|------|------|-----------|
| D | 발신자별 고객방 조회 UI(`GET /customers`, `/customers/{sender}/timeline`), skill 문서 4종(`skills/<name>/SKILL.md`)과 선택 로딩 도구. **상세 지시: [opus_development_instructions_D.md](opus_development_instructions_D.md)** | total 10-2, 11-2, 11-3 |
| E | `get_product_specs`·`compare_specs`. `spec_attribute.inheritable` 플래그(기본 false), 자식 명시 값 우선, 기본/옵션 구분, 단위 정규화, `product_component` 연결 없는 부품 값 사용 금지. **제품 양식은 한 시트·공통 속성 유지**(노트북/데스크톱 분리·전용 속성 추가 금지) | total 8-2, 8-7, 11-7 |
| F | deepagents backend 시제품: `EvidenceService` 위에 읽기 전용 `BackendProtocol` 구현, 같은 10문항으로 비교. 채택 전 설치 버전 고정 | total 11-2 |
| G | `mails`에 `message_id, in_reply_to, references_` 컬럼, 발신 시 `Message-ID` 생성·`task_send`에 저장, `In-Reply-To`로 conversation 연결, `raw_body/new_body/quoted_body` 분리, 고객 메모리 테이블 | total 11-3, 4장 4단계 |
| I | 문의 분석(유형·맡는 절차), 절차 초안 생성(로컬 모델), R&D 승인 화면. 승인본만 사용. **실행 순서는 D 다음, E 앞. 상세 지시: [opus_development_instructions_I.md](opus_development_instructions_I.md)** | 사용자 결정 2026-11-13 |
| H | 그래프를 만들 때 제품·부품 사양 DB를 참조한다. 아래 6-1 참고. **A~C 범위가 아니다. 지금 구현하지 않는다** | 사용자 요청 2026-11-13 |

### 6-1. 단계 H — 그래프 생성 시 사양 DB 참조 (나중 단계)

배경: 지금 그래프의 제품·부품 개체는 문서에서 LLM이 뽑은 표기뿐이다(`graph_rag/extractor.py`는 `concepts`만 입력으로 받는다). 사양 DB(`product`, `component`, `product_component`)에는 정식 모델명과 상위·파생 관계가 있는데 그래프와 이어져 있지 않다. 그래서 같은 제품이 문서마다 다른 표기로 따로 잡히고, 그래프에서 찾은 제품을 사양 조회로 넘길 수 없다.

할 일 (E가 끝난 뒤, 별도 지시가 있을 때)

1. **사양 DB로 개체를 미리 심는다.** `seed_concepts`와 같은 방식으로 `GraphRepository.seed_specs()`를 만든다.
   - `product.model`·`name` → `product` 개체와 별칭. `component.model`(+`vendor`) → `component` 개체.
   - `product.parent_id` → 새 관계 `variant_of`(파생 → 상위). `graph_rag/types.py` `RELATION_TYPES`에 추가.
   - `product_component` → `has_component`. 옵션 여부는 관계의 비고로 남긴다.
   - 출처는 새 값 `origin='spec'`. 문서를 다시 뽑아도 유지되고, 사양 DB가 바뀌면 `spec` 출처만 지우고 다시 넣는다. 화면에서 지운 관계(`graph_relation_block`)는 되살리지 않는다.
   - `graph_entity`에 `ref_type`(`product`|`component`), `ref_id` 컬럼을 `_migrate`로 추가해 사양 DB 행과 연결한다.
2. **추출할 때 정식 이름에 맞춘다.** `extract_page_graph`에 알려진 제품·부품 목록을 `concepts`처럼 넘긴다. 부품이 많으므로(현재 123건) 그 페이지 텍스트에 문자열로 등장하는 후보만 추려서 넘긴다. 문서 표기가 정식 모델과 같은 대상이면 정식 이름의 개체에 붙이고 문서 표기는 별칭으로 남긴다. 사양 DB에 없는 제품(타사 모델 등)은 지금처럼 그대로 뽑는다.
3. **검색 결과를 사양 조회로 잇는다.** `graph_search`의 `matched`에 `ref_type`·`ref_id`를 포함해 E의 `get_product_specs(product_id)`로 바로 넘길 수 있게 한다. 파생 모델을 물으면 `variant_of`로 상위 모델의 문서도 후보에 넣는다.

지킬 것
- 상위 모델의 인증을 파생 모델에 자동으로 적용하지 않는다. `variant_of`는 문서 후보를 넓힐 뿐이고, 적용 모델은 문서 근거로 확인한다.
- `product_component`는 현재 0건이다. 연결 데이터는 도메인 입력이며 임의로 만들지 않는다.
- A5의 토큰 규칙(`N5800`과 `N5800-GB70-PU02` 구분)이 심은 개체에도 그대로 통과해야 한다.
- 제품 양식은 한 시트·공통 속성을 유지한다.

완료 조건: 사양 DB에 등록된 제품을 다른 표기로 적은 문서 두 개가 같은 개체에 붙는다. 그래프 재추출 뒤에도 `spec` 출처 개체·관계가 남는다. `graph_search("N5800")` 결과에 `product_id`가 들어 있다.

---

## 7. 보고 형식 (항목마다 `docs/dev_log/<단계>-<항목>.md`)

```
# <단계-항목> <제목>
## 변경 파일
## 결정한 것 (지시서에 없어서 스스로 정한 것, 이유 포함)
## 테스트: 명령과 출력 (요약 아님, 실제 출력 마지막 20줄)
## 확인하지 못한 것 / Gemini에게 요청할 검증
## 커밋 해시
```

지시서와 코드가 충돌하면 코드를 고치지 말고 dev_log에 "충돌" 항목으로 적고 멈춘다. 설계 변경은 구현자가 결정하지 않는다.
