# C-C4 재시작 복구

## 변경 파일
- `main.py`: C1에서 이미 lifespan 시작부의 `task_repo.reset_processing()`(A4) 뒤에 `open_checkpointer()`를 두었다. 이 항목에서는 코드 변경이 없다.
- `tests/test_restart_resume.py`(신규)

## 결정한 것
1. **생성 중에 서버가 꺼진 task의 재개 방법: 새 메시지 없이 `invoke(None)`.** `processing` → `pending`으로 돌아온 task는 반려가 없고 대화 기록만 있다. 이때 질문을 다시 넣으면 대화에 질문이 두 번 쌓인다. 그래서 마지막 checkpoint에서 남은 단계를 이어 간다 (C3의 경로 2). 마지막 checkpoint가 이미 최종 답변이면(답변 생성 뒤 저장 전 종료) 그 답변을 검증·저장한다.
2. **재시작 흉내:** 같은 파일로 `SqliteSaver`를 닫았다가 새 연결로 열고, 새 에이전트를 만들어 같은 thread_id로 실행한다.

## 테스트: 명령과 출력
```
.venv/Scripts/python.exe -m pytest tests/test_restart_resume.py -v

tests/test_restart_resume.py::test_new_agent_on_same_db_sees_previous_messages PASSED [ 33%]
tests/test_restart_resume.py::test_task_interrupted_while_processing_resumes_same_thread PASSED [ 66%]
tests/test_restart_resume.py::test_lifespan_resets_processing_before_opening_checkpointer PASSED [100%]
============================== 3 passed in 5.49s ==============================
```
- 지시서 테스트: 임시 checkpointer DB에 대화를 만든 뒤 새 연결·새 에이전트로 같은 thread_id를 호출 → 이전 메시지가 입력에 있다.
- 추가: `read_pages` 뒤 모델 호출에서 끊긴 task(processing) → `reset_processing()` → 새 연결 → 소비자 한 주기 → user 메시지 1개(질문 재투입 없음), 1차 읽기 결과에서 이어서 drafted, 검증 ok.

## 확인하지 못한 것 / Gemini에게 요청할 검증
- 실제 프로세스 강제 종료(uvicorn kill) 후 재시작은 해 보지 않았다. 테스트는 예외로 끊긴 상황을 흉내 냈다.
- 운영 `storage/agent_threads.db`는 아직 없다 (서버가 C1 이후 코드로 재시작되지 않음). 재시작 후 생기는지 확인이 필요하다.

## 커밋 해시
- `1af4d48`
