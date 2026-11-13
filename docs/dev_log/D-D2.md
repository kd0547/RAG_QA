# D-D2 고객방 API (조회 전용)

## 변경 파일
- `repository/customer_repository.py`(신규) `CustomerRepository`
  - `list_customers(q, limit, offset)`, `timeline(sender, limit, before)`
  - `parse_time`: 시간대 없는 값은 서버 지역 시각으로 보고(`naive.astimezone()`) 시간대 있는 `datetime`으로 바꿔 비교. 응답은 저장 문자열 그대로
  - `NEEDS_REVIEW_STATUSES = (drafted, in_review, sending, send_failed, send_unknown, failed)` (프론트 `REVIEW_STATUSES`와 같음)
  - 본문(`body`·`answer`·`reason`) 8,000자 자름 + `truncated`
- `app/routers/customers.py`(신규): `GET /customers`, `GET /customers/{sender}/timeline` (없는 발신자 404, 읽을 수 없는 `before` 400)
- `repository/__init__.py`: `customer_repo`
- `main.py`: 라우터 등록(SPA catch-all 앞), catch-all의 API 접두어 목록에 `customers` 추가 (없는 `/customers/...` 요청에 index.html 대신 404)
- `tests/test_customers.py`(신규) 14건

## 결정한 것
1. **조회 방식:** 발신자 목록은 메일 전체(`mails` LEFT JOIN `tasks`)를 한 번 읽어 파이썬에서 묶는다. 시간대가 섞인 `received_at`을 SQL `MAX/ORDER BY`(문자열 비교)로 고르면 순서가 틀리기 때문이다. 운영 128건 기준 1ms. 타임라인은 발신자의 문의를 한 번 읽고, 고른 문의의 실행·검토·발송·첨부를 각각 `IN (…)` 한 번씩 읽는다.
2. **`q`:** 주소가 맞거나, 그 고객의 메일 제목 중 하나라도 맞으면 그 고객을 넣는다. 건수·상태 집계는 검색과 관계없이 그 고객의 전체 메일 기준.
3. **`running` 실행**은 사건으로 내보내지 않는다 (사건 표에 없음). 진행 중인 문의는 상태 칩(`processing`)으로 보인다.
4. **초안 본문 규칙 3**(본문 기록 없음)이면 `answer: null`, `text_source: null`.
5. **추정 발송(`inferred` send)의 `recipient`는 `null`.** 기록이 없어 누구에게 보냈는지 모른다.
6. **`next_before`**는 이번에 고른 문의 중 가장 오래된 것의 `received_at`이고, 그보다 이전 문의가 있을 때만 준다. 수신 시각이 완전히 같은 두 문의가 페이지 경계에 걸리면 하나가 빠질 수 있다 (지시서의 `before` 방식 그대로).
7. **발송 첨부(`task_send.attachments_json`)**에는 `path`가 들어 있어 `filename`만 꺼낸다.
8. 실행 기록이 있지만 `ok` 실행이 하나도 없는 옛 작업은, `draft_answer`가 있어도 추정 초안을 만들지 않는다 (지시서 조건 "실행 기록이 하나도 없는데" 그대로).

**수신 계정:** 지금은 수신 계정이 하나라 `mails`에 컬럼을 추가하지 않았다. 계정 구분은 단계 G에서 메일 헤더 컬럼과 함께 넣는다.

**모델 입력과 분리:** `agent/`, `tools/`, `mail/email_service.py`는 `customer_repository`를 임포트하지 않는다 (테스트로 검사).

## 테스트: 명령과 출력
```
.venv/Scripts/python.exe -m pytest tests/test_customers.py -q
14 passed in 7.36s

.venv/Scripts/python.exe -m pytest tests -q
300 passed in 36.64s
```
| 지시서 테스트 | 테스트 |
|---|---|
| 발신자 둘 따로, 대소문자만 다른 주소 합침 | `test_senders_listed_separately_and_case_merged` |
| received → draft → reject → draft → send | `test_event_order_received_draft_reject_draft_send` |
| 옛 작업의 inferred 초안·발송 | `test_legacy_task_gets_inferred_draft_and_send` |
| 같은 발신자의 문의 둘이 다른 묶음 | `test_two_inquiries_are_separate_groups_oldest_first` |
| 시간대 섞인 시각 순서 | `test_mixed_timezone_received_at_order` |
| before로 이어 가져오기, 겹침 없음 | `test_before_pages_older_inquiries_without_overlap` |
| 디스크 경로·`data:` 없음 | `test_no_disk_path_or_image_data` (도구 호출도 없음) |
| 없는 발신자 404 | `test_unknown_sender_404_and_bad_before_400` |
| B 실행 입력에 A 본문·초안 없음 | `test_other_inquiry_not_in_model_input` (대역 모델이 받은 시스템 프롬프트+메시지 전체) |
| (추가) 같은 시각 순서, 실패·재시도, 본문 없는 옛 실행, 검색·페이지, 8,000자 자름 | 나머지 5건 |

**운영 DB 읽기 전용 실행** (`mode=ro` 연결로 저장소 함수만 호출, 주소는 가림):
```
list 0.001s
don*** 38  2026-09-17T15:58:32+09:00  2026-11-13T10:45:55.644742  {'sent': 9, 'failed': 3, 'drafted': 26}  29
jmp*** 88  2026-09-22T10:53:06+09:00  2026-11-03T17:39:44+09:00   {'sent': 5, 'drafted': 62, 'failed': 21} 83
api*** 2   2026-09-17T15:55:32+09:00  2026-10-19T14:25:12+09:00   {'drafted': 2}                           2
timeline 0.001s  total 38, next_before 2026-10-08T13:32:16+09:00, 문의 20개
사건: received 20, draft(추정) 18, send(추정) 3, draft 2, reject 1   — data:/stored_path 없음
```
시간대 없는 `2026-11-13T10:45:55.644742`가 시간대 있는 값들보다 최근으로 올바르게 정렬됐다.

## 사고: 운영 DB에 컬럼 2개가 추가됨 (규칙 위반, 보고)
- 위 "운영 DB 읽기 전용 실행" 스크립트는 `mode=ro` 연결을 넘겼지만, `from repository.customer_repository import …`가 패키지 `repository/__init__.py`를 먼저 실행했다. `__init__`이 운영 `storage/mail.db`를 열고 `_migrate`를 돌려 **운영 `run` 테이블에 `answer TEXT`, `skills_json TEXT` 컬럼이 추가됐다** (2026-11-13 12:26, 파일 수정 시각).
- 영향: 값이 모두 NULL인 컬럼 추가뿐이다. 행·다른 테이블은 바뀌지 않았다 (나머지 마이그레이션은 이미 적용된 상태라 아무것도 하지 않음). D1 코드로 서버를 다시 시작하면 같은 ALTER가 적용될 예정이었다. 지금 떠 있는 서버(C2 코드)는 `run`을 `SELECT *`로 읽어도 화면 응답이 필드 목록(`_RUN_FIELDS`)으로 걸러져 동작이 같다.
- 되돌리지 않았다: `DROP COLUMN`도 운영 DB 쓰기이고, 재시작 때 다시 추가된다.
- 이후 조치: 운영 DB 점검은 저장소 모듈을 임포트하지 않고 `sqlite3` `mode=ro` SQL로만 한다. D3·D4 화면 확인용 백엔드는 운영 DB 연결을 사본으로 돌린 **뒤에** 임포트했다 (사본은 확인 후 삭제).

## 확인하지 못한 것 / Gemini에게 요청할 검증
- 실서버 엔드포인트는 재시작 전이라 확인하지 않았다 (사용자 uvicorn은 `--reload` 없음).

## 커밋 해시
- (summary에 기록)
