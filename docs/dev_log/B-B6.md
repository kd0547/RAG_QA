# B-B6 작은 서버 검증과 실행 기록

## 변경 파일
- `agent/validation.py`(신규): `ValidationResult`, `split_evidence_line`, `validate_answer(run_id, owner, answer)`
- `agent/agent.py`
  - `_invoke_logged`: 콜백(`_ToolTrace`)으로 도구 호출 `{tool, args_summary(200자), at}` 수집, AI 메시지 `usage_metadata`로 토큰 합계. `finish_run`에 기록
  - 예외 → `error`, `GraphRecursionError` → `limit`, 마지막 메시지가 AI 본문이 아니거나 비면 `error`("빈 답변") 후 `AgentRunError`. 모두 다시 던진다
  - `_finish_answer`: 검증 → 근거 줄을 뺀 본문, 출처, `validation`
  - `check_answerability`를 `TOOLS`에서 제거
- `tools/tool.py`: `check_answerability`와 판정 프롬프트 제거. `agent/type.py`(AnswerabilityCheck) 삭제
- `agent/prompt.py`: check_answerability 단계 삭제, 출력 형식에 "마지막 줄 `근거: …`" 추가 (B7에서 전면 교체)
- `storage/schema.sql`, `repository/repo_connect.py`: `tasks.validation_json`
- `repository/task_repository.py`: `save_draft(…, validation=None)`, `get_validation`
- `mail/email_service.py`: 검증 결과 저장, errors면 WARNING 로그
- `app/routers/mails.py`, `app/routers/questions.py`: 응답에 `validation`
- `frontend/src/mail/types.ts`, `MailReviewPage.tsx`: `DraftValidation`, 검토 화면 경고 박스 (errors: "근거 검증 경고", warnings만: "근거 확인 필요"). 문제가 없으면 아무것도 표시하지 않는다
- `tests/test_validation.py`(신규), `tests/test_search_tools.py`·`test_email_consumer.py`·`test_mail_list.py` 갱신

## 결정한 것
1. **근거 줄 인식:** 마지막 비어 있지 않은 줄이 `근거:`(전각 `：`, `**근거**:` 허용)로 시작해야 한다. 값이 `없음`이면 "근거 없음 선언". 쉼표·공백으로 나눈 항목 중 `e`+16진수가 아닌 것은 warning("근거 ID 형식이 아님").
2. **인용 기록:** 소유자 확인을 통과한 ID는 이 실행에서 읽지 않았더라도(warning) `cite`로 기록한다. 소유자가 다른 ID는 기록하지 않는다.
3. **근거 줄이 없고 읽은 것도 없으면** errors("근거를 읽지 않고 답변") + warnings("근거 줄 없음"). 지시서 4번 "'근거: 없음'이 아닌데"에 근거 줄이 없는 경우도 포함했다.
4. **`AgentRunError`는 `RuntimeError`의 하위 클래스.** `/ask`는 기존대로 `RuntimeError`를 503으로 돌려준다. 메일 소비자는 예외를 받아 `failed`로 둔다 (기존 동작, 테스트 추가).
5. **검증 결과 화면 표시를 B6에서 넣었다.** 지시서 B6 "검토 화면 상단에 경고 배지"에 따라 넣었다. C5의 `validation` 추가와 겹치는 부분이다. "검증 완료" 같은 문구는 쓰지 않는다.
6. **프롬프트에 근거 줄 규칙을 B6에서 먼저 한 줄 넣었다.** 검증이 이 줄을 전제로 하기 때문이다. 같은 날 B7에서 프롬프트 전체를 바꿨다.
7. **`tool_calls_json`의 `at`은 도구 시작 시각** (`on_tool_start` 콜백).

## 테스트: 명령과 출력
```
.venv/Scripts/python.exe -m pytest tests/test_validation.py -v

tests/test_validation.py::test_split_evidence_line PASSED                [ 10%]
tests/test_validation.py::test_other_owners_id_is_error PASSED           [ 20%]
tests/test_validation.py::test_fact_answer_without_reading_is_error PASSED [ 30%]
tests/test_validation.py::test_declared_none_without_reading_is_ok PASSED [ 40%]
tests/test_validation.py::test_valid_citation_is_recorded PASSED         [ 50%]
tests/test_validation.py::test_end_to_end_answer_is_stripped_and_cited PASSED [ 60%]
tests/test_validation.py::test_empty_answer_raises_and_records_error PASSED [ 70%]
tests/test_validation.py::test_recursion_limit_is_recorded_as_limit PASSED [ 80%]
tests/test_validation.py::test_consumer_marks_failed_not_drafted_when_run_fails PASSED [ 90%]
tests/test_validation.py::test_validation_is_saved_and_shown_in_mail_detail PASSED [100%]

============================== 10 passed in 6.58s ==============================
```
지시서 테스트 대응: 남의 ID 인용 → errors 1건 (`test_other_owners_id_is_error`) / read 0건 + 사실 답변 → errors (`test_fact_answer_without_reading_is_error`) / `근거: 없음` + read 0건 → ok (`test_declared_none_without_reading_is_ok`).

화면: 개발 서버에서 `fetch` 대역으로 errors 1건·warnings 1건인 초안을 열었다. "근거 검증 경고" 박스에 두 줄, 출처 제목 "답변이 인용한 근거 1", 승인 버튼은 그대로임을 확인했다.

## 확인하지 못한 것 / Gemini에게 요청할 검증
- 로컬 vLLM 모델(qwen)이 마지막 줄 `근거: e…` 형식을 지키는지는 실제 모델로 확인하지 않았다. 지키지 않으면 모든 초안에 "근거 줄 없음" 경고가 붙는다 (저장·승인은 막지 않음).
- `usage_metadata`를 vLLM(OpenAI 호환)이 채워 주는지 확인하지 않았다. 없으면 토큰은 NULL이다.

## 커밋 해시
- `c29e89d`
