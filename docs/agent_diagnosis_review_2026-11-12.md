# rag_QA 에이전트 진단 검증 · 상용 에이전트 비교 · 고도화 방향

작성일: 2026-11-12
대상: Handoff 문서 「rag_QA 에이전트 역량 진단 및 메일 멀티턴 전환 설계」
검증 방법: 실제 코드(`agent/`, `tools/`, `repository/`, `mail/`, `app/routers/`)와 운영 DB(`storage/mail.db`) 구조를 직접 읽어 대조

---

## 1. 진단서 7개 항목 검증 결과

| # | 진단 | 판정 | 근거 위치 | 비고 |
|---|------|------|-----------|------|
| ① | 검수 텍스트(`file_page`) 무시, 원본 재파싱 | **확인** | [tools/tool.py:258](../tools/tool.py#L258) `_extract_text` → `parse_file(path_str)` | 검수 저장은 [files.py:255](../app/routers/files.py#L255)에서 Chroma·`file_page`·그래프까지 갱신하지만 `read_source_document`만 디스크를 읽음. `lru_cache(mtime)` 기준이라 검수해도 캐시가 안 깨짐 |
| ② | 사양 DB와 에이전트 단절 | **확인** | [agent/agent.py:24](../agent/agent.py#L24) `TOOLS` 5개 | 운영 DB에 product 4, component 123, spec_value 1,572건이 있으나 조회 도구 없음. `product_component`는 0건 |
| ③ | `graph_search` 경로에서 `sources=[]` | **확인 + 추가 원인** | [agent/agent.py:63](../agent/agent.py#L63), [agent/agent.py:173](../agent/agent.py#L173) | `run_agent`는 `_collect_sources`를 쓰지 않고 같은 로직을 인라인 중복. **메일 검토 화면의 출처 0건은 그래프와 무관**: [mails.py:102](../app/routers/mails.py#L102)에서 `sources` 조립이 통째로 주석 처리됨 |
| ④ | `start=0` 순차 읽기, 파일 목록·grep 부재 | **확인** | [tools/tool.py:270](../tools/tool.py#L270) | `[page N]` 마커를 본문에 넣으면서도 페이지로 점프할 수 없음. 글자 오프셋은 모델이 산수를 해야 함 |
| ⑤ | 한국어 조사 결합 시 개체 매칭 실패 | **확인(논리)** | [graph_repository.py:324](../repository/graph_repository.py#L324), [graph_rag/types.py:42](../graph_rag/types.py#L42) | `_NORM_STRIP`은 공백·기호만 제거하고 한글은 남김 → `"N5800의"` → `n5800의`. `instr`은 alias가 질문 안에 통째로 들어있을 때만 잡으므로 "N5800"이 단독 alias로 등록돼 있으면 우연히 잡힘. 현재 DB에는 N5800 개체 자체가 없어 실데이터 검증은 못 함 |
| ⑥ | 텍스트 전문을 LLM 인자로 복사 | **확인** | [tools/tool.py:156](../tools/tool.py#L156), [tools/tool.py:184](../tools/tool.py#L184) | `documents: list[dict]` 전체를 출력 토큰으로 재생성. 프롬프트는 "원본에서 읽은 근거 부분"을 넣으라고 하므로 8,000자 읽기 결과를 다시 써야 함. `check_answerability`는 mode와 무관하게 항상 local 모델 |
| ⑦ | 프롬프트 충돌, `/ask` 파라미터 무시 | **확인** | DB `prompt` 테이블(선택된 "테스트" 프롬프트), [prompt.py:52](../agent/prompt.py#L52), [questions.py:42](../app/routers/questions.py#L42) | DB 프롬프트 본문 "1. search_documents로 찾는다" + 뒤에 붙는 `GRAPH_GUIDE` "search_documents보다 먼저 graph_search". `query_top_n`/`rerank_top_n`은 Pydantic 필수 필드라 프론트는 반드시 보내지만 서버는 버림 |

싱글턴 판정도 확인됨. `build_agent`에 checkpointer 없음, 두 `run_agent*` 모두 메시지 1건으로 호출 후 상태 폐기. `langgraph-checkpoint` 4.1.1은 설치돼 있으나 `langgraph-checkpoint-sqlite`는 미설치. 메일 쪽은 `Message-ID`/`In-Reply-To`/`References` 처리와 인용문 분리가 코드 어디에도 없음.

### 진단서가 놓친 추가 문제

- **첨부 파일 전문 덤프**: [agent/agent.py:154](../agent/agent.py#L154) `_attachment_to_block`이 첨부 PDF/docx를 페이지 제한 없이 통째로 user 메시지에 넣음. 고객이 50페이지 사양서를 붙이면 그것이 곧 프롬프트가 됨. 상용 에이전트는 첨부를 "읽을 수 있는 파일"로 두고 필요한 부분만 도구로 읽음.
- **출처가 "읽은 것"이 아니라 "검색된 것"**: `sources`는 `search_documents` 히트 청크를 모은 것이라, 모델이 실제로 `read_source_document`로 읽고 근거로 쓴 페이지와 무관. 검토 담당자가 보는 근거와 답변의 실제 근거가 다를 수 있음.
- **반려 피드백이 질문과 같은 user 턴에 섞임**: [agent/agent.py:92](../agent/agent.py#L92). 모델 입장에서는 "질문 + 이전 초안 + 반려 사유"가 한 덩어리 새 질문. 멀티턴이 없으니 불가피한 구조.
- **`check_answerability`가 품질 게이트 역할을 못 함**: 모델이 복사한 텍스트를 다시 모델이 판정. 프롬프트에 "최대 2회" 재검색 지시 + `recursion_limit=40`이 유일한 종료 조건.
- **`rerank_documents`는 리랭커 로드 실패 시 빈 목록**: 모델이 "후보 0건"으로 오해해 재검색 루프에 빠질 수 있음.
- **file_page 없는 옛 파일**: `file_page` 테이블은 커밋 52963dd 이후 업로드분만 있음. ①을 고칠 때 `has_pages`가 False면 파싱으로 fallback해야 함.

### 우선순위 평가

진단서의 1순위(①, ③, ⑤)는 타당함. 다만 두 가지를 조정 권장.

1. **⑥(도구 인자 전문 복사)은 2순위가 아니라 1순위 수준**: 멀티턴(3순위)을 도입하면 매 턴 8,000자 단위 읽기 결과가 상태에 쌓이는데, 그 위에서 모델이 텍스트를 다시 복사하는 도구가 남아 있으면 컨텍스트와 지연이 곱으로 커짐. 멀티턴 전에 "핸들(ID)로 참조" 구조로 바꿔야 함.
2. **메일 검토 화면 출처 복구는 1줄짜리 즉시 수정**: [mails.py:102](../app/routers/mails.py#L102) 주석 해제. ③과 별개 작업.

---

## 2. 상용 에이전트(Claude Code · Codex · Antigravity)와의 구조적 차이

| 축 | 상용 코딩 에이전트 | rag_QA 현재 | 차이가 만드는 결과 |
|----|-------------------|-------------|-------------------|
| **도구 원시성** | `ls`/`glob`/`grep`/`read(offset,limit)` 같은 작고 결정적인 원시 도구를 조합 | 의미 검색·리랭크·판정처럼 "한 번에 많은 일"을 하는 도구 5개 | 모델이 전략을 세울 여지가 없고, 도구가 못 하는 탐색(목록 보기, 정확 일치)은 불가능 |
| **참조 방식** | 파일 경로·라인 번호·ID 같은 **핸들**로 주고받음. 내용은 도구 결과로만 흐름 | 모델이 이전 도구 결과의 본문을 다음 도구 인자로 **재작성** | 출력 토큰 낭비, 변형, 지연. 멀티턴 전환의 최대 걸림돌 |
| **상태·기억** | 세션 전체가 영속 스레드. 긴 세션은 compaction(요약)으로 유지 | 매 호출 백지. 반려 재생성도 처음부터 | 1차 때 읽은 문서를 다시 읽음. 근거 문서가 바뀔 수 있음 |
| **탐색 루프** | 가설 → 확인 → 수정의 자유 루프. 종료는 모델이 판단 | 프롬프트에 1~5단계 절차를 고정. 게이트는 LLM 판정 1회 | 질문 유형이 바뀌면(사양 비교, 인증 묶음) 절차가 안 맞음 |
| **정형 데이터** | 쉘·SQL·스크립트 실행으로 직접 질의 | 사양 DB 1,572건이 있어도 못 봄 | 입찰 사양 대조가 핵심 질문인데 벡터 검색으로만 답함 |
| **근거 표시** | 실제로 읽은 `file:line`을 인용 | 검색 히트 청크를 출처로 표시 | 검토자가 보는 근거 ≠ 답변 근거 |
| **입력 자료** | 첨부·저장소를 "읽을 수 있는 공간"으로 두고 필요 시 읽음 | 첨부 전문을 프롬프트에 덤프 | 긴 첨부 = 컨텍스트 폭발 |
| **사람 개입(HITL)** | 권한 확인·plan 승인을 그래프의 interrupt로 모델링 | 메일 검토는 상태 폴링(`pending`→`drafted`→`reject`) | 반려가 "다음 턴"이 아니라 "새 작업"이 됨 |
| **관측·평가** | 도구 호출 궤적이 그대로 전사됨. 회귀 eval 세트 보유 | 로그만 남음. 평가는 `tests/rag_agent_run.py` 1회성 | 프롬프트·도구를 바꿔도 좋아졌는지 알 수 없음 |

핵심 요약: 상용 에이전트의 능력은 모델이 똑똑해서가 아니라 **"작고 결정적인 도구 + 핸들 참조 + 영속 상태 + 궤적 가시화"**라는 네 가지 공학적 기반에서 나옴. rag_QA는 네 가지 모두 없는 상태에서 프롬프트 절차 고정으로 버티고 있음.

---

## 3. 고도화 방향

### 3-1. 도구 계층 재설계 (멀티턴보다 먼저)

목표: 모델이 본문을 복사하지 않고, 파일시스템 탐색하듯 문서를 다룰 수 있게 한다.

| 새 도구 | 역할 | 구현 근거 |
|---------|------|-----------|
| `list_documents(group_id?, keyword?)` | 등록 문서 목록(이름·그룹·페이지 수·설명) | `file_repo.file_list()` + `page_repo` |
| `grep_documents(pattern, file_id?)` | 검수된 `file_page.text`에서 정확 일치/정규식. 결과는 `(file_id, page, 매치 줄)` | SQLite `LIKE`/Python `re` |
| `read_pages(file_id, pages=[...])` | 검수 텍스트를 **페이지 번호로** 읽음. `[page N]` 마커 유지 | `page_repo.pages_with_number`, 없으면 `parse_file` fallback |
| `search_documents` | 유지. 반환에 `text` 대신 **요약 스니펫 + 청크 ID** | 기존 |
| `rerank_documents(query, chunk_ids)` | 청크 ID만 받아 서버에서 본문 조회 | Chroma `get(ids=…)` |
| `check_answerability` | **삭제 또는 선택**. 대신 최종 답변에 `cited_pages=[(file_id,page)]` 구조화 출력 요구 | 근거 추적이 자동으로 됨 |
| `spec_lookup(model, attributes?)` / `spec_compare(models[])` | 제품·부품 사양 조회·비교. 하위 모델은 `parent_id`로 상속 | `spec_repo.find_owner`, `_specs` |
| `read_attachment(name, pages?)` | 첨부를 프롬프트에 넣지 않고 도구로 읽게 함 | `parse_file` + 임시 폴더 |

`read_pages`가 생기면 `read_source_document`의 `start/max_chars`는 폐기. 출처는 `read_pages` 호출 이력과 `cited_pages`에서 수집하면 ③이 구조적으로 해결됨.

### 3-2. 영속 스레드 (메일 작업 1건 = thread 1개)

- `langgraph-checkpoint-sqlite` 설치 후 `SqliteSaver(storage/agent_threads.db)`를 `create_agent(checkpointer=…)`에 주입.
- `thread_id`: 메일은 `task_id`, 웹 채팅은 브라우저 세션 ID.
- 반려 루프: `email_consumer_loop`가 반려 건이면 같은 `thread_id`로 `[{"role":"user","content": 반려사유}]`만 투입. 1차 때 읽은 페이지가 상태에 남아 있어 재검색이 줄어듦.
- 고객 회신(`Re:`): 발송 시 `Message-ID`를 생성해 `tasks`에 저장, 수신 시 `In-Reply-To`/`References`로 원 작업을 찾아 같은 thread에 투입. 본문은 인용 구분선(`-----Original Message-----`, Outlook 한국어 `보낸 사람:`, `On … wrote:`) 앞부분만 사용.
- 주의: 8,000자 읽기 결과가 턴마다 쌓이므로 **도구 결과 축약(오래된 tool 메시지를 "읽음: 파일 p.3~5" 한 줄로 치환)** 미들웨어가 함께 필요. 3-1 없이 3-2만 하면 컨텍스트가 먼저 터짐.

### 3-3. 프롬프트를 "절차"에서 "정책"으로

- DB 프롬프트와 `GRAPH_GUIDE`의 순서 충돌 제거. 질문 유형별 진입점을 한 곳에 서술: 모델명·인증 → `graph_search`/`spec_lookup`, 자유 서술 → `search_documents`, 특정 문서 지정 → `list_documents`+`grep`.
- "최대 2회", "start=0부터" 같은 수치 지시 삭제. 대신 "답변에 인용한 페이지는 반드시 `read_pages`로 읽은 것이어야 한다"는 불변 조건만 남김.
- `/ask`의 `query_top_n`/`rerank_top_n`은 도구 기본값으로 연결하거나 API에서 제거.

### 3-4. 궤적 가시화와 평가 세트

- 메일 검토 화면에 "에이전트가 한 일"(검색어, 읽은 페이지, 사양 조회) 타임라인 표시. `result["messages"]`를 `task_trace` 테이블에 저장하면 됨. 담당자가 반려 사유를 쓸 때 어디서 틀렸는지 바로 보임.
- 골든 QA 세트 30~50문항(질문, 기대 근거 페이지, 기대 답변 키워드)을 `tests/eval/`에 두고 도구·프롬프트 변경마다 돌림. 현재는 변화의 좋고 나쁨을 측정할 수단이 없음.

### 3-5. 한국어 개체 매칭

- `find_entities` 토큰화: 영숫자 연속(`[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*`)을 먼저 뽑고, 한글 어절은 조사(의·은·는·이·가·을·를·에·로·과·와·도) 제거 후 토큰화.
- `alias_norm` 비교를 "질문 토큰이 alias의 접두"가 아니라 "alias의 첫 토큰이 질문 토큰과 일치"로 바꾸면 `N5800 14세대`도 `N5800`으로 잡힘.

---

## 4. 권장 실행 순서

1. **즉시(반나절)**: 메일 검토 출처 주석 해제, `_collect_sources`에 `graph_search`·`read_source_document` 포함, `find_entities` 토큰화 수정.
2. **1단계(도구)**: `read_pages`(검수 텍스트·페이지 점프) → `list_documents`/`grep_documents` → `rerank`/`check` 핸들 전환 → `spec_lookup`/`spec_compare` → `read_attachment`.
3. **2단계(프롬프트·출처)**: 정책형 프롬프트 1본으로 통합, `cited_pages` 구조화 출력, 궤적 저장·표시.
4. **3단계(멀티턴)**: checkpointer + 도구 결과 축약 미들웨어 → 반려 루프 → `Re:` 스레드.
5. **상시**: 골든 QA 세트로 각 단계 전후 비교.

진단서의 3순위(멀티턴)를 마지막에 두는 것은 동일하나, 그 전제로 ⑥(핸들 참조)과 도구 결과 축약이 반드시 선행돼야 한다는 점이 진단서와의 차이임.
