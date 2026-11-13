# Opus 보완 지시서 — 단계 C2 (A~C 미결 사항)

작성일: 2026-11-13
대상: 구현 담당 에이전트(Opus)
상위 문서: [opus_development_instructions.md](opus_development_instructions.md). **0장 작업 규칙(범위·커밋·금지·테스트·보고·언어)이 그대로 적용된다.**
범위: 아래 P1~P8만. 단계 D~H는 시작하지 않는다. 지시에 없는 리팩터링은 하지 않는다.
보고: 항목마다 `docs/dev_log/C2-P<번호>.md`, 끝나면 `docs/dev_log/C2-summary.md`.

---

## 1. 배경: 2026-11-13 실환경 확인 결과

A~C 구현 뒤 로컬 서버(재시작됨, 프롬프트 `v2 근거 ID` 선택됨)에서 실제 모델로 확인했다. Outlook 서버 장애 중이라 메일 수신 대신 `scripts/inject_test_mail.py`(커밋 `a6073fb`)로 대기 작업을 넣었다.

| 확인 | 결과 |
|------|------|
| `/ask` 질문 1건 | 6.4초. `graph_search` → `read_pages`. 근거 줄 인식, 검증 통과, run·checkpoint 저장 |
| 주입한 메일 작업 1건 (task `6b40acb4…`) | 6.5초, 도구 3회, 입력 19,584토큰, `drafted`, 검증 통과 |
| 같은 작업 반려 (문체 변경 사유) | **같은 대화로 재작성. 1.4초, 도구 0회, 입력 8,480토큰, 새 메시지 2개.** 검증 통과, `last_review_id=1` |
| 검토 알림 메일 | TLS 핸드셰이크 시간 초과 62.5초 → `send_failed`. 초안은 `drafted` 유지 (설계대로) |
| 전체 테스트 | 257 passed |

아직 확인하지 못한 것(코드 작업 아님, 사용자·Gemini 몫): 승인 발송과 `send_unknown` 분기(Outlook 복구 후), 첨부 읽기 실파일, 축약·요약이 걸리는 긴 대화, 사실 오류 반려 시 재검색, 기준선 10문항 전후 비교.

이 확인과 A~C dev_log의 "결정이 필요한 것"에서 아래 8건이 남았다.

---

## 2. 항목

우선순위 순서다. P1~P4는 반드시, P5~P8은 이어서 한다.

### P1. 발송 중 서버가 꺼진 작업 정리

- 문제: `sending` 상태에서 서버가 꺼지면 작업이 `sending`에 남고 화면에서 풀 방법이 없다 ([main.py:64](../main.py#L64)는 `processing`만 되돌린다).
- 결정: **프로세스 시작 시 `sending` → `send_unknown`.** 단일 프로세스이므로 시작 시점에 진행 중인 발송은 없다. 자동 재발송이 아니라 담당자 확인으로 넘기는 것이므로 합의(Q1)와 맞다.
- 할 일
  - `TaskRepository.mark_stale_sending() -> int`: 한 트랜잭션에서 `UPDATE tasks SET status='send_unknown' WHERE status='sending'`, 해당 task의 가장 최근 `task_send` 행 중 `outcome IS NULL`인 것을 `outcome='send_unknown', detail='서버 재시작으로 발송 결과를 확인할 수 없음'`으로.
  - `main.py` lifespan에서 `reset_processing()` 다음에 호출. 건수가 있으면 WARNING 로그.
  - 주석의 "sending은 되돌리지 않는다"를 "pending/drafted로 되돌리지 않고 send_unknown으로 넘긴다"로 고친다.
- 테스트: `sending` 1건 + 미완 `task_send` 1행 → 호출 후 `send_unknown`, `task_send.outcome` 채워짐. `sent`·`drafted`는 그대로. 승인 API가 그 작업을 다시 받을 수 있음(기존 `SENDABLE`).

### P2. 한 페이지가 길 때 이어 읽기

- 문제: `read_pages`·`read_attachment`는 한 번에 최대 20,000자(`MAX_READ_CHARS`)이고 페이지 안에서 시작 위치를 줄 수 없다. 한 페이지(xlsx 시트 등)가 그보다 길면 뒷부분에 도달할 수 없다 ([tools/tool.py:270](../tools/tool.py#L270) `read_page_texts`). 기준선에서 가장 많이 쓰인 `SSD_성능_비교.xlsx`가 전체 49,933자다.
- 할 일
  - 두 도구에 `offset: int = 0` 인자 추가. **`pages`가 정확히 1개일 때만** 허용하고, 2개 이상이면서 `offset > 0`이면 `{"error": "offset은 페이지 하나를 읽을 때만 쓸 수 있습니다"}`.
  - 잘린 페이지 항목에 `page_chars`(그 페이지 전체 글자 수)와 `next_offset`(이어 읽을 위치)을 넣는다. 끝까지 읽었으면 `next_offset` 없음.
  - 근거 등록은 지금처럼 **페이지 전체**다. offset이 달라도 같은 `evidence_id`가 나와야 한다.
  - 도구 docstring의 Returns에 "truncated이고 next_offset이 있으면 같은 페이지를 offset=next_offset으로 다시 읽는다"를 적는다. 잘림 안내 문구(`max_chars를 늘리거나…`)도 같이 고친다.
  - DB에 들어간 프롬프트(`v2 근거 ID`)는 건드리지 않는다. 안내는 docstring으로 충분하다.
- 테스트: 49,933자 한 페이지를 `max_chars=20000`으로 세 번(offset 0 → 20000 → 40000) 읽어 이어 붙이면 원문과 같다. 세 번 모두 같은 `evidence_id`. 페이지 2개 + offset → error. 첨부도 같은 동작.

### P3. 검토 화면에 실행 이력 전체

- 문제: `GET /mails/{id}`의 `trace`는 가장 최근 실행만이다 ([mails.py:126](../app/routers/mails.py#L126) `_latest_trace`). 반려 후 재작성이 도구를 안 부르면 목록이 비어, 담당자는 1차에서 무엇을 읽었는지 볼 수 없다. 오늘 확인한 task `6b40acb4…`가 그 상태다.
- 할 일
  - `run` 테이블에 `label TEXT` 컬럼(`_migrate`). `_invoke_logged`가 받은 `label`("메일(첨부 0건, 반려 없음)", "메일 반려 반영(review_id=1, 같은 대화)" 등)을 `start_run`에 넘겨 저장.
  - `EvidenceRepository.runs_for_owner(owner_type, owner_id) -> list[dict]` (시작 시각 오름차순).
  - 응답에 `runs: [{run_id, label, status, started_at, seconds, tokens_in, tokens_out, tool_calls: [{tool, args_summary, at}]}]` 추가. 기존 `trace`는 호환용으로 남긴다.
  - `MailReviewPage.tsx`: "에이전트가 한 일"을 실행별 묶음으로. 머리줄 예: `1차 초안 · 도구 3회 · 6.5초`, `반려 반영 · 도구 0회 · 1.4초`. 도구 0회인 실행에는 "이전에 읽은 근거로 재작성"이라고 표시. 최신 실행이 펼쳐지고 나머지는 접힘.
  - `frontend/src/mail/types.ts`에 타입 추가.
- 테스트: 실행 2건(1차 도구 3회, 2차 0회)인 task → `runs` 2개, 순서·label·도구 수 일치. `label`이 NULL인 예전 run도 깨지지 않음.

### P4. 검토 알림이 메일 처리 루프를 막지 않게

- 문제: `_notify_reviewer`가 처리 루프 스레드에서 동기 호출된다 ([email_service.py](../mail/email_service.py) `email_consumer_loop`). 메일 서버 장애 중에는 초안마다 60초 넘게(`SMTP_TIMEOUT_SECONDS=60`, 오늘 실측 62.5초) 다음 작업이 밀린다.
- 할 일
  - 알림을 별도 데몬 스레드(`name="mail-notify"`)에서 보낸다. 초안은 이미 저장된 뒤이므로 순서 문제는 없다. 스레드 안의 예외·실패 로그는 지금 문구 그대로.
  - `send_email(..., timeout: float | None = None)` 인자 추가. 알림은 `config.NOTIFY_SMTP_TIMEOUT_SECONDS`(기본 20), 승인 발송은 기존 60 유지.
  - 종료 시 알림 스레드는 기다리지 않는다(데몬).
- 테스트: 발송 대역이 5초 멈추는 상황에서 대기 작업 2건을 처리 루프에 넣으면, 두 번째 작업의 초안 저장이 첫 알림 종료보다 먼저 일어난다. 알림 실패 뒤에도 두 작업 모두 `drafted`.

### P5. 생성 실패 작업 재시도 API

- 문제: 검토 화면은 `failed` 상태에서 "재전송" 버튼을 보여 주고 `POST /mails/{id}/retry`를 부르는데 ([MailReviewPage.tsx:316](../frontend/src/mail/pages/MailReviewPage.tsx#L316)) 백엔드에 그 API가 없어 404다. `failed`는 이제 "답변 생성 실패" 전용이므로 버튼 이름도 맞지 않는다.
- 할 일
  - `POST /mails/{task_id}/retry`: `failed`일 때만 `pending`으로 (조건부 UPDATE, 아니면 409). 응답 `{task_id, status}`. `task_reviews`에 `action='retry'`를 남긴다 (CHECK 제약은 A4의 재생성 방식 그대로 확장).
  - 재시도 실행 경로 (`run_agent_temp_attachments`): 대화 기록이 있고 반려가 없을 때 지금은 `invoke(None)`으로 재개한다. 그런데 이전 실행이 **끝난 상태**(예: 모델 호출 한도로 종료, 빈 답변)면 재개해도 같은 결과가 나온다. 그래서 `agent.get_state(config).next`가 비어 있으면(그래프가 끝난 상태) 새 user 메시지 `"[재시도] 이전 실행이 답변 없이 끝났습니다. 이미 읽은 근거로 답변을 작성하고, 부족하면 필요한 부분만 더 읽으세요."`를 ID `retry:{thread_id}:{n}`으로 넣는다. `next`가 남아 있으면(중간에 끊김) 지금처럼 `invoke(None)`.
  - 단, 마지막 메시지가 정상 답변인 채로 끝난 경우(답변 생성 뒤 저장 전 종료, C4의 경우)는 지금 동작(그 답변을 검증·저장)을 유지한다. 구분 기준: 마지막 AI 메시지가 `MODEL_LIMIT_MESSAGE_PREFIX`로 시작하거나 비었으면 "답변 없이 끝남".
  - 프론트: 버튼 이름 "재전송" → "다시 생성", 완료 문구에서 `res.to` 제거("다시 생성을 요청했습니다").
- 테스트: `failed` → retry 200 → `pending`. `drafted`에서 retry → 409. 한도로 끝난 thread를 재시도하면 재시도 메시지가 1개 들어가고 답변이 저장됨. 같은 재시도를 두 번 처리해도 메시지 1개.

### P6. 웹 질문의 대화·근거 정리

- 문제: `/ask`는 호출마다 `ask:{uuid}` 대화를 `storage/agent_threads.db`에 만들고 지우지 않는다. `_thread_locks`에도 항목이 남는다. `owner_type='session'`인 evidence·run도 `mail.db`에 계속 쌓인다 (C-C1 dev_log 5번).
- 할 일
  - `run_agent`·`run_agent_temp_attachments`: thread_id가 `ask:`로 시작하면 실행이 끝난 뒤(성공·실패 모두, `finally`) `checkpointer.delete_thread(thread_id)`와 `_thread_locks.pop`. `task:` 대화는 절대 지우지 않는다.
  - `EvidenceRepository.purge_sessions(older_than_days) -> dict`: `owner_type='session'`이고 `created_at`/`started_at`이 기준보다 오래된 evidence, evidence_use, run 삭제. `owner_type='task'`는 건드리지 않는다.
  - `config.SESSION_EVIDENCE_RETENTION_DAYS`(기본 14). `main.py` lifespan 시작 시 한 번 호출하고 삭제 건수를 INFO로.
- 테스트: `/ask` 경로 실행 후 그 thread의 checkpoint 0건, `task:` thread는 남음. 30일 전 session 근거는 지워지고 어제 것과 task 근거는 남음.

### P7. 메일 수신 스레드가 종료를 막지 않게

- 문제: 2026-11-13 10:38 서버 종료 때 `종료 대기 시간 안에 끝나지 않은 스레드: ['mail-receiver']` 경고가 났다. [email_receiver.py:311](../mail/email_receiver.py#L311) `poplib.POP3_SSL(POP3_SERVER, POP3_PORT)`에 timeout이 없어 서버 장애 중 무기한 대기할 수 있다. (원인은 추정이다. 먼저 코드로 확인하고 dev_log에 적는다.)
- 할 일
  - `poplib.POP3_SSL(..., timeout=config.POP3_TIMEOUT_SECONDS)` (기본 30).
  - `msal.PublicClientApplication(..., timeout=30)`로 토큰 요청에도 시간 제한.
  - 대화형 로그인(`acquire_token_interactive`) 흐름은 바꾸지 않는다. 최초 1회 인증에 쓰인다.
  - 수신 스레드를 데몬으로 바꾸지 않는다. 시간 제한으로 해결한다.
- 테스트: `poplib.POP3_SSL` 대역이 `TimeoutError`를 던지면 `fetch_new_emails`가 빈 목록을 돌려주고 예외를 올리지 않음. 생성자에 timeout이 전달됨.

### P8. 내용이 없는 첨부를 매번 다시 파싱하지 않게

- 문제: 파싱 결과가 0페이지인 첨부는 `attachment_page`에 행이 없어 읽을 때마다 다시 파싱한다 ([tools/tool.py](../tools/tool.py) `attachment_page_texts`, B-B4 dev_log).
- 할 일: 0페이지면 표시 행 하나(`seq=0, page=0, text=''`)를 저장하고, `attachment_page_texts`는 `page=0`이고 본문이 빈 행을 결과에서 뺀다. `read_attachment`는 이 경우 `{"error": "이 첨부에서 추출된 텍스트가 없습니다"}`. 안내 줄의 페이지 수는 0.
- 테스트: 빈 파싱 결과 첨부를 두 번 읽어도 파서 대역 호출 1회.

---

## 3. 하지 않는 것

- D~H 단계의 어떤 작업도 시작하지 않는다 (고객방 화면, 사양 도구, deepagents, 고객 회신, 그래프의 사양 DB 참조).
- `/ask`에 멀티턴(thread_id 입력)을 넣지 않는다. P6은 정리만 한다.
- DB에 저장된 프롬프트 내용을 바꾸지 않는다.
- `MAX_READ_CHARS`(20,000), 실행 한도(검색 6·도구 25·모델 20), `recursion_limit`(200), 맥락 예산(24,000/40,000)을 바꾸지 않는다. 바꿀 근거가 생기면 dev_log에 측정값과 함께 "제안"으로 적는다.
- 실제 메일을 보내지 않는다. `scripts/inject_test_mail.py`로 운영 DB에 작업을 넣어 확인하지 않는다 (사용자가 한다).

## 4. 사용자 확인 사항 (코드 아님, 참고)

- `PUBLIC_BASE_URL`이 `http://192.168.0.184:8000`인데 서버는 `localhost:8000`으로만 떠 있다. 검토 알림과 주입 스크립트가 출력하는 링크가 다른 PC에서 열리지 않는다.
- `frontend/dist`는 2026-11-05 빌드다. 8000 포트 화면에는 발송 상태·검증 경고·작업 내역이 없다. `npm run build` 필요.
- Outlook 복구 뒤 승인 발송 1건으로 새 SMTP 경로(`mail`/`rcpt`/`data` 직접 호출)를 확인한다.
- `tests/eval/eval_set.json`의 `expected_evidence`·`expected_keywords`를 R&D 담당자가 채운다.

## 5. Gemini 검증 항목 (C2)

[gemini_verification_instructions.md](gemini_verification_instructions.md)의 규칙(읽기 전용, PASS/FAIL/UNVERIFIED, 근거 첨부)을 따른다.

| 항목 | PASS 조건 |
|------|-----------|
| P1 | 서버 시작 직후 `sending` 0건. 되돌린 작업이 `send_unknown`이고 화면에서 "발송 확인됨"·"재발송"이 가능. 자동 재발송 코드 없음 |
| P2 | 20,000자를 넘는 한 페이지를 `next_offset`으로 끝까지 읽을 수 있고 `evidence_id`가 같음. 여러 페이지 + offset은 거부 |
| P3 | 반려 후 재작성된 작업의 상세 응답 `runs`에 1차 실행의 도구 호출이 남아 있음. 화면에서 실행별로 구분돼 보임 |
| P4 | 알림 발송이 멈춰도 다음 대기 작업의 초안 저장이 지연되지 않음. 알림 실패 시 상태는 `drafted` |
| P5 | `failed`에서만 retry 가능. 한도로 끝난 작업을 재시도하면 같은 "한도 초과"가 반복되지 않고 답변이 저장됨. 재시도 메시지 중복 없음 |
| P6 | `/ask` 뒤 `agent_threads.db`에 `ask:` thread가 남지 않음. `task:` thread와 task 근거는 삭제되지 않음 |
| P7 | POP3 연결·토큰 요청에 시간 제한이 걸려 있음. 장애 대역에서 서버 종료가 5초 대기 안에 끝남 |
| P8 | 빈 첨부를 두 번 읽어도 파싱 1회 |
| 회귀 | `pytest tests -q` 전부 통과 (시작 시점 257). 프론트 `npx tsc -b`, `npx eslint src/mail` 통과 |
