# A-A2 출처 수집 통일·2중 적재 제거

## 변경 파일
- `agent/agent.py`
  - `run_agent`의 인라인 출처 수집을 지우고 `_collect_sources`를 쓴다. (예전 코드는 문자열 content를 `json.loads` 한 뒤 `sources.extend`를 하고, 아래 `isinstance(content, list)` 분기에서 한 번 더 `extend`해 같은 청크가 두 번 들어갔다.)
  - `_collect_sources`: `search_documents`·`rerank_documents`에 더해 `graph_search` 결과를 받는다. 청크 ID(없으면 `(source, page, text)`) 기준으로 중복 제거.
  - `_graph_sources`(신규): `graph_search`의 `documents[*]`를 페이지마다 `{"id": "graph:{file_id}:{page}", "file_id", "source", "page", "text": "개체: ...", "score": None}` 한 건으로 바꾼다.
- `tests/conftest.py`(신규): 테스트 격리 장치 (아래 "결정한 것").
- `tests/test_agent_sources.py`(신규).

## 결정한 것
- 그래프 출처의 `source`에는 `original_name`(파일명)을 넣었다. 지시서는 `"source"` 키만 정했고, `graph_search`의 `source`는 디스크 경로다. `task_sources.source`는 "문서명" 컬럼이고 A1이 어차피 파일명만 내보내므로 처음부터 파일명을 넣었다. `original_name`이 없으면 `source`(경로)를 쓴다.
- **`tests/conftest.py` 추가.** `agent.agent`를 임포트하면 `repository` 패키지가 운영 DB(`storage/mail.db`)를 열어 스키마를 적용하고, `repository.embedding_repository`가 운영 Chroma(`storage/chroma`)를 연다. A4에서 스키마가 바뀌므로 테스트 실행만으로 운영 DB가 바뀌게 된다 (지시서 0-3 "운영 DB에 쓰지 않는다" 위반). 그래서 conftest가
  1. 운영 DB 경로로 가는 `sqlite3.connect`를 세션 임시 폴더로 돌리고,
  2. `repository.embedding_repository`에 빈 대역 모듈을 미리 넣고 (기존 업로드 테스트들은 각자 monkeypatch로 덮어쓰므로 영향 없음),
  3. `tests/parser.py`가 `parser` 패키지를 가리지 않게 진짜 패키지를 먼저 캐시하고,
  4. 메일 모듈이 임포트 시점에 읽는 계정 환경변수(`MAIL_ID` 등)에 더미 값을 넣는다 (`.env`의 실제 계정이 테스트에 들어오지 않게).
  확인: 전체 테스트 실행 전후 `storage/mail.db` 수정 시각이 `2026-11-10 17:20:49`로 그대로다.

## 테스트: 명령과 출력
```
.venv/Scripts/python.exe -m pytest tests/test_agent_sources.py -v

tests/test_agent_sources.py::test_search_and_rerank_same_chunk_counted_once PASSED [ 20%]
tests/test_agent_sources.py::test_single_search_result_gives_one_source PASSED [ 40%]
tests/test_agent_sources.py::test_graph_documents_become_one_source_per_page PASSED [ 60%]
tests/test_agent_sources.py::test_graph_without_match_adds_nothing PASSED [ 80%]
tests/test_agent_sources.py::test_run_agent_uses_collect_sources PASSED  [100%]

============================== 5 passed in 5.49s ==============================
```

## 확인하지 못한 것 / Gemini에게 요청할 검증
- 실제 LLM으로 `run_agent`를 돌려 보지 않았다 (`_invoke_logged`를 대역으로 바꿔 확인). 지시서 주의대로 단계 B에서 출처 원천이 evidence로 바뀌므로 이 이상 만들지 않았다.
- 그래프 출처는 `score=None`이라 `get_source_files`의 평균 점수에서 빠지고, 점수 없는 파일은 첨부 후보 목록의 뒤쪽에 놓인다. 의도한 동작이지만 화면에서 확인하지 않았다.

## 커밋 해시
- `9026f93`
