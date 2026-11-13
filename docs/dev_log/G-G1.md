# G-G1 고객 이력 도구와 담당자 메모

범위: 통합 지시서 5절. 고객 회신 기능(메일 헤더 저장, 발신 Message-ID, 대화 자동 연결, 인용문 분리, 회신 작업에 이전 대화 붙이기, 연결 후보)은 사용자 결정으로 **넣지 않았다.** `mail/` 아래 파일은 바꾸지 않았다 (메일 수신·발송 경로 그대로).

## 변경 파일
- `storage/schema.sql`: `customer_note(note_id, sender, text, created_at, created_by, retired_at)` + 인덱스 `(sender, retired_at)`
- `repository/customer_history_repository.py`(신규) `CustomerHistoryRepository`
  - 메모: `list_notes`, `add_note`(1~500자, 발신자 키 `LOWER(TRIM(sender))`), `retire_note`(지우지 않고 `retired_at`)
  - 이력: `sender_for_task`, `history_for_task(task_id, days, limit)`, `counts_for_task(task_id, days)`
- `repository/__init__.py`: `customer_history_repo`
- `config.py`: `CUSTOMER_HISTORY_ENABLED`(기본 켬), `CUSTOMER_HISTORY_DAYS`(기본 90)
- `tools/tool.py`: `get_customer_history(limit=10)`
- `agent/agent.py`
  - `active_tools()`: 설정이 켜져 있으면 `get_customer_history`
  - `customer_history_hint(owner)`: 메일이고 이전 문의나 메모가 있으면 `[이 발신자의 이전 문의 N건, 담당자 메모 M건이 있다. 필요하면 get_customer_history로 본다]`
  - `run_agent_temp_attachments`: **첫 user 메시지**(대화 기록이 없을 때)의 맨 끝에 안내 줄을 붙인다. 반려·재시도·재개 메시지에는 붙이지 않는다
- `app/routers/customers.py`: `GET /customers/{sender}/notes`, `POST /customers/{sender}/notes`(`created_by`는 요청 IP), `POST /customers/{sender}/notes/{note_id}/retire`
- `tests/conftest.py` `agent_env`: `customer_history_repo`도 임시 DB로
- `tests/test_customer_history.py`(신규) 12건

## 도구가 돌려주는 것
```
{days, inquiry_total, inquiries: [{received_at, subject, request_type, reason, status}], notes: [{text, created_at}], note}
```
- 발신자는 인자로 받지 않는다. 서버가 현재 작업(`current_owner()`)의 메일 발신자로 조회한다. 웹 질문·실행 컨텍스트 밖이면 `"오류: …"` 문자열
- 같은 발신자의 **다른** 문의만 (현재 작업 제외), 최근 것부터, `CUSTOMER_HISTORY_DAYS`(90일) 안의 것만. 수신 시각은 고객방과 같은 `parse_time`으로 비교한다 (시간대 섞임)
- `request_type`: 문의 분석이 `ok`일 때 유형 이름 (합쳐진 유형은 옮겨 간 유형). `reason`: 분석 사유를 한 줄로(200자)
- `status`: `sent` → 답변 발송됨, `failed` → 생성 실패, 그 밖 → 검토 중
- 메일 본문, 초안, 반려된 초안, 발송 본문은 싣지 않는다
- 근거를 등록하지 않는다 (인용할 수 없다). 결과에 "참고 자료이며 근거가 아닙니다" 안내
- 축약 제외 목록(`exclude_tools`)에 넣지 않았다

## 결정한 것
1. **저장소 이름과 위치.** 고객방 저장소(`customer_repository`)는 본문·초안·발송까지 돌려주고, D 단계에서 "모델 쪽 코드(agent/, tools/)는 이 모듈을 임포트하지 않는다"를 테스트로 묶었다. 그 경계를 지키려고 모델에 보여 줄 수 있는 것만 돌려주는 별도 저장소를 만들었다. 시각·발신자 키 함수(`parse_time`, `sender_key`)만 고객방 저장소에서 가져온다 (저장소 계층 안의 임포트).
2. 문의 = 작업(task)이 있는 메일. 작업이 없는 메일은 이력에 넣지 않는다.
3. 이전 문의가 0건이고 메모도 0건이면 안내 줄을 붙이지 않는다. 하나라도 있으면 두 건수를 모두 적는다.
4. 안내 줄은 첫 user 메시지의 첨부 안내 뒤, 맨 끝에 둔다.
5. 사용 중지한 메모는 화면 목록에는 남고(흐리게) 도구·건수에는 들어가지 않는다.

## 테스트: 명령과 출력
```
.venv/Scripts/python.exe -m pytest tests/test_customer_history.py -q
12 passed in 7.25s

.venv/Scripts/python.exe -m pytest tests -q
449 passed in 59.56s
```
| 지시서 테스트 | 테스트 |
|---|---|
| 다른 발신자의 문의를 돌려주지 않는다. 인자로 발신자를 바꿀 수 없다 | `test_history_is_same_sender_only_recent_and_has_no_bodies`, `test_sender_cannot_be_changed_by_arguments` (도구 인자는 `limit`뿐, `sender`를 넣어도 무시) |
| 91일 전 문의는 나오지 않는다. 응답에 메일·초안·발송 본문이 없다 | `test_history_is_same_sender_only_recent_and_has_no_bodies` (91일 전 제외·89일 전 포함, 본문 문자열 9개 검사), `test_days_setting_and_limit` |
| 사용 중지한 메모는 나오지 않는다 | `test_retired_notes_are_hidden` |
| 같은 발신자의 A, B에서 B 실행의 메시지·시스템 프롬프트에 A 본문·답변이 없다. 안내 줄에는 건수만 | `test_next_inquiry_gets_count_line_only` (메일 처리 루프로 A·B를 차례로, 메모 본문도 없음) |
| 웹 질문에서 오류 문자열 | `test_web_question_gets_error_string` |
| `CUSTOMER_HISTORY_ENABLED=false`면 도구와 안내 줄이 없다 | `test_flag_off_removes_tool_and_hint` |
| (추가) 근거 등록 안 함, 모델이 읽고 `근거: 없음`으로 답하면 통과, 축약 제외 목록에 없음, 메모 API·검증·다른 발신자 메모 404 | 나머지 |

D 단계 테스트 `test_model_side_code_does_not_import_customer_repository`와 `test_other_inquiry_not_in_model_input`도 그대로 통과한다.
