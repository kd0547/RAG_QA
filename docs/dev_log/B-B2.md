# B-B2 read_pages · list_documents · grep_documents

## 변경 파일
- `tools/tool.py`: `read_pages`, `list_documents`, `grep_documents`, 공통 함수 `read_page_texts`·`_register_read`·`_context_error`. `read_source_document`와 그 캐시(`_extract_text`, `DOCS_ROOT`) 제거
- `repository/file_page_repository.py`: `page_counts()`, `search_text(pattern, file_id, limit)`
- `agent/agent.py`: `TOOLS`에 세 도구 추가, `read_source_document` 제거
- `agent/prompt.py`: `read_source_document` 문구를 `read_pages`로 (B7에서 전면 교체)
- `tests/test_doc_tools.py`(신규)

## 결정한 것
1. **`read_pages` 반환 형식:** `{file_id, original_name, pages:[{evidence_id, page, text}], truncated, next_pages?, missing_pages?, message?}`. 오류는 `{"error": …}`.
2. **분량 초과 시:** 남은 분량만큼 페이지 앞부분을 보여 주고 그 항목에 `truncated: true, page_chars`를 붙인다. 아직 못 읽은 요청 페이지는 `next_pages`에 담는다. **등록하는 근거는 페이지 전체**다 (같은 페이지는 잘린 정도와 관계없이 같은 근거 ID).
3. **`max_chars` 상한 20000.** 한 페이지(예: 큰 xlsx 시트)가 20000자를 넘으면 `read_pages`로 끝까지 읽을 수 없다. 이때는 안내 문구로 `grep_documents`를 권한다. 지시서 시그니처에 시작 위치 인자가 없어 넣지 않았다 → 아래 "확인하지 못한 것".
4. **xlsx처럼 같은 페이지 번호의 행이 여럿이면** `"\n\n"`로 잇고, `page_id`는 첫 행, `revision`은 행들의 `updated_at` 중 가장 늦은 값.
5. **`grep_documents`의 LIKE 1차 필터는 정규식 기호가 없을 때만 쓴다.** `"C910G|Ti600s"` 같은 정규식을 LIKE로 거르면 하나도 안 나오기 때문이다. 기호가 있으면 행 전체를 Python `re`로 본다. 행마다 첫 일치 하나, snippet은 앞뒤 80자이고 공백·줄바꿈은 한 칸으로 합친다. 잘못된 정규식은 오류 dict.
6. **`list_documents`는 `page_counts()` 한 번으로** 모든 파일의 페이지 수를 구한다 (파일마다 `has_pages`를 부르지 않음). `has_pages = page_count > 0`.
7. 실행 컨텍스트(owner/run) 밖에서 `read_pages`를 부르면 오류 dict를 돌려준다.

## 테스트: 명령과 출력
```
.venv/Scripts/python.exe -m pytest tests/test_doc_tools.py -v

tests/test_doc_tools.py::test_read_pages_registers_evidence PASSED       [ 11%]
tests/test_doc_tools.py::test_reviewed_text_is_reflected_immediately PASSED [ 22%]
tests/test_doc_tools.py::test_xlsx_blocks_of_same_sheet_are_joined PASSED [ 33%]
tests/test_doc_tools.py::test_file_without_pages_is_not_parsed PASSED    [ 44%]
tests/test_doc_tools.py::test_read_pages_truncates_to_max_chars PASSED   [ 55%]
tests/test_doc_tools.py::test_read_pages_needs_run_context PASSED        [ 66%]
tests/test_doc_tools.py::test_list_documents_filters_and_counts PASSED   [ 77%]
tests/test_doc_tools.py::test_grep_documents_literal_regex_and_errors PASSED [ 88%]
tests/test_doc_tools.py::test_agent_reads_pages_end_to_end PASSED        [100%]

============================== 9 passed in 6.70s ==============================
```
- 검수 반영: `update_text` 뒤 바로 `read_pages` → 바뀐 문자열, 새 근거 ID (`test_reviewed_text_is_reflected_immediately`)
- 페이지 없는 파일: `tools.parse_file`과 `parser.file_parser.parse_file` 둘 다 대역으로 바꾸고 호출 0회 (`test_file_without_pages_is_not_parsed`)
- end-to-end: 대역 모델이 grep → read_pages → 답변, 실행 기록에 읽은 근거 1건

## 확인하지 못한 것 / Gemini에게 요청할 검증
- **20000자를 넘는 한 페이지:** 기준선의 `SSD_성능_비교.xlsx`(49,933자)가 시트 하나라면 `read_pages`로는 앞 20000자만 읽힌다. 개발 서버의 `file_page`에서 이 파일의 페이지별 길이 확인이 필요하다. 길다면 `read_pages`에 시작 위치를 더할지 설계 결정이 필요하다 (구현자가 정하지 않음).
- 개발 서버 문서 17개로 `grep_documents` 속도를 재지 않았다 (정규식은 전체 행을 훑는다).

## 커밋 해시
- `d711294`
