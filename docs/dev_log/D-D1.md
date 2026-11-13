# D-D1 실행별 초안 본문과 적용 절차 기록

## 변경 파일
- `storage/schema.sql`: `run`에 `answer TEXT`, `skills_json TEXT`
- `repository/repo_connect.py` `_migrate`: 두 컬럼이 없으면 각각 `ALTER TABLE run ADD COLUMN` (있으면 건너뜀)
- `repository/evidence_repository.py`
  - `set_run_answer(run_id, answer)`
  - `runs_for_owner`: `skills_json`을 풀어 `skills` 목록으로 (비었거나 깨졌으면 `[]`, 깨지면 WARNING). `answer`는 그대로 돌려준다
- `agent/agent.py` `_finish_answer`: 소유자가 `task`이면 `set_run_answer(run_id, validation.answer)` (근거 줄을 뺀 본문)
- `tests/test_run_answer.py`(신규) 5건

## 결정한 것
- 실패·한도 실행은 `_invoke_logged`가 `AgentRunError`/예외를 던져 `_finish_answer`까지 오지 않으므로 따로 막을 필요가 없다. 테스트로 확인(빈 답변 실행 `answer` NULL).
- 근거 검증이 경고(`ok: False`)여도 본문은 저장한다. 그 초안이 `tasks.draft_answer`로 저장되는 것과 같다.
- `skills_json`은 D1에서 컬럼만. D4에서 채운다.
- 검토 화면 API(`GET /mails/{id}`의 `runs`)는 `_RUN_FIELDS` 그대로 — `answer`를 내보내지 않는다 (고객방 전용).

## 테스트: 명령과 출력
```
.venv/Scripts/python.exe -m pytest tests/test_run_answer.py tests/test_mail_detail_trace.py -q
10 passed in 7.20s

.venv/Scripts/python.exe -m pytest tests -q
286 passed in 34.60s
```
- 1차 초안(표)과 반려 반영 초안(문장)의 `run.answer`가 각각 남고 서로 다르다. 둘 다 근거 줄 없음, 두 번째가 `tasks.draft_answer`와 같다
- 웹 질문(session) 실행은 `answer` NULL, 빈 답변으로 실패한 task 실행도 NULL
- `skills_json` 정상/깨짐 처리
- 기존 DB(`label`까지 있는 run)를 두 번 열어도 컬럼이 한 번만 생긴다

## 확인하지 못한 것 / Gemini에게 요청할 검증
- 운영 DB 마이그레이션은 서버 재시작 때 적용된다 (사용자).

## 커밋 해시
- (커밋 뒤 summary에 기록)
