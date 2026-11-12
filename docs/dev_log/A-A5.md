# A-A5 한국어 개체 매칭

## 변경 파일
- `repository/graph_repository.py`
  - `_query_tokens`(신규): 접두 일치에 쓸 질문 토큰 = (a) 영숫자 식별자 `[A-Za-z0-9]+(?:[-_.][A-Za-z0-9]+)*`, (b) 공백·쉼표로 나눈 어절, (c) 어절 끝 조사 하나를 뗀 것. 모두 `normalize` 후 `MIN_PARTIAL_LEN`(3)자 이상.
  - `find_entities`: SQL은 예전처럼 `instr`(별칭이 질문 안에 있음) + `LIKE 'tok%'`로 후보를 넉넉히 뽑되 `a.alias` 원문을 같이 가져온다. Python에서 `instr` 조건으로 잡힌 행은 통과, `LIKE`로만 잡힌 행은 별칭 원문을 공백으로 나눠 `normalize`한 어절 집합에 질문 토큰이 정확히 있을 때만 통과. 개체별로 가장 긴 별칭 길이로 정렬 (예전 `max(length(alias_norm))`과 같은 순서).
- `tests/test_graph.py`: 임시 DB에 `N5800 14세대`, `N5800-GB70-PU02`, `R-R-TGE-N5800`, `A650`, 상위 개념 `KC 인증`을 심고 확인.

## 결정한 것
- 조사 목록은 지시서 그대로이고, 긴 것부터 본다 (`에서`를 `에`보다 먼저, `으로`를 `로`보다 먼저). 어절당 하나만 뗀다. 어절 전체가 조사인 경우("의")는 떼지 않는다.
- SQL의 `GROUP BY`·`LIMIT`을 없애고 Python에서 거른 뒤 `limit`을 적용했다. 거르기 전에 자르면 통과할 개체가 잘릴 수 있다. 그래프 별칭 테이블은 작다(로컬 0~수백 행).

## 테스트: 명령과 출력
```
.venv/Scripts/python.exe -m pytest tests/test_graph.py -v   (마지막 20줄)

tests/test_graph.py::test_extractor_drops_names_not_on_page_and_adds_kc_number PASSED [ 10%]
tests/test_graph.py::test_extractor_fills_relation_endpoints_and_keeps_known_concepts PASSED [ 15%]
tests/test_graph.py::test_extracted_concept_link_joins_kc_expansion PASSED [ 21%]
tests/test_graph.py::test_empty_page_does_not_call_llm PASSED            [ 26%]
tests/test_graph.py::test_seed_merges_extracted_certification_into_concept_member PASSED [ 31%]
tests/test_graph.py::test_kc_question_expands_concept_and_ranks_documents PASSED [ 36%]
tests/test_graph.py::test_partial_model_name_matches PASSED              [ 42%]
tests/test_graph.py::test_no_match_tells_agent_to_use_vector_search PASSED [ 47%]
tests/test_graph.py::test_replacing_page_and_deleting_file_clean_up PASSED [ 52%]
tests/test_graph.py::test_index_file_combines_blocks_and_skips_failed_pages PASSED [ 57%]
tests/test_graph.py::test_prompt_adds_graph_guide_only_when_graph_is_available PASSED [ 63%]
tests/test_graph.py::test_korean_particle_is_stripped_for_model_name PASSED [ 68%]
tests/test_graph.py::test_model_name_alone_matches_word_prefix PASSED    [ 73%]
tests/test_graph.py::test_longer_part_number_is_not_confused_with_model PASSED [ 78%]
tests/test_graph.py::test_kc_spacing_gives_same_result PASSED            [ 84%]
tests/test_graph.py::test_cert_number_not_matched_by_model_suffix PASSED [ 89%]
tests/test_graph.py::test_korean_suffix_is_not_removed_from_alias_words PASSED [ 94%]
tests/test_graph.py::test_query_tokens_add_particle_stripped_candidates PASSED [100%]

============================= 19 passed in 1.59s ==============================
```
지시서 테스트 대응: `"N5800의 사양"` → `["N5800 14세대"]` / `"N5800"` → `["N5800 14세대"]` / `"N5800-GB70-PU02 인증"` → `["N5800-GB70-PU02"]` (N5800 14세대 0건) / `"KC인증 자료"` == `"KC 인증 자료"` == `["KC 인증"]` / `"N5800"`에 `R-R-TGE-N5800` 없음.

## 확인하지 못한 것 / Gemini에게 요청할 검증
- **남은 비대칭:** 별칭이 붙여 쓴 한 어절(예: `"KC인증서 원본"`)이고 질문이 띄어 쓴 경우(`"KC 인증서"`)는 접두 일치 경로에서 서로 다르게 나올 수 있다. 질문 토큰 `kc인증서`가 없기 때문이다. 지시서의 KC 사례는 별칭 전체가 질문 안에 들어가는 `instr` 경로로 잡혀 결과가 같다. 개발 서버의 실제 별칭으로 확인 요청.
- 개발 서버 그래프(문서 17개)로 실제 질문을 넣어 보지 않았다. 로컬 DB는 `product_component` 0건, 그래프 거의 비어 있음.
- 영숫자 식별자 토큰 `N5800`이 `"N5800-GB70-PU02 인증"`에서 나오지 않는 것은 정규식이 하이픈 연결을 한 덩어리로 잡기 때문이다. 질문이 `"N5800 GB70"`처럼 띄어 쓰면 `N5800 14세대`도 잡힌다 (의도된 동작으로 판단).

## 커밋 해시
- `986e67a`
