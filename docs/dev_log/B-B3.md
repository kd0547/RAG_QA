# B-B3 search_documents 스니펫화 · rerank_documents ID화

## 변경 파일
- `tools/tool.py`
  - `search_documents`: 청크마다 `origin_type='chunk'` 근거 등록(본문 전체 저장). 반환 항목 `{evidence_id, file_id, group_id, source(파일명), page, chunk_index, snippet(300자), score}`. `text`·`id`(청크 ID) 키 제거.
  - `rerank_documents(query, evidence_ids, top_n)`: 현재 소유자의 근거만 `get_many`로 본문을 가져와 리랭크. 반환은 evidence_id 목록. 리랭커 미로드 시 입력 순서. `record_use(…, 'rerank')`.
  - `check_answerability(question, evidence_ids)`: 본문을 서버가 조회 (B6에서 도구 자체를 제거).
  - `_owned_evidence()`: 다른 소유자·없는 ID는 빼고 WARNING 로그.
- `agent/prompt.py`: rerank·check 단계 문구를 evidence_id로 (B7에서 전면 교체)
- `tests/test_search_tools.py`(신규)

## 결정한 것
1. **리랭커가 없을 때는 입력 순서대로 앞 `top_n`개.** "입력 순서를 그대로"와 "top_n개까지"를 함께 지켰다. 빈 목록은 돌려주지 않는다.
2. **검색 결과의 `source`는 파일명.** 예전에는 디스크 경로였는데 이제 경로로 읽는 도구가 없다. `PureWindowsPath(...).name`이라 윈도우·리눅스 경로 모두 처리한다.
3. **청크 근거의 `revision`은 None.** 청크는 업로드·검수 때 다시 만들어진다. 같은 청크인지는 본문 해시로 가린다 (B1 결정 2).
4. **`search_documents`도 실행 컨텍스트가 필요하다.** 근거로 등록해야 하기 때문이다. 에이전트 밖에서 쓰는 곳은 없다 (`/search` 라우터는 이 도구를 쓰지 않음, 확인함).

## 테스트: 명령과 출력
```
.venv/Scripts/python.exe -m pytest tests/test_search_tools.py -v

tests/test_search_tools.py::test_search_returns_snippet_and_evidence_id PASSED [ 25%]
tests/test_search_tools.py::test_rerank_without_model_keeps_input_order PASSED [ 50%]
tests/test_search_tools.py::test_rerank_with_model_sorts_by_score PASSED [ 75%]
tests/test_search_tools.py::test_other_owner_ids_are_ignored_with_warning PASSED [100%]

============================== 4 passed in 6.00s ==============================
```
(B3 커밋 시점에는 `check_answerability`가 ID로 본문을 읽고 남의 근거를 빼는지 검사하는 테스트도 있었다. B6에서 도구와 함께 지웠다.)

## 확인하지 못한 것 / Gemini에게 요청할 검증
- 실제 리랭커(`BAAI/bge-reranker-v2-m3`)로 점수 정렬을 돌려 보지 않았다 (`predict`를 대역으로 바꿈).

## 커밋 해시
- `896f097`
