# I-I1 작성 절차(`create-skill`)와 로더 확장

## 변경 파일
- `agent/skills.py`
  - 채널: `ANSWER_CHANNELS = ("mail", "web")`, `AUTHOR_CHANNEL = "author"`, `CHANNELS`에 `author`. `author`는 다른 채널과 함께 쓸 수 없다 (검사 오류)
  - `Skill`에 `origin`(`repo`·`db`, 기본 `repo`)과 `version`(기본 `None`)
  - 저장소 절차: `reload_skills()`·`repo_skills()` — 지금처럼 시작 때 한 번. 검사에서 빠진 문서의 사유를 `_repo_errors`에 남긴다
  - DB 승인본: `set_db_source(fn)`로 붙는 조회 함수를 **실행마다** 부른다 (`db_skills()`). 채널은 `("mail", "web")` 고정, `origin="db"`, `version`은 행의 버전, `digest`는 본문으로 다시 계산
    - 저장소 절차·서버 적용 절차·`create-skill`·예약어(`drafts`, `types`, `analysis`)와 이름이 같거나 형식·길이가 어긋난 DB 절차는 읽지 않고 ERROR 로그 (같은 행·같은 사유는 한 번만 남긴다)
    - 조회가 예외를 내면 `logger.exception` 후 저장소 절차만으로 계속한다
  - `get_skills()` = 저장소 + DB 승인본. `applied_skills()`(서버 적용)는 **저장소 절차에서만** 찾는다. `selectable_skills(channel)`은 답변 채널(`mail`·`web`)만 받고 `author` 채널 절차를 빼고 돌려준다
  - `author_skill()`: 저장소 `create-skill`이 있고 채널이 `author`뿐일 때만 돌려준다. `author_skill_status()`: 화면용 `{available, name, digest, reason}`
  - `normalize_body()`, `body_digest()`: 저장소·DB 절차의 digest를 같은 기준(LF, 앞뒤 공백 제거)으로 계산
- `tools/tool.py`·`agent/agent.py`: 바꾸지 않았다. `load_skill`은 원래대로 `selectable_skills(channel_for(owner))`에서만 찾으므로 `author` 절차와 승인 전 DB 초안은 읽을 수 없다. `TOOLS`도 그대로
- `tests/test_skill_sources.py`(신규) 8건
- `tests/test_skills.py`: 저장소 절차 4종 테스트가 `author` 채널 절차는 세지 않게 한 줄 고쳤다 (설계자가 `create-skill`을 넣어도 깨지지 않게)

## 결정한 것
1. **I1 커밋에서는 DB 조회 함수를 비워 둔다** (`_no_db_source`). 항목 순서가 I1 → I2라서, 로더는 조회 함수를 받는 자리만 만들고 I2에서 `skill_repo`를 붙인다. I1 테스트는 대역 조회 함수로 "재시작 없이 나타나고 사라진다"를 확인했다.
2. `author` 채널은 단독으로만 쓸 수 있게 했다. `channels: "author,mail"`이면 같은 문서가 메일 선택 목록에 나오므로 지시서 I1-1("메일·웹의 선택 절차 목록에 나오지 않는다")을 지키려고 검사 오류로 뺀다.
3. **서버 적용 절차는 저장소에서만 찾는다.** 저장소 `mail-reply-style` 문서가 빠져 있을 때 같은 이름의 DB 절차가 그 자리를 채우는 길을 막았다 (원칙 3). DB 절차를 읽을 때도 `SERVER_CHOSEN` 이름은 무조건 뺀다.
4. DB 절차의 검사(`db_skill_problem`)는 승인 전 검사(I4 `check_skill_draft`)와 별개로 읽을 때 한 번 더 한다. 승인 뒤 저장소에 같은 이름의 절차가 들어오면 그때부터 DB 쪽이 빠진다.
5. 사용자가 넣은 `skills/skill-creator/`(GitHub 원본)는 머리말에 `metadata.channels`가 없고 본문이 33,168자라 로더가 ERROR 로그를 남기고 뺀다. 이름도 `create-skill`이 아니다. 지시서 2-2와 11-1에 따라 **구현자는 이 문서를 고치거나 옮기지 않았다.** 설계자가 `skills/create-skill/SKILL.md`(`channels: "author"`)로 고쳐 넣을 때까지 초안 생성은 꺼진 상태이고 화면에 사유가 보인다.

## 테스트: 명령과 출력
```
.venv/Scripts/python.exe -m pytest tests/test_skill_sources.py tests/test_skills.py -v
tests/test_skill_sources.py::test_author_skill_is_not_listed_or_loadable_in_answer_channels PASSED [  5%]
tests/test_skill_sources.py::test_author_channel_cannot_be_mixed_with_answer_channels PASSED [ 10%]
tests/test_skill_sources.py::test_missing_create_skill_disables_author_only PASSED [ 15%]
tests/test_skill_sources.py::test_db_skill_appears_and_disappears_without_reload PASSED [ 20%]
tests/test_skill_sources.py::test_db_skill_with_repo_or_reserved_name_is_ignored PASSED [ 25%]
tests/test_skill_sources.py::test_db_skill_cannot_become_server_applied PASSED [ 30%]
tests/test_skill_sources.py::test_db_failure_falls_back_to_repository PASSED [ 35%]
tests/test_skill_sources.py::test_approved_db_skill_is_listed_in_agent_prompt_not_body PASSED [ 40%]
tests/test_skills.py::test_repository_skills_all_load_and_pass_checks PASSED [ 45%]
tests/test_skills.py::test_invalid_documents_are_skipped_others_load PASSED [ 50%]
tests/test_skills.py::test_crlf_document_reads_with_same_digest PASSED   [ 55%]
tests/test_skills.py::test_web_prompt_lists_optional_skills_without_any_body PASSED [ 60%]
tests/test_skills.py::test_mail_prompt_has_reply_style_body_and_reject_run_has_both PASSED [ 65%]
tests/test_skills.py::test_prompt_section_order PASSED                   [ 70%]
tests/test_skills.py::test_load_skill_returns_body_and_refuses_other_channel_or_paths PASSED [ 75%]
tests/test_skills.py::test_load_skill_does_not_register_evidence PASSED  [ 80%]
tests/test_skills.py::test_load_skill_result_survives_tool_result_clearing PASSED [ 85%]
tests/test_skills.py::test_fifth_load_skill_call_is_limited PASSED       [ 90%]
tests/test_skills.py::test_adversarial_skill_cannot_skip_validation_or_send PASSED [ 95%]
tests/test_skills.py::test_skill_bodies_only_mention_existing_tools PASSED [100%]

============================= 20 passed in 6.34s ==============================

.venv/Scripts/python.exe -m pytest tests -q
320 passed in 36.70s
```

## 확인하지 못한 것 / Gemini에게 요청할 검증
- `create-skill` 실제 문서가 없어 `author_skill()`이 진짜 문서로 동작하는지는 임시 폴더 문서로만 확인했다.
- **시작 조건**: 지시서 I는 "단계 D가 Gemini 검증을 통과한 뒤"에 시작하라고 한다. `docs/dev_log/`에 D 판정 기록(D-summary, D-live-check)이 없다. 사용자가 2026-11-13 "개발 진행해주고"로 지시해 시작했다.
- I-11(`author` 채널 절차가 메일·웹에서 읽히지 않는다): `test_author_skill_is_not_listed_or_loadable_in_answer_channels`.

## 커밋 해시
(커밋 후 I-summary.md에 적는다)
