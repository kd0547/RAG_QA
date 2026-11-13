# I-I3 문의 분석

## 변경 파일
- `agent/request_analysis.py`(신규)
  - `AnalysisOutput{type_id, new_type{label, description}, covered_by, reason}` (pydantic, 구조화 출력)
  - `build_messages`: 시스템 프롬프트(규칙 + 유형 목록 `type_id | label | description` + 선택 절차 목록) / user(`<메일>` 제목·첨부 파일명·본문 앞 3,000자 `</메일>`). 자료 안의 `<메일>`·`</메일>` 표시는 지운다
  - `check_output`: 없는 `type_id`는 무효, merged는 `merged_into`를 따라감, `new_type` label 30자·description 200자·한 줄, label이 기존 유형과 같으면(공백·대소문자 무시) 그 유형, `covered_by`가 사용 중 선택 절차(메일 채널, 저장소 + DB 승인본)가 아니면 null, 둘 다 없으면 무효
  - `analyze_task`: 모델 호출 → 검사 → 무효면 사유를 알려 주고 한 번 다시 → 또 무효면 `status='error'`. 모델 예외도 `error`로 저장하고 다시 던지지 않는다
  - `used_skills`: 그 task의 모든 실행에서 `run.skills_json` 이름 + `load_skill` 호출 인자 `name` (처음 나온 순서)
  - `run_cycle`: 꺼져 있으면 아무것도 안 함, 대기·처리 중 task가 있으면 쉼, 아니면 대상 최대 `REQUEST_ANALYSIS_BATCH`건 (건마다 대기 작업을 다시 확인)
  - `analyzer_loop`/`start_analyzer`: 데몬 스레드 `request-analyzer`, `stop_event.wait(주기)` 후 한 주기. 주기 예외는 로그만 남기고 계속
- `repository/skill_repository.py`: `waiting_task_count`, `tasks_to_analyze(limit, max_attempts=3)`(상태 `drafted, in_review, sending, sent, send_failed, send_unknown`, 분석 없음 또는 error·attempts<3, `tasks.created_at` 최근 순), `analysis_input`(파일명만), `get_analysis`, `save_analysis`(덮어쓰기, attempts+1)
- `config.py`: `REQUEST_ANALYSIS_ENABLED`(1), `REQUEST_ANALYSIS_INTERVAL_SECONDS`(30), `REQUEST_ANALYSIS_BATCH`(5), `REQUEST_ANALYSIS_TIMEOUT_SECONDS`(120), `SKILL_DRAFT_TIMEOUT_SECONDS`(300), `SKILL_DRAFT_MIN_CASES`(3), `SKILL_DRAFT_AUTO`(1)
- `main.py`: 메일 스레드 다음에 `start_analyzer()`, 종료 때 `analyzer_stop.set()` → `join(5)`
- `tests/test_request_analysis.py`(신규) 10건

## 결정한 것
1. **시간 제한**: 구조화 출력 체인의 `invoke(messages, timeout=…)`로 넘긴다. `RunnableSequence`는 첫 단계(모델 바인딩)에 kwargs를 넘기고, `ChatOpenAI._get_request_payload`가 그 값을 요청 payload에 넣어 OpenAI 클라이언트의 요청별 `timeout`이 된다 (vLLM 호환). 실제 vLLM에서 시간 초과가 나는지는 I7에서 본다.
2. **선택 절차 목록은 메일 채널 기준**(`selectable_skills("mail")`)이다. 분석 대상이 메일 task뿐이라서다. 서버 적용 절차(`mail-reply-style` 등)는 목록에 없어 `covered_by`로 고를 수 없다.
3. 대상 순서의 "최근"은 `tasks.created_at`이다. `mails.received_at`은 시간대가 섞여 있어(D 지시서 1절) 문자열 정렬이 틀릴 수 있다.
4. 모델이 `type_id`와 `new_type`을 둘 다 주면 `type_id`를 쓴다 (기존 유형 우선 규칙).
5. 새 유형은 검사를 통과한 뒤, 저장 직전에 만든다. 무효 출력 두 번으로 `error`가 된 분석은 유형을 만들지 않는다.
6. 스레드는 시작 직후가 아니라 첫 주기(30초) 뒤에 처음 돈다. 서버 시작 때 `processing` → `pending`으로 되돌린 메일이 먼저 처리되게 하려는 것이다.
7. 분석 스레드는 데몬이다. 종료 때 5초 기다리고, 모델 호출 중이면 남은 스레드 목록에 이름이 찍힌다.

## 테스트: 명령과 출력
```
.venv/Scripts/python.exe -m pytest tests/test_request_analysis.py -v
tests/test_request_analysis.py::test_existing_type_and_covered_by_are_saved_with_used_skills PASSED [ 10%]
tests/test_request_analysis.py::test_new_type_is_created_and_same_label_attaches PASSED [ 20%]
tests/test_request_analysis.py::test_server_checks_filter_bad_output PASSED [ 30%]
tests/test_request_analysis.py::test_merged_type_follows_merged_into PASSED [ 40%]
tests/test_request_analysis.py::test_two_invalid_outputs_leave_error_and_task_status PASSED [ 50%]
tests/test_request_analysis.py::test_targets_are_answered_tasks_recent_first PASSED [ 60%]
tests/test_request_analysis.py::test_cycle_rests_while_mail_is_waiting PASSED [ 70%]
tests/test_request_analysis.py::test_cycle_analyzes_at_most_batch PASSED [ 80%]
tests/test_request_analysis.py::test_mail_instructions_cannot_push_values_out_of_range PASSED [ 90%]
tests/test_request_analysis.py::test_analyzer_thread_survives_exceptions_and_mail_loop_still_works PASSED [100%]

============================= 10 passed in 6.68s ==============================

.venv/Scripts/python.exe -m pytest tests -q
335 passed in 42.13s
```

## 확인하지 못한 것 / Gemini에게 요청할 검증
- 실제 로컬 모델(vLLM)의 구조화 출력 품질과 건당 시간: I7 (서버 재시작 뒤).
- I-6(메일 본문의 지시문): `test_mail_instructions_cannot_push_values_out_of_range` — 대역 모델이 지시를 그대로 따라도 유형 이름·설명은 길이·한 줄로 잘리고, 서버 적용 절차를 `covered_by`로 넣지 못하고, `skill_doc`에 행이 생기지 않는다.
- I-7·I-8: `test_two_invalid_outputs_leave_error_and_task_status`, `test_analyzer_thread_survives_exceptions_and_mail_loop_still_works`, `test_cycle_rests_while_mail_is_waiting`.

## 커밋 해시
(I-summary.md에 적는다)
