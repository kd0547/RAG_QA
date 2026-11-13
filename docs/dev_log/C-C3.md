# C-C3 반려를 다음 턴으로

## 변경 파일
- `storage/schema.sql`, `repository/repo_connect.py`: `tasks.last_review_id INTEGER`
- `repository/task_repository.py`: `unapplied_reject_reasons(task_id) -> [(review_id, reason)]` (review_id > last_review_id인 requeue 반려), `save_draft(…, applied_review_id=)`가 같은 트랜잭션에서 `last_review_id` 갱신
- `mail/email_service.py`: `build_review_feedback(reasons)`는 이전 초안 없이 `"[검토 담당자 반려]\n- 사유…"` + 짧은 안내. 소비자는 미반영 반려만 `review=(최대 review_id, 안내문)`로 넘기고, 성공하면 `applied_review_id`로 저장
- `agent/agent.py` `run_agent_temp_attachments(…, review=…)`: 세 경로
  1. 대화 기록 있음 + 반려 → 반려 안내 user 메시지 하나만 (`id=review:{thread}:{review_id}`)
  2. 대화 기록 있음 + 반려 없음 → 새 메시지 없이 checkpoint에서 재개 (C4)
  3. 대화 기록 없음 → 질문·첨부(`id=question:{thread}`) + 반려가 있으면 두 번째 user 메시지
- `repository/evidence_repository.py`: `uses_for_owner(owner, action)`
- `agent/validation.py`, `agent/agent.py evidence_sources`: '읽음' 판정·출처 대체를 같은 소유자 범위로 (아래 결정 1)
- `tests/test_review_turns.py`(신규), `tests/test_email_consumer.py`, `tests/test_validation.py`

## 결정한 것
1. **지시서 B6과 C3의 충돌: '이 run에서 읽음'을 '같은 소유자의 실행들에서 읽음'으로 넓혔다.** B6은 "이 run에 read 0건 + 사실 답변 = errors"이다. 그런데 C3(와 Gemini B-C)은 반려 후 재작성이 1차에서 읽은 근거를 다시 읽지 않기를 요구한다. 그대로 두면 정상적인 재작성이 모두 "근거를 읽지 않고 답변" 오류가 된다. 메일의 소유자는 `task:{task_id}` = 대화 하나라서, 같은 대화에서 읽은 근거는 모델 맥락에 있다고 보고 인정했다. `/ask`는 호출마다 소유자가 새로 생겨 의미가 그대로다. warning 문구도 "이번 실행에서" → "이 질문에서"로 바꿨다.
   - 출처도 같다: 이번 실행에서 인용·읽기가 없으면 같은 소유자의 읽은 근거로 채운다 (재작성 초안의 출처가 비지 않게).
2. **같은 반려를 두 번 넣지 않는 방법: 메시지 ID 고정.** LangGraph의 `add_messages`는 같은 ID의 메시지를 덮어쓴다. 같은 `review_id`로 두 번 처리해도 user 메시지는 하나다. `last_review_id` 갱신은 초안 저장과 같은 트랜잭션이라, 성공한 반려는 다시 처리되지 않는다.
3. **여러 번 반려된 뒤 처리되면** 미반영 사유를 한 메시지에 모으고 가장 큰 review_id를 ID로 쓴다.
4. 마이그레이션 전 task(대화 기록 없음, `last_review_id` NULL)는 예전 반려 사유가 모두 미반영으로 잡혀 첫 실행 + 반려 안내 메시지로 간다 (지시서대로).
5. thread 잠금은 C1에서 넣었다.

## 테스트: 명령과 출력
```
.venv/Scripts/python.exe -m pytest tests/test_review_turns.py -v

tests/test_review_turns.py::test_rejection_continues_same_thread_without_new_search PASSED [ 20%]
tests/test_review_turns.py::test_same_review_twice_adds_one_message PASSED [ 40%]
tests/test_review_turns.py::test_rejection_without_checkpoint_starts_over_with_reasons PASSED [ 60%]
tests/test_review_turns.py::test_unapplied_reasons_respect_last_review_id PASSED [ 80%]
tests/test_review_turns.py::test_review_feedback_text PASSED             [100%]
============================== 5 passed in 5.93s ==============================
```
`test_rejection_continues_same_thread_without_new_search`는 실제 소비자 루프·임시 SQLite checkpointer로 첫 초안 → `reject(requeue)` → 재처리를 끝까지 돈다. 두 번째 모델 입력에 1차의 `read_pages` ToolMessage와 반려 안내가 있고, 두 번째 실행의 도구 호출은 0건이다. 검증 `ok`, warnings 없음, 출처 cited, `last_review_id` 갱신, 대화의 user 메시지 2개.

## 확인하지 못한 것 / Gemini에게 요청할 검증
- 실제 모델이 "문체만 바꾸는 반려"에서 검색을 0~1회로 줄이는지는 실모델로 봐야 한다 (B-C 항목). 대역 모델은 정해진 대로 답한다.
- 1차 `read_pages` 결과가 축약(C2)된 뒤 반려되면 모델이 `list_evidence`로 ID만 볼 수 있고 본문은 다시 읽어야 한다. 이 경우 `read_pages`가 다시 불린다 (근거 ID는 같은 revision이면 같다).

## 커밋 해시
- `fccd946`
