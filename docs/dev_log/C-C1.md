# C-C1 checkpointer

## 변경 파일
- `requirements.txt`: `langgraph-checkpoint-sqlite==3.1.3`
- `agent/agent.py`: `open_checkpointer(path)`, `set_checkpointer()`, `create_rag_agent(llm, checkpointer=…)`, `build_agent(mode, checkpointer)`, `get_agent`가 공유 checkpointer로 빌드. `task_thread_id()`, `new_ask_thread_id()`. `run_agent*`에 `thread_id`. `_invoke_logged`의 config `{"configurable": {"thread_id": …}, "recursion_limit": …}`. thread별 `threading.Lock`
- `main.py`: lifespan에서 `open_checkpointer()` → `set_checkpointer()` → `get_agent()`, 종료 시 `set_checkpointer(None)`·연결 닫기
- `mail/email_service.py`: `thread_id=task_thread_id(task_id)`
- `tests/conftest.py`: 운영 `storage/agent_threads.db`도 테스트 격리 대상. `agent_env.install(…, checkpointer=)`
- `tests/test_threads.py`(신규)

## 결정한 것
1. **설치 시 `langgraph-checkpoint`가 4.1.1에서 4.3.1로 올라간다.** sqlite 3.1.3이 `>=4.3.1`을 요구하기 때문이다. 업그레이드 직후 전체 231개 테스트가 통과했다. `aiosqlite`, `sqlite-vec`도 함께 설치된다.
2. **이전 실행 메시지 제외.** 대화 기록이 있으면 `invoke` 결과에 이전 실행의 메시지도 들어 있다. 그래서 실행 전 checkpoint의 메시지 ID를 저장해 두고, 실행 기록의 도구 수·토큰은 새로 생긴 메시지만 센다.
3. **thread 잠금은 `_invoke_logged`에서 invoke 전체를 감싼다** (지시서 C3의 동시 실행 방지를 C1에 미리 넣었다).
4. C1 커밋 시점의 `recursion_limit`은 지시서대로 40이다. C2에서 바꿨다 (C-C2 참고).
5. `/ask`는 호출마다 `ask:{uuid}`라서 `agent_threads.db`에 질문마다 대화가 하나씩 쌓인다. 정리 기능은 지시서에 없어 넣지 않았다.

## 테스트: 명령과 출력
```
.venv/Scripts/python.exe -m pytest tests/test_threads.py -v

tests/test_threads.py::test_task_thread_is_saved_and_continued PASSED    [ 25%]
tests/test_threads.py::test_ask_uses_new_thread_each_call PASSED         [ 50%]
tests/test_threads.py::test_run_counts_only_this_runs_messages PASSED    [ 75%]
tests/test_threads.py::test_consumer_uses_task_thread PASSED             [100%]
============================== 4 passed in 5.68s ==============================
```

## 확인하지 못한 것 / Gemini에게 요청할 검증
- 실제 서버에서 메일 소비자 스레드와 `/ask` 요청이 같은 `SqliteSaver`를 동시에 쓰는 상황은 확인하지 않았다 (`check_same_thread=False`, SqliteSaver 내부 잠금에 의존).

## 커밋 해시
- `c921f22`
