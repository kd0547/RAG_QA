# I-I5 업무 절차 API

## 변경 파일
- `app/routers/skills.py`(신규). 고정 경로(`/skills/drafts`, `/skills/types`, `/skills/analysis`)를 `/skills/{name}`보다 먼저 선언
  - `GET /skills`: 사용 중 절차(저장소 + DB 승인본) — 이름, 설명, 채널, 출처(`repo`·`db`), 버전, digest, 서버 적용 여부, 최근 30일 사용 실행 수, (DB) 유형·승인 시각. `author`(작성 절차 상태)와 `settings`(분석·자동 초안 설정)도 함께
  - `GET /skills/{name}`: 저장소 절차는 `read_only: true`, DB 절차는 사용 중 버전(없으면 마지막 승인본) 본문 + 버전 이력 + 열린 새 버전 초안
  - `GET /skills/drafts?status=`(기본 `generating, draft, error, rejected`. 그 밖의 값 400), `GET /skills/drafts/{doc_id}`(설명·본문·검사 결과·재료 사례 요약·유형·이전 승인 버전)
  - `PUT /skills/drafts/{doc_id}`: draft만, 다시 검사, `origin='edited'`
  - `POST /skills/drafts/{doc_id}/approve`: **승인 시점 상태로 다시 검사**해 errors가 없을 때만. 유형의 `skill_name`을 잇고 `reviewed_by`=요청 IP, `review_note`
  - `POST /skills/drafts/{doc_id}/reject`: 사유 필수, draft·error만
  - `POST /skills/{name}/drafts`: 마지막 승인본 복사 → 새 버전 draft (`origin='edited'`). 이미 열린 새 버전 초안이 있으면 그것(`already: true`)
  - `POST /skills/{name}/retire`: 새 `retired` 행 + 유형 `skill_name` 비움. 사용 중이 아니면 409
  - `GET /skills/types`(건수, 맡는 절차, 상태, 최근 사례 5건, 열린 초안, 어긋난 분석 수), `POST /skills/types/{id}/draft`(202), `POST /skills/types/{id}/state`(`open`↔`no_skill_needed`), `POST /skills/types/{id}/merge`(`{into}`)
  - `GET /skills/analysis?type_id=&mismatch=&limit=`
- `repository/skill_repository.py`: `update_draft`, `set_check`, `approve_doc`(**`approved`로 바꾸는 유일한 코드**), `reject_doc`, `open_draft_for_name`, `new_version_from_approved`, `retire`, `list_docs`, `set_type_state`, `merge_type`, `recent_cases`, `list_analysis`(어긋남 = `covered_by`가 있는데 실제 사용 절차에 없음), `skill_usage_since`
- `main.py`: 라우터 등록, SPA catch-all의 API 접두어 목록에 `skills`
- `tests/test_skill_api.py`(신규) 10건

## 결정한 것
1. **승인 시점에 다시 검사한다.** 초안이 만들어진 뒤 저장소에 같은 이름의 절차가 들어오거나 다른 유형이 같은 이름으로 먼저 승인될 수 있다. 다시 검사한 결과에 errors가 있으면 400이고, 그 검사 결과를 `check_json`에 남긴다(본문·출처는 그대로).
2. **더 새 버전이 이미 승인·사용 중지된 초안은 승인하지 않는다(409 `stale`).** v2·v3 초안이 함께 열려 있을 때 v3 승인 뒤 v2를 승인하면, 판정 규칙(가장 큰 버전)상 v2는 쓰이지 않는데 화면에는 '승인됨'으로 보이기 때문이다.
3. 반려는 `draft`뿐 아니라 `error`도 받는다. 생성 실패 초안을 목록에서 닫을 길이 필요하다.
4. 사용 중지된 절차를 다시 쓰는 길은 지시서대로 `POST /skills/{name}/drafts` → 승인이다 (예: v1 승인, v2 승인, v3 retired → v4 초안 → 승인).
5. 사용 횟수는 "그 절차를 쓴 실행 수"(서버 적용 또는 `load_skill` 호출, 한 실행에 한 번)다. 웹 질문 실행은 14일 뒤 정리되므로 30일 수치에는 최근 14일분만 남는다.
6. 생성 중·실패 행의 임시 이름(`_generating-…`)은 응답에서 `name: null`로 숨긴다.
7. 재료 사례 요약은 `task_id, subject, status, received_at, sent`만 내보낸다. 메일 본문·초안 본문은 응답에 없다.

## 테스트: 명령과 출력
```
.venv/Scripts/python.exe -m pytest tests/test_skill_api.py -v
test_list_shows_repository_skills_and_author_status PASSED
test_approve_makes_skill_selectable_without_restart PASSED
test_draft_with_errors_cannot_be_approved_and_edit_rechecks PASSED
test_new_version_keeps_history_and_retire_removes PASSED
test_repository_skills_are_read_only PASSED
test_reject_requires_reason_and_happens_once PASSED
test_draft_detail_shows_cases_without_mail_body PASSED
test_types_state_merge_and_draft_request PASSED
test_fixed_paths_are_not_taken_by_name_route PASSED
test_adversarial_db_skill_cannot_change_server_policy PASSED
10 passed in 7.84s

.venv/Scripts/python.exe -m pytest tests -q
362 passed in 49.18s
```

`approved` 상태를 쓰는 코드 검색 (I-3):
```
grep -rn "status = 'approved'\|status='approved'\|\"approved\"" --include=*.py agent app repository mail tools
repository/skill_repository.py:24:DOC_STATUSES = (...)                         ← 상수
repository/skill_repository.py:206:  WHERE d.status = 'approved'                ← 사용 중 판정 (읽기)
repository/skill_repository.py:219:  ... status = 'approved' ORDER BY ...        ← 마지막 승인본 (읽기)
repository/skill_repository.py:230:  if ... status == "approved": raise          ← insert_doc 금지
repository/skill_repository.py:535:  UPDATE skill_doc SET status = 'approved' …  ← approve_doc (승인 API만 부름)
repository/skill_repository.py:588:  WHERE d.name = ? AND d.status = 'approved'  ← retire 대상 조회 (읽기)
mail/templates.py:582:  "approved": "전송 대기"                        ← 메일 상태 표시 (무관)
```

## 확인하지 못한 것 / Gemini에게 요청할 검증
- I-5(적대적 DB 절차): `test_adversarial_db_skill_cannot_change_server_policy` — 승인된 DB 절차가 "근거 없이 바로 발송"을 지시하고 대역 모델이 따라도 `drafted`, 검증 경고, 검토 알림만 발송, `task_send` 0행.
- I-9: `test_new_version_keeps_history_and_retire_removes`.
- 실서버에서의 동작(사용자 uvicorn은 `--reload` 없이 떠 있어 재시작 전에는 `/skills`가 404).

## 커밋 해시
(I-summary.md에 적는다)
