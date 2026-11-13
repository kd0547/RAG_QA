# I-I2 저장 구조

## 변경 파일
- `storage/schema.sql`: `request_type`, `request_analysis`, `skill_doc` (지시서 I2 그대로) + 인덱스 `idx_request_analysis_type`, `idx_skill_doc_type(type_id, status)`, `idx_skill_doc_status`. 새 테이블이라 `_migrate`(ALTER)는 고치지 않았다
- `repository/skill_repository.py`(신규) `SkillRepository`
  - 유형: `ensure_seed_types()`(없을 때만, 같은 label의 seed 행이 있으면 건너뜀), `get_type`, `resolve_type`(merged → `merged_into`를 따라감, 없거나 순환이면 None), `list_types(states, limit)`(ok 분석 건수 `case_count` 많은 순), `find_type_by_label`(공백·대소문자 무시), `create_type`(한 줄로 줄이고 label 30자·description 200자에서 자름, 같은 label이면 기존 유형)
  - 절차: `active_skill_docs()`(이름마다 approved·retired 중 가장 큰 version이 approved인 행), `active_doc`, `latest_approved`, `history`, `next_version`, `insert_doc`(approved 행은 만들 수 없다), `create_generating(type_id)`, `docs_for_type`
- `repository/__init__.py`: `skill_repo = SkillRepository(db)`
- `agent/skills.py`: DB 조회 함수의 기본값을 `repository.skill_repo.active_skill_docs()`로 (부를 때마다 `repository.skill_repo`를 찾아 테스트가 임시 DB로 바꿀 수 있다)
- `main.py`: lifespan에서 `skill_repo.ensure_seed_types()` (실패해도 서버는 뜬다)
- `tests/conftest.py`: `agent_env`에 `skill_repo`(임시 DB)
- `tests/test_skill_repository.py`(신규) 5건

## 결정한 것
1. **생성 중(`generating`) 행의 이름**: 지시서 표는 `name NOT NULL`인데, 초안 생성은 모델이 이름을 정하기 전에 `generating` 행을 먼저 만든다(I4). 그래서 생성 중 행은 임시 이름 `_generating-<12자 hex>`와 `version 0`을 쓴다. 밑줄로 시작해 절차 이름 형식(`NAME_PATTERN`)에 맞지 않으므로 실제 절차 이름과 겹치지 않는다. 생성이 끝나면 I4가 실제 이름·버전으로 바꾼다.
2. **사용 중 판정에 approved·retired만 본다.** `draft`·`error`·`rejected`처럼 더 큰 버전이 승인 전이어도 승인된 이전 버전을 계속 쓴다 (지시서 예: 승인 v1, 초안 v2 → v1).
3. 기본 유형을 `Database` 초기화가 아니라 서버 시작(lifespan)에서 넣는다. 기본 프롬프트(`prompt_repo.ensure_default`)와 같은 자리다. 테스트용 DB를 만들 때마다 행이 생기지 않는다.
4. `insert_doc`는 `approved` 상태를 받지 않는다. approved로 바꾸는 코드는 I5 승인 함수 하나로 모은다 (I-3).

## 테스트: 명령과 출력
```
.venv/Scripts/python.exe -m pytest tests/test_skill_repository.py tests/test_skill_sources.py -v
tests/test_skill_repository.py::test_existing_db_gets_tables_and_seed_types_once PASSED [  7%]
tests/test_skill_repository.py::test_active_version_rule PASSED          [ 15%]
tests/test_skill_repository.py::test_unapproved_rows_are_never_active PASSED [ 23%]
tests/test_skill_repository.py::test_loader_reads_active_db_skill_through_repository PASSED [ 30%]
tests/test_skill_repository.py::test_type_helpers PASSED                 [ 38%]
tests/test_skill_sources.py::test_author_skill_is_not_listed_or_loadable_in_answer_channels PASSED [ 46%]
tests/test_skill_sources.py::test_author_channel_cannot_be_mixed_with_answer_channels PASSED [ 53%]
tests/test_skill_sources.py::test_missing_create_skill_disables_author_only PASSED [ 61%]
tests/test_skill_sources.py::test_db_skill_appears_and_disappears_without_reload PASSED [ 69%]
tests/test_skill_sources.py::test_db_skill_with_repo_or_reserved_name_is_ignored PASSED [ 76%]
tests/test_skill_sources.py::test_db_skill_cannot_become_server_applied PASSED [ 84%]
tests/test_skill_sources.py::test_db_failure_falls_back_to_repository PASSED [ 92%]
tests/test_skill_sources.py::test_approved_db_skill_is_listed_in_agent_prompt_not_body PASSED [100%]

============================= 13 passed in 6.32s ==============================

.venv/Scripts/python.exe -m pytest tests -q
325 passed in 40.33s
```

## 확인하지 못한 것 / Gemini에게 요청할 검증
- 운영 DB에는 아직 테이블이 없다 (서버 재시작 때 생긴다). 이 단계에서 운영 DB를 열지 않았다.
- 지시서의 사용 중 판정 예(승인 v1·초안 v2 → v1 / v2 승인 → v2 / v3 retired → 사용 안 함)는 `test_active_version_rule`.

## 커밋 해시
(I-summary.md에 적는다)
