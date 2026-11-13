# D-summary 고객방 조회 화면과 업무 절차(skill)

지시서: [opus_development_instructions_D.md](../opus_development_instructions_D.md)
정리: 통합 지시서 [opus_development_instructions_remaining.md](../opus_development_instructions_remaining.md) R0 (2026-11-13)

## 항목과 커밋

| 항목 | 내용 | 커밋 | 기록 |
|------|------|------|------|
| D1 | `run.answer`·`run.skills_json`, 실행별 초안 본문 기록 | `060ec96` | [D-D1](D-D1.md) |
| D2 | 발신자별 고객방 조회 API (`/customers`, `/customers/{sender}/timeline`) | `736f7e5` | [D-D2](D-D2.md) |
| D3 | 고객방 화면 (조회 전용) | `f267a63` | [D-D3](D-D3.md) |
| D4 | 절차 로더 `agent/skills.py`, `load_skill`, 메일 답장·반려 절차 서버 적용 | `dd3c7f2` | [D-D4](D-D4.md) |
| D5 | 절차 문서 4종과 도구·메일 틀·프롬프트 대조 (본문·코드 변경 없음) | `64c90fb` | [D-D5](D-D5.md) |
| (사고 기록) | D2 점검 스크립트가 저장소를 임포트해 운영 `run`에 컬럼 2개가 생김 (데이터 변경 없음) | `ade0319` | [D-D2](D-D2.md) |

## 테스트 수

| 시점 | 전체 테스트 |
|------|-------------|
| D 시작 전 (C2 완료) | 281 |
| D1 | 286 passed |
| D2 | 300 passed |
| D4 | 312 passed |
| D 완료 (I 시작 전) | 312 passed |

프론트: D3·D4에서 `npx tsc -b`, `npx eslint src/mail` 출력 없음.

## 지시서와 다르게 한 것
1. **서버가 고르는 절차(`mail-reply-style`, `revise-after-reject`)는 선택 절차 목록과 `load_skill`에서 뺐다** (D4 결정 1). 5-4를 글자 그대로 읽으면 반려 없는 1차 메일 실행 목록에 `revise-after-reject`가 들어가는데, 5-3 표가 "서버가 고른다"로 정했으므로 모델 선택 대상에서 제외했다.
2. **`skills_json`은 실행 시작 때 기록한다** (D4 결정 2). 실패·한도 실행도 어떤 절차로 돌았는지 남는다.
3. 고객방 목록은 한 번에 200명까지 불러오고 페이지 넘김 UI는 넣지 않았다 (운영 발신자 3명, D3).
4. 수신 계정 구분 컬럼은 넣지 않았다 (계정이 하나). 통합 지시서에서 고객 회신 기능(단계 G 헤더 저장)이 빠졌으므로 이 항목도 넣지 않는다.
5. D5의 본문 어긋남(certification-bundle 웹 채널 문장, revise-after-reject의 첨부 다시 읽기, 담당자 값과 근거 규칙)은 본문을 고치지 않고 설계자에게 넘겼다. 설계자의 수정본은 `docs/skills_next/`로 왔고 Z1에서 그대로 옮긴다.

## D6 (실서버·실모델 확인)
통합 지시서 R0-2에 따라 따로 하지 않고 9절 T4(통합 확인)로 옮겼다.

## Gemini B-D 항목별 확인 위치

| 번호 | 조건 | 확인 위치 |
|------|------|-----------|
| D-1 | 반려 뒤에도 1차 초안 본문이 남는다 | `tests/test_run_answer.py`, `tests/test_customers.py::test_event_order_received_draft_reject_draft_send` |
| D-2 | 발신자별 타임라인 시간순 | `tests/test_customers.py` (사건 순서·시간대 섞임) |
| D-3 | 같은 발신자의 문의가 묶음으로 구분 | `tests/test_customers.py` |
| D-4 | 기록 없는 옛 작업이 `inferred` | `tests/test_customers.py::test_legacy_task_gets_inferred_draft_and_send` |
| D-5 | 타임라인이 모델 입력에 들어가지 않는다 | `tests/test_customers.py::test_model_side_code_does_not_import_customer_repository`, `::test_other_inquiry_not_in_model_input` |
| D-6 | 응답에 디스크 경로·이미지 데이터가 없다 | `tests/test_customers.py` (경로·data URL 검사) |
| D-7 | 고객방에 승인·반려·편집 동작 없음 | `frontend/src/mail/pages/MailCustomersPage.tsx`, D-D3 화면 확인 |
| D-8 | 절차 문서 4종 검사 통과 | `tests/test_skills.py::test_repository_skills_all_load_and_pass_checks` |
| D-9 | 선택 절차만 읽힘, 웹 프롬프트는 목록만 | `tests/test_skills.py::test_web_prompt_lists_optional_skills_without_any_body` |
| D-10 | 적용 절차가 실행 기록에 남음 | `tests/test_skills.py`, `run.skills_json` |
| D-11 | 절차 본문이 검증·한도·승인 정책을 못 바꿈 | `tests/test_skills.py` (적대적 절차 테스트) |
| D-12 | `load_skill`이 경로를 만들지 않고 다른 채널 절차를 주지 않음 | `tests/test_skills.py::test_load_skill_returns_body_and_refuses_other_channel_or_paths` |
| D-13 | 한도·맥락 예산·DB 프롬프트 그대로 | `agent/agent.py` diff (D4), `tests/test_context_budget.py` |
| D-14 | 전체 테스트·프론트 타입·린트 | 위 테스트 수 표 |
