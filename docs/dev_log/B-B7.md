# B-B7 프롬프트 v2와 설정값

## 변경 파일
- `agent/prompt.py`: `SYSTEM_PROMPT_TEMPLATE`를 v2로 새로 썼다. `PROMPT_V2_NAME = "v2 근거 ID"`. `GRAPH_GUIDE` 삭제(본문에 흡수). `render_prompt`는 상위 개념 목록만 덧붙인다
- `repository/prompt_repository.py`: `ensure_seeded(name, content)`, `ensure_v2()`
- `main.py`: lifespan에서 `ensure_default()` 뒤 `ensure_v2()`
- `config.py`: `SEARCH_TOP_K=5`, `RERANK_TOP_N=3` (환경변수로 덮어쓰기 가능)
- `tools/tool.py`: `search_documents.top_k`, `rerank_documents.top_n` 기본값을 config에서
- `app/routers/questions.py`: `QuestionRequest.query_top_n/rerank_top_n` Optional + 무시한다는 docstring. 주석 처리돼 있던 top_n 안내 코드 삭제. `/ask/attachments`의 같은 Form 필드도 Optional
- `tests/test_prompt_v2.py`(신규), `tests/test_graph.py`(GRAPH_GUIDE 테스트 → 상위 개념 목록 테스트)

## v2 프롬프트 구성 (지시서 대응)
- 역할 1문단: R&D 문의 답변, 문서·첨부 근거로만, 없으면 찾지 못했다고
- 도구 역할 표: graph_search, list_documents, grep_documents, search_documents, rerank_documents, read_pages, read_attachment, list_evidence
- 시작 규칙 3줄: 모델명·인증 → graph_search/grep_documents, 자유 서술 → search_documents, 특정 문서 → list_documents+read_pages (첨부는 read_attachment)
- 불변 조건: 인용하는 사실·수치는 read_pages/read_attachment로 읽은 페이지에 있어야 한다, 상위 개념 펼침 시 종류별 "문서 없음"
- 출력 형식: 마지막 줄 `근거: e…, e…` / `근거: 없음`
- 삭제한 것: 절차 번호, `start=0`, "최대 2회", `check_answerability`, `read_source_document`

## 결정한 것
1. **v2를 넣고 선택하는 것은 한 번만** (이름 `v2 근거 ID`가 이미 있으면 아무것도 하지 않음). 담당자가 다른 프롬프트를 고르면 재시작해도 그 선택이 유지된다. 기존 행은 지우거나 고치지 않는다.
2. **`DEFAULT_PROMPT`(= 템플릿 원문)도 v2가 된다.** 운영 DB의 기존 기본 프롬프트 행은 `ensure_default`가 덮어쓰지 않는다 (테스트로 확인). 새로 만드는 DB에서만 기본 프롬프트가 v2다.
3. **예전 프롬프트(v1, '테스트' 등)를 선택하면 그래프 안내가 더 붙지 않는다.** 지시서대로 GRAPH_GUIDE를 템플릿에 흡수했기 때문이다. 예전 프롬프트는 없어진 도구를 설명하고 있어 쓰면 안 된다.
4. 화면(`frontend`)은 지시서대로 손대지 않았다. 계속 `query_top_n`·`rerank_top_n`을 보내지만 서버는 받기만 하고 무시한다.

## 테스트: 명령과 출력
```
.venv/Scripts/python.exe -m pytest tests/test_prompt_v2.py tests/test_graph.py::test_prompt_adds_concept_list_only_when_graph_has_concepts -v

tests/test_prompt_v2.py::test_v2_template_content PASSED                 [ 20%]
tests/test_prompt_v2.py::test_ensure_v2_inserts_once_and_keeps_existing PASSED [ 40%]
tests/test_prompt_v2.py::test_tool_defaults_come_from_config PASSED      [ 60%]
tests/test_prompt_v2.py::test_ask_accepts_request_without_top_n PASSED   [ 80%]
tests/test_graph.py::test_prompt_adds_concept_list_only_when_graph_has_concepts PASSED [100%]

============================== 5 passed in 6.07s ==============================
```

## 확인하지 못한 것 / Gemini에게 요청할 검증
- **운영 서버에는 아직 v2가 없다.** 사용자의 서버가 2026-11-12 17:41:58에 B6까지의 코드로 재시작됐다 (`logs/` "서버 준비 완료"). 운영 DB의 prompt는 `1 기본 프롬프트`, `2 테스트(선택됨)`뿐이다. 선택된 '테스트' 프롬프트는 없어진 도구(read_source_document, check_answerability)를 설명하고 있다. **다시 재시작하면** `ensure_v2`가 v2를 넣고 선택한다.
- v2 프롬프트로 실제 모델이 도구를 고르는 품질은 기준선 10문항 비교(C절)에서 봐야 한다.

## 커밋 해시
- `e51c16b`
