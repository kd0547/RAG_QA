# Gemini 검증 지시사항 — rag_QA 에이전트 고도화

작성일: 2026-11-12
역할: 당신(Gemini)은 **독립 검증자**다. 설계자(Claude = C, Codex = O)가 합의한 내용이 코드와 일치하는지, 구현이 완료 조건을 만족하는지, 개선 전후가 기준선 대비 나아졌는지를 확인한다. 설계를 다시 논의하거나 코드를 고치지 않는다.

## 0. 입력 자료와 환경

| 자료 | 경로 | 용도 |
|------|------|------|
| 합의 문서 (최종) | `docs/agent_review_total_2026-11-12.md` | 검증할 주장과 완료 조건의 원천. 6장 결정표, 11-8 실행 순서, 12장 최종 합의 |
| O 검토 원문 | `docs/agent_capability_review_2026-11-12.md` | 8장의 격리 실행 13사례 참고 |
| C 검토 원문 | `docs/agent_diagnosis_review_2026-11-12.md` | 1차 진단표 |
| 기준선 평가셋 | `tests/eval/baseline_2026-11-12.json` | 현재 상태의 답변 103건 + 로그 궤적 57건. 개선 후 비교 대상 |
| 추출 스크립트 | `tests/eval/export_baseline.py` | 읽기 전용. 개선 후 같은 방식으로 재추출 |
| 기준 환경 | **개발 서버 URL: 사용자가 별도 제공** | 기준선이 참조한 문서 17개가 등록된 환경. 로컬 `storage/mail.db`에는 문서 1개만 있어 재실행 비교는 서버에서만 유효 |

규칙
- 읽기 전용. 코드·DB·프롬프트를 고치지 않는다. 검증용 스크립트는 `tests/eval/` 아래 새 파일로만 만든다.
- 메일을 보내지 않는다. `send_email`, 승인 API(`POST /mails/{id}/approve`)를 호출하지 않는다.
- 실제 LLM 호출은 "C. 전후 비교"에서만, 사용자가 서버 URL과 함께 허용한 경우에만 한다.
- 모든 판정은 `PASS / FAIL / UNVERIFIED` 셋 중 하나다. 추측으로 PASS를 주지 않는다. 확인 못 한 것은 UNVERIFIED로 두고 이유를 적는다.
- 각 판정에 파일:줄 또는 재현 명령을 붙인다.

## A. 합의 문서의 코드 주장 검증 (구현 전, 지금 바로)

아래 표의 각 주장을 코드에서 확인하고 결과를 기록한다. 표의 위치는 2026-11-12 기준이며 줄 번호는 바뀔 수 있다.

| # | 주장 | 확인 위치 | 기대 관찰 |
|---|------|-----------|-----------|
| A1 | `read_source_document`는 `file_page`를 읽지 않고 `parse_file`로 원본을 재파싱한다 | `tools/tool.py` `_extract_text`, `read_source_document` | `page_repo` 참조 없음, `parse_file(path_str)` 호출, `lru_cache` 키가 (경로, mtime) |
| A2 | 검수 저장은 `file_page`·Chroma·그래프를 갱신하지만 원본 파일은 안 바꾼다 | `app/routers/files.py` `set_page_text` | `replace_page_embeddings`, `page_repo.update_text`, `_schedule_graph_index` 호출. 파일 쓰기 없음 |
| A3 | 에이전트 `TOOLS`에 사양 DB 도구가 없다 | `agent/agent.py` `TOOLS` | 5개 도구, `spec_repo` 참조 없음 |
| A4 | `_collect_sources`와 `run_agent` 인라인 수집은 `search_documents`·`rerank_documents`만 본다 | `agent/agent.py` | 두 곳 모두 이름 튜플이 그 둘뿐 |
| A5 | `run_agent`는 JSON 문자열 출처를 두 번 `extend`한다 | `agent/agent.py` `run_agent` | `json.loads` 직후 `extend`, 이어서 `isinstance(list)`에서 다시 `extend` |
| A6 | 메일 상세 API의 `sources`는 통째로 주석 처리돼 항상 `[]` | `app/routers/mails.py` `view_mail_detail` | 리스트 내부가 주석. `tests/test_mail_list.py`가 `sources == []`를 기대 |
| A7 | 승인 API는 SELECT 후 상태 검사만 하고, `sent` 전이는 SMTP 성공 뒤 | `app/routers/mails.py` `mail_approve`, `repository/task_repository.py` `approve` | 조건부 UPDATE 없음. 동시 승인 시 둘 다 `drafted`를 봄 |
| A8 | 승인은 `drafted`만 허용 (`failed` 재승인 불가) | `mails.py` `mail_approve` | `status != "drafted"` → 409 |
| A9 | 검토 알림 메일이 `save_draft`보다 먼저 발송된다 | `mail/email_service.py` `email_consumer_loop` | `send_email(...)` 다음 줄에 `task_repo.save_draft` |
| A10 | `find_entities`는 공백·쉼표 토큰에 `LIKE 'tok%'`, `normalize`는 한글을 남긴다 | `repository/graph_repository.py`, `graph_rag/types.py` `_NORM_STRIP` | `"N5800의 사양"` → 토큰 `n5800의`, 별칭 `n580014세대`와 불일치. 격리 실행으로 재현 |
| A11 | `rerank_documents`·`check_answerability`는 `documents: list[dict]` 본문을 LLM 인자로 받는다 | `tools/tool.py` | 서버 측 ID 조회 없음 |
| A12 | 첨부 문서 전문이 user 메시지에 들어간다 | `agent/agent.py` `_attachment_to_block` | `parse_file` 전체 페이지를 join해 text 블록으로 |
| A13 | DB 선택 프롬프트는 `search_documents` 먼저, `GRAPH_GUIDE`는 `graph_search` 먼저 | `storage/mail.db` `prompt` 테이블 `is_selected=1`, `agent/prompt.py` | 두 지시가 공존 |
| A14 | `/ask`의 `query_top_n`·`rerank_top_n`은 필수 필드지만 버려진다 | `app/routers/questions.py` | 주석 처리된 블록 |
| A15 | checkpointer 없음, `langgraph-checkpoint-sqlite`·`deepagents` 미설치, 내장 미들웨어는 존재 | `agent/agent.py` `build_agent`, `.venv/Scripts/pip list` | `checkpointer=` 인자 없음. `SummarizationMiddleware`·`ContextEditingMiddleware` import 가능 |
| A16 | 발신 메일에 `Message-ID`·`In-Reply-To`·`References`를 넣지 않고, 수신 시 저장하지 않는다 | `mail/email_send.py`, `mail/email_receiver.py`, `mails` 테이블 컬럼 | 세 헤더 문자열이 코드·스키마에 없음 |
| A17 | SMTP `send_message` 내부에서도 본문 전송 후 응답 대기 중 예외가 날 수 있다 | Python `smtplib.SMTP.data`, `send_message` | `354` 뒤 본문 전송 → 최종 응답에서 `SMTPServerDisconnected` 가능 (O 11-5 재현 방식 참고) |
| A18 | 로컬 DB: `product_component` 0건, `file` 1건, `file_page` 1건 | `storage/mail.db` 읽기 전용 조회 | 수치 일치 |

보고: 18행 표 + FAIL/UNVERIFIED 사유. 합의 문서와 코드가 다르면 **문서 쪽을 틀렸다고 보고** 어느 문장인지 적는다.

## B. 구현 완료 조건 검증 (각 단계가 끝날 때마다)

단계 이름은 합의 문서 11-8의 A~G를 따른다. 각 단계에서 아래를 확인한다.

### B-A. 0단계 결함 수정

| 항목 | 확인 방법 | PASS 조건 |
|------|-----------|-----------|
| 출처 복구 | `GET /mails/{task_id}` (sources가 저장된 task) | `sources`가 비어 있지 않고 `source, page, text` 포함. `tests/test_mail_list.py` 갱신돼 통과 |
| 2중 적재 제거 | `run_agent`로 검색 1건 결과를 대역 처리 | 같은 chunk가 1번만 |
| 저장 후 알림 | `email_consumer_loop` 코드 순서, 또는 `save_draft`를 실패시키는 대역 | 알림 발송 전에 초안이 DB에 있음 |
| 발송 상태 분기 | `TaskStatus`, 프론트 `MailStatus`, 승인 API | `sending/sent/send_failed/send_unknown` 존재. 동시 승인 2회 → 발송 대역 호출 1회 + 409 1회. `send_message` 정상 반환 후 `quit` 예외 → `sent` + 경고 로그. 본문 전송 중 disconnect → `send_unknown`. 자동 재발송 코드 없음 |
| 한국어 토큰화 | `find_entities` 격리 실행 | `"N5800의 사양"` → `N5800 14세대` 매칭. `"N5800-GB70-PU02"`가 `N5800`과 혼동되지 않음. `"KC인증"`·`"KC 인증"` 동일 결과 |
| 회귀 | `pytest tests/` | 기존 테스트 전부 통과 |

### B-B. 공통 근거 서비스 + 최소 registry

- `read_pages(file_id, pages)`가 `file_page.text`를 돌려주고, 검수로 바꾼 텍스트가 즉시 반영된다 (검수 저장 → 읽기 → 바뀐 문자열 포함).
- 페이지 없는 파일에 대해 `parse_file`을 호출하지 않고 "페이지 없음" 메시지를 돌려준다 (파서에 대역을 붙여 호출 0회 확인).
- evidence 행이 `owner_id, origin_type, file_id, page_id, revision, content_hash, text`를 갖고, 다른 task의 evidence_id를 인용하면 서버 검증이 거부한다.
- `rerank_documents`가 evidence_id 목록을 받고 본문을 인자로 받지 않는다.
- 첨부 문서 전문이 user 메시지에 없고, `read_attachment`로 제한된 분량만 돌아온다 (50페이지 PDF 첨부로 확인).
- 실행 실패·예산 초과·빈 답변이 `drafted`로 저장되지 않는다.

### B-C. 내부 반려 멀티턴

- 같은 `task_id`로 반려 1회 후 재생성 시, 1차에서 읽은 evidence를 다시 `read_pages` 하지 않고 ID로 재조회한다 (파서·DB 읽기 호출 횟수 비교).
- 문체만 바꾸는 반려에서 `search_documents` 호출이 0~1회다.
- 반려 이벤트를 같은 `review_id`로 두 번 넣어도 메시지가 한 번만 추가된다.
- 서버 재시작 후 같은 thread로 이어진다 (`storage/agent_threads.db`에 checkpoint 존재).
- 오래된 도구 결과가 자리표시자로 치환된 뒤에도 모델이 evidence 목록을 볼 수 있다 (O 11-4의 관찰: `ClearToolUsesEdit`는 본문 안의 ID도 지움).
- `ToolCallLimitMiddleware`·`ModelCallLimitMiddleware`가 run 기준으로 걸려 있고, 한도 초과 메시지가 고객 답변으로 저장되지 않는다.

### B-D. 고객방 UI + skill

- 발신자별 타임라인에 질문·초안·반려·발송이 시간순으로 보인다. 전체 타임라인이 모델 입력에 자동 주입되지 않는다.
- skill 문서(`spec-compare` 등)가 저장소에 있고, 선택된 것만 모델에 읽힌다. skill 본문의 지시가 서버 검증·승인 정책을 바꾸지 못한다.
- 항목별 통과 조건(D-1 ~ D-14)은 [opus_development_instructions_D.md](opus_development_instructions_D.md) 9절을 따른다.

### B-I. 문의 분석 · 절차 초안 · R&D 승인 (D 다음, E 앞)

- 승인 전 초안은 어떤 답변 실행에도 읽히지 않는다. 자동 승인 경로가 없다. 답변 에이전트에 쓰기 도구가 없다.
- 항목별 통과 조건(I-1 ~ I-12)은 [opus_development_instructions_I.md](opus_development_instructions_I.md) 10절을 따른다.

### 남은 단계 통합 검증 (E · H · G · F, 2026-11-13)

사용자 결정으로 남은 단계는 한 번에 만들고 한 번에 검증한다. 항목별 통과 조건은 [opus_development_instructions_remaining.md](opus_development_instructions_remaining.md) 9절 T5 표를 따른다. 아래 B-E ~ B-G는 그 표의 요약이다.

### B-E. 사양 계산·비교

- `get_product_specs`: 자식 명시 값 > 허용 상속 부모 값. `inheritable=false` 속성은 상속 안 됨. 값 부재와 "미지원"을 구분.
- `compare_specs`: "RAM 32GB 이상"에 대해 기본 16GB/최대 64GB/옵션 32GB를 각각 다르게 판정. `1.5kg`과 `1500g` 동일 판정.
- `product_component` 연결 없는 부품 값을 쓰지 않는다.

### B-F. deepagents 시제품 비교 / B-G. 고객 회신

- 같은 모델·문서·10문항으로 두 엔진의 정답/근거/토큰/지연/도구 오류를 표로. 어느 쪽이 좋다고 미리 가정하지 않는다.
- ~~회신 연결: `In-Reply-To`가 있는 메일만 자동 연결. 다른 발신자의 같은 제목은 연결되지 않음. 인용문 아래 본문이 검색어에 섞이지 않음.~~ → 2026-11-13 사용자 결정으로 고객 회신 기능은 넣지 않는다. 검증 대상이 아니다. 단계 G는 고객 이력 조회와 담당자 메모만 본다 (통합 지시서 9절 T5의 G-1~G-3).

## C. 기준선 전후 비교 (개선 후, 개발 서버에서)

전제: 사용자가 제공한 개발 서버에 기준선이 참조한 문서 17개(`baseline_2026-11-12.json`의 `documents_referenced`)가 등록돼 있어야 한다. 먼저 `GET /files`로 대조하고 빠진 문서를 보고한다.

1. **문항 선정**: 103건 중 아래 10건을 우선 쓴다. 같은 질문이 반복된 SSD 대체품 시리즈(SSD2~SSD16)는 대표 1건만.
   - KC 인증서 요청 (`kc 인증서 보내줘`, 그래프 경로)
   - 인천공항 사전규격 대조 (첨부 PDF/HWP, 사양 비교)
   - 공군 입찰 규격 대조 (첨부 1건)
   - LLM 추론 서버 입찰 (첨부 2건, 문서 밖 지식 필요)
   - Essencore C910G 대체품 (xlsx 49,933자, 페이지 점프 필요)
   - Ti600s ↔ C910G 대체 가능 여부
   - 데스크탑 Sales Guide 요청 (문서 없음 → "찾지 못함"이 정답)
   - `RE:` 회신 2건 (`RE: [응답] 인천공항…`, `RE: [테스트][검토]SSD`) — 인용문 포함 본문
   - 주간판매 질문 1건 (xlsx 표)
2. **실행**: 각 문항의 `question`과 `attachments`를 개선된 서버에 같은 모드(`local`)로 보낸다. 메일 경로가 아니라 `/ask/attachments`를 쓰거나, 메일로 보낸 뒤 `drafted` 상태에서 `GET /mails/{id}`로 읽는다. **승인하지 않는다.**
3. **기록**: `after` 필드에 `answer, sources, trajectory(도구 호출 수·초·토큰)`를 채운다. 추출은 `export_baseline.py`와 같은 형식.
4. **지표** (문항별 표):
   - 근거 정확: 답변이 인용한 파일·페이지가 사람이 적은 `expected_evidence`와 일치하는가
   - 필수 키워드: `expected_keywords`가 답변에 있는가
   - 근거 없는 수치: 답변의 숫자 중 인용 근거 텍스트에 없는 것의 개수
   - 출처 건수: 기준선은 검색 히트(최대 86건), 개선 후는 읽은 페이지. 개수가 줄어든 것 자체는 FAIL이 아니다
   - 소요 시간·도구 호출 수·입출력 토큰
   - "찾지 못함"이 정답인 문항에서 지어내지 않았는가
5. **판정**: 문항별 PASS/FAIL과 기준선 대비 개선/동일/악화. 전체 평균을 먼저 쓰지 말고 문항별 표를 먼저 쓴다.

`expected_evidence`·`expected_keywords`는 사람(R&D 담당자)이 채운다. 비어 있으면 그 문항은 UNVERIFIED로 두고 지표 중 측정 가능한 것(시간·호출·근거 없는 수치)만 적는다.

## D. 보고 형식

```
# 검증 보고 <날짜> — 단계 <A~G 또는 C 비교>
## 요약: PASS n / FAIL n / UNVERIFIED n
## 표: 항목 | 판정 | 근거(파일:줄 또는 명령과 출력) | 비고
## FAIL 상세: 재현 절차, 기대, 실제
## UNVERIFIED 상세: 확인 못 한 이유, 필요한 것
## 문서 불일치: 합의 문서의 어떤 문장이 코드와 다른가
```

하지 말 것: 설계 대안 제안, 코드 수정, "아마도"로 끝나는 판정, 평균값만 있는 전후 비교.

### B-GR. 지식 그래프 정비 (2026-11-16)

항목별 통과 조건(GR-1 ~ GR-9)은 [opus_development_instructions_graph_rework.md](opus_development_instructions_graph_rework.md) 10절을 따른다.
