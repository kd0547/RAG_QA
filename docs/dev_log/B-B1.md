# B-B1 evidence 저장소

## 변경 파일
- `storage/schema.sql`: `evidence`, `run`, `evidence_use` 테이블 (지시서 2-3) + 인덱스 `idx_run_owner`, `idx_evidence_use_run`
- `repository/evidence_repository.py`(신규): `register`, `get`, `get_many`, `list_for_owner`, `record_use`, `uses_for_run`, `start_run`, `finish_run`, `get_run`, `latest_run`
- `repository/__init__.py`: `evidence_repo`
- `agent/evidence_context.py`(신규): `Owner`, `current_owner()`, `current_run()`, `owner_scope`, `run_scope` (contextvars)
- `agent/agent.py`: `run_agent(…, owner=None)`, `run_agent_temp_attachments(…, owner=None)`가 `owner_scope`에 들어가고, `_invoke_logged`가 `start_run` → `run_scope` → `finish_run`
- `mail/email_service.py`: 메일 처리는 `owner=Owner("task", task_id)`
- `tests/conftest.py`: 도구 호출을 내는 대역 모델 `ScriptedModel`, `tool_call()`, 임시 DB 픽스처 `agent_env`
- `tests/test_evidence.py`(신규)

## 결정한 것
1. **`evidence.source_name` 컬럼 추가 (지시서 스키마에 없음).** 출처 화면에 파일명을 보여야 하는데, `/ask/attachments`의 임시 첨부는 `file`·`mail_attachments` 어디에도 행이 없어 이름을 찾을 수 없다. 등록 시점에 표시용 이름을 같이 저장한다.
2. **같은 근거 판정 키 = (소유자, 원천, file_id, page_id, page, attachment_id, spec_value_id, revision, content_hash).** 지시서의 (owner, origin, file_id, page_id, revision)에 `content_hash` 등을 더했다. 검색 청크는 한 파일·페이지에 여러 개라 지시서 키만으로는 서로 다른 청크가 한 ID로 합쳐진다. 또 `file_page.updated_at`은 초 단위라 1초 안에 두 번 검수하면 revision이 같아도 본문이 다르다. 지시서 키가 같고 본문도 같으면 같은 ID라는 규칙은 그대로다.
3. **ID 형식:** `e` + uuid 앞 8자리 16진수 (예: `e1a2b3c4d`). 실행 ID는 `r` + 12자리.
4. **`run.status`에 `running` 추가.** `start_run`이 행을 만들 때의 상태다. 종료 상태는 지시서대로 `ok | error | limit`.
5. **`get`·`get_many`에 소유자 인자(선택).** 지시서 시그니처는 `get(evidence_id)`인데, 테스트 요구 "다른 owner 조회 시 None"을 위해 `owner_type, owner_id`를 주면 걸러지게 했다.
6. **`latest_run(owner)` 추가.** C5 검토 화면의 '에이전트가 한 일'에 쓸 예정이다.
7. **contextvars 전달 확인.** LangGraph가 도구를 병렬 스레드에서 실행해도 값이 전달되는지 대역 모델로 먼저 확인했다 (도구 두 개를 동시 호출 → 두 도구 모두 owner 값을 읽음).
8. 소유자 없이 `_invoke_logged`를 부르면 `RuntimeError`를 낸다 (근거를 누구 것으로 등록할지 모르므로).

## 테스트: 명령과 출력
```
.venv/Scripts/python.exe -m pytest tests/test_evidence.py -v

tests/test_evidence.py::test_same_page_same_revision_returns_same_id PASSED [ 14%]
tests/test_evidence.py::test_get_respects_owner PASSED                   [ 28%]
tests/test_evidence.py::test_list_for_owner_and_uses PASSED              [ 42%]
tests/test_evidence.py::test_run_lifecycle PASSED                        [ 57%]
tests/test_evidence.py::test_context_scopes_reset PASSED                 [ 71%]
tests/test_evidence.py::test_run_agent_records_run_for_task_owner PASSED [ 85%]
tests/test_evidence.py::test_run_agent_without_owner_uses_new_session PASSED [100%]

============================== 7 passed in 6.09s ==============================
```

## 확인하지 못한 것 / Gemini에게 요청할 검증
- 실제 LLM(vLLM)으로 돌리지 않았다. 모든 실행은 `ScriptedModel` 대역이다.
- `/ask`는 호출마다 새 세션이라 세션 근거가 계속 쌓인다. 정리(보관 기간)는 지시서에 없어 넣지 않았다.

## 커밋 해시
- `fe3fdc3`
