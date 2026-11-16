# I-summary 문의 분석, 절차 초안 생성, R&D 승인

> 2026-11-13 후속: 실제 `create-skill` 문서의 출처·라이선스 표시·크기·외부 실행 여부를 [I-I1](/C:/TG_AI_DEV/rag_QA/docs/dev_log/I-I1.md)의 후속 현행화에 기록했다. 작성 절차의 사양 도구 안내와 잘린 로그의 사용량 집계를 수정했으며, 최신 전체 테스트는 463 passed다. 아래 항목별 수치는 당시 기록으로 유지한다. 최신 검증은 [운영 반영 전 점검](/C:/TG_AI_DEV/rag_QA/docs/dev_log/T-predeploy-2026-11-13.md)을 참조한다.

지시서: [opus_development_instructions_I.md](../opus_development_instructions_I.md)

## 항목과 커밋

| 항목 | 내용 | 커밋 | 기록 |
|------|------|------|------|
| (체크포인트) | 사용자가 넣은 `skills/skill-creator/` 원본 | `4a08165` | — |
| I1 | 작성 절차(`author` 채널)와 DB 승인본을 합치는 로더 | `fc34723` | [I-I1](I-I1.md) |
| I2 | `request_type`·`request_analysis`·`skill_doc`, `SkillRepository`, 기본 유형 | `c5567fd` | [I-I2](I-I2.md) |
| I3 | 문의 분석 모듈과 `request-analyzer` 스레드 | `82e374f` | [I-I3](I-I3.md) |
| I4 | 절차 초안 생성 (`check_skill_draft`, 자동·수동) | `4ce4298` | [I-I4](I-I4.md) |
| I5 | `/skills` API | `f8bb783` | [I-I5](I-I5.md) |
| I6 | `/skill` 화면 | `ead7aa5` | [I-I6](I-I6.md) |
| I7 | 실서버·실모델 확인 (코드 변경 없음): 분석 32건 모두 ok, 건당 평균 6.1초, 유형 판단 30건 중 28건 맞음, 자동 초안은 create-skill이 없어 안 생김 | (이 문서와 같은 커밋) | [I-live-check](I-live-check.md) |

전체 테스트: `.venv/Scripts/python.exe -m pytest tests -q` → **362 passed** (시작 전 312). 프론트 `npx tsc -b`, `npx eslint src/skill …` 출력 없음.

## 지시서와 다르게 된 것 / 멈춘 것
1. **`create-skill`이 없다.** 사용자가 넣은 것은 GitHub 원본 `skills/skill-creator/`(이름 다름, `metadata.channels` 없음, 본문 33,168자)다. 지시서 2-2·11-1에 따라 구현자는 이 문서를 쓰거나 고치지 않았다. 로더는 이 폴더를 ERROR 로그와 함께 빼고, **초안 생성은 꺼진 상태**다. 화면 세 탭 위쪽에 "작성 절차 없음 — skills/create-skill/SKILL.md가 없습니다"가 보인다. 설계자가 `skills/create-skill/SKILL.md`(`channels: "author"`, 본문 6,000자 이하)를 넣고 서버를 다시 시작하면 켜진다. `skill-creator`라는 이름은 DB 절차 이름으로 쓸 수 없게 막아 두었다.
2. **시작 조건**: 지시서는 "단계 D가 Gemini 검증을 통과한 뒤" 시작하라고 한다. `docs/dev_log/`에 D 판정 기록(D-summary, D-live-check)이 없다. 사용자가 2026-11-13 "개발 진행해주고"로 지시해 시작했다.
3. 사용자가 13:30:35에 서버를 다시 시작해 I1~I5 코드가 운영에서 돌고 있다 (I6 화면은 `npm run build` 전이라 아직 없다). 그 시작에서 운영 DB에 새 테이블 세 개와 기본 유형 3개가 생겼고, 분석 스레드가 기존 메일을 분석하고 있다. 구현자는 운영 DB에 쓰지 않았다 (점검은 `mode=ro` SQL만, 화면 확인은 사본 DB).

## 스스로 정한 것 (항목별 기록의 요약)
- 생성 중·실패 초안은 임시 이름 `_generating-…`·version 0을 쓰고, 실패한 초안은 이름을 차지하지 않는다 (I2·I4)
- 서버 적용 절차는 저장소에서만 찾는다. DB 절차가 그 이름을 쓸 수 없다 (I1)
- 자동 초안은 그 유형의 `skill_doc`이 상태와 관계없이 하나라도 있으면 만들지 않는다 (반려·실패 포함) (I4)
- 승인 시점에 다시 검사하고, 같은 이름의 더 새 버전이 이미 승인·사용 중지됐으면 승인하지 않는다 (I5)
- 반려는 `draft`와 `error` 초안에 쓸 수 있다 (I5)
- API 실패 표시는 프롬프트 화면 방식(오류 상자 + 다시 시도). 예시 데이터로 대체하지 않는다 (I6)

## Gemini 검증 항목 (B-I)

| 번호 | 확인 위치 |
|------|-----------|
| I-1 | `git diff e4a5cf7 HEAD -- agent/agent.py` 변경 없음 (`TOOLS` 그대로) |
| I-2 | `SkillRepository.active_skill_docs()` SQL(approved만), `skills.db_skills()`; `test_unapproved_drafts_are_never_selectable`, `test_unapproved_rows_are_never_active`, `test_approve_makes_skill_selectable_without_restart`(승인 전 `load_skill` 오류) |
| I-3 | `approved`로 바꾸는 코드는 `SkillRepository.approve_doc` 하나, 부르는 곳은 `POST /skills/drafts/{id}/approve` 하나 (검색 결과는 I-I5.md). `insert_doc`는 `approved`를 거부. 자동 승인 설정 없음 |
| I-4 | `test_db_skill_cannot_become_server_applied`, `test_db_skill_with_repo_or_reserved_name_is_ignored`, `test_material_instruction_cannot_make_server_applied_skill`, `test_check_errors_retry_once_then_error[spec-compare]` |
| I-5 | `test_adversarial_db_skill_cannot_change_server_policy` (승인된 DB 절차로), D의 `test_adversarial_skill_cannot_skip_validation_or_send` |
| I-6 | `test_mail_instructions_cannot_push_values_out_of_range` |
| I-7 | `test_two_invalid_outputs_leave_error_and_task_status`, `test_analyzer_thread_survives_exceptions_and_mail_loop_still_works` |
| I-8 | `test_cycle_rests_while_mail_is_waiting`, 실서버 로그 (I-live-check) |
| I-9 | `test_db_skill_appears_and_disappears_without_reload`, `test_active_version_rule`, `test_new_version_keeps_history_and_retire_removes` |
| I-10 | `test_draft_with_errors_cannot_be_approved_and_edit_rechecks`, `test_draft_detail_shows_cases_without_mail_body`, 화면 캡처 `img/I-I6-*.jpg` |
| I-11 | `test_author_skill_is_not_listed_or_loadable_in_answer_channels` |
| I-12 | 362 passed, tsc·eslint 출력 없음, `agent/agent.py`·`agent/prompt.py`·`tools/`·`mail/` 변경 없음 (`config.py`는 새 설정 추가만) |

## 사용자 확인 사항
1. 설계자가 `skill-creator` 원본을 이 런타임 형식으로 고친 `skills/create-skill/SKILL.md`를 넣어야 초안 생성이 켜진다 (지시서 11-1).
2. 자동 초안 기준 3건·자동 생성 켬이 기본값이다 (`SKILL_DRAFT_MIN_CASES`, `SKILL_DRAFT_AUTO`).
3. 로그인 기능이 없어 화면에 접근할 수 있는 누구나 승인할 수 있다. 승인자는 IP로만 남는다.
4. 화면을 쓰려면 `frontend`에서 `npm run build` (서버는 이미 13:30에 다시 시작됨. `/skills` API는 지금 응답한다).
