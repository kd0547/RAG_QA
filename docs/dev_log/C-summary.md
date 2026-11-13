# 단계 C 요약 (Gemini B-C 검증 요청)

단계 C(C1~C5) 구현을 마쳤다. 지시서에 따라 **D~G는 시작하지 않았다** (C가 Gemini 검증을 통과한 뒤 별도 지시).

| 항목 | dev_log | 커밋 |
|------|---------|------|
| C1 checkpointer | [C-C1.md](C-C1.md) | `c921f22` |
| C2 맥락 예산 미들웨어 | [C-C2.md](C-C2.md) | `26dcca0` |
| C3 반려를 다음 턴으로 | [C-C3.md](C-C3.md) | `fccd946` |
| C4 재시작 복구 | [C-C4.md](C-C4.md) | `1af4d48` |
| C5 검토 화면 보강 | [C-C5.md](C-C5.md) | `507e2d0` |

## 회귀: 전체 테스트
```
.venv/Scripts/python.exe -m pytest tests -q

........................................................................ [ 28%]
........................................................................ [ 57%]
........................................................................ [ 86%]
..................................                                       [100%]
250 passed in 29.85s
```
단계 C 시작 전: `231 passed`. 프론트 `npx tsc -b`, `npx eslint src/mail` 통과.

## Gemini B-C 항목 대응
| B-C 조건 | 근거 |
|----------|------|
| 반려 후 재생성 시 1차 evidence를 다시 `read_pages` 하지 않음 | `test_review_turns.py::test_rejection_continues_same_thread_without_new_search` (두 번째 실행 도구 호출 0건) |
| 문체만 바꾸는 반려에서 `search_documents` 0~1회 | 대역 모델로는 0회. 실모델 확인 필요 (UNVERIFIED 예상) |
| 같은 `review_id`로 두 번 넣어도 메시지 한 번 | `test_same_review_twice_adds_one_message` |
| 재시작 후 같은 thread로 이어짐 (`agent_threads.db`에 checkpoint) | `test_restart_resume.py` 3건 |
| 축약 뒤에도 evidence 목록을 볼 수 있음 | `test_context_budget.py::test_old_tool_results_become_placeholder_but_evidence_list_stays` |
| Tool/ModelCallLimit이 run 기준, 한도 초과 메시지가 답변으로 저장되지 않음 | `build_middleware`(run_limit), `test_model_call_limit_is_recorded_as_limit`, `test_search_documents_limited_per_run` |

## 금지 사항 점검
- 메일 발송·운영 DB 쓰기: 없음. 테스트 전후 운영 `storage/mail.db` 수정 시각은 2026-11-12 18:00:19(사용자 서버) 그대로이고, 운영 `storage/agent_threads.db`는 생기지 않았다 (conftest 격리 대상에 추가).
- 프롬프트로 해결: 한도·축약·요약은 모두 서버 미들웨어로 강제한다. 프롬프트에 횟수를 쓰지 않는다.
- 자동 재발송: 없음.

## 지시서와 다르게 하거나 지시서에 없던 것 (상세는 각 dev_log)
1. **`recursion_limit` 40 → 200** (C2). 미들웨어 노드 때문에 40이면 도구 9회 호출에서 끊긴다 (어제 실제 질문은 8회). 모델 호출 20회 한도가 먼저 걸리도록 올렸다. 측정표는 C-C2.
2. **B6의 '이 run에서 읽음'을 '같은 소유자(대화)의 실행들에서 읽음'으로 넓힘** (C3). 그대로면 반려 후 재작성이 모두 검증 오류가 된다.
3. 같은 반려 중복 방지를 메시지 ID 고정으로 구현 (C3).
4. 대화 기록만 있고 반려가 없으면(생성 중 재시작) 새 메시지 없이 checkpoint에서 재개 (C3·C4).
5. `read_sources` 응답 필드 추가로 인용/읽기 구분 (C5).
6. 설치로 `langgraph-checkpoint` 4.1.1 → 4.3.1 (C1).

## 사용자 확인이 필요한 것
- **서버 재시작과 `npm run build`.** 사용자 서버는 마지막으로 2026-11-12 17:41에 B6 코드로 시작됐다. 재시작해야 단계 C(대화 기록·미들웨어·반려 턴)가 동작하고 `storage/agent_threads.db`가 생긴다. 재시작하면 기존 DB에 `tasks.last_review_id` 컬럼이 추가된다.
- `read_pages` 시작 위치 인자 (B 단계에서 넘어온 결정), `sending` 상태 처리 정책 (A 단계에서 넘어온 결정)은 여전히 미정이다.
