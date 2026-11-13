# H-H4 그래프 검색 결과를 사양으로 잇기

## 변경 파일
- `repository/graph_repository.py`
  - `find_entities`: 항목에 `ref_type`, `ref_id`. **다른 개체의 더 긴 표기 안에만 들어 있는 개체는 뺀다** (상위 개념 제외, 아래 결정 1)
  - `parents_of(entity_ids)`: `variant_of`로 상위 모델 찾기
  - `_RELATION_COLUMNS`에 `is_option`
- `graph_rag/service.py` `search_graph`
  - `matched`: `{name, type, ref_type, ref_id}`
  - 파생 모델(제품)이 matched에 있으면 상위 모델이 나온 문서를 `documents` **뒤에** 후보로 더하고 `via: "상위 모델 ○○"`를 붙인다. 이미 나온 문서는 그대로 둔다
  - 상위 모델의 관계(인증 등)는 `relations`에 넣지 않는다 (상위 모델은 `target_ids`에 들어가지 않는다)
  - `_evidence`: spec 관계는 "사양 DB" (옵션이면 "사양 DB, 옵션")
- `tools/tool.py` `graph_search` 설명: `ref_type`·`ref_id`를 `get_specs`에 넘기는 법, `via` 문서는 후보이고 상위 모델의 인증·사양이 그대로 적용된다고 쓰지 않는다
- `tests/test_graph_spec.py`: 4건 추가 (전체 18건)

## 결정한 것
1. **더 긴 표기 안에만 들어 있는 개체 빼기.** 기존 `find_entities`는 "개체 표기가 질문 안에 들어 있으면" 찾는다. 그래서 "N5800-GB70-PU02 인증"을 물으면 정규화 문자열 `n5800gb70pu02인증` 안에 `n5800`이 들어 있어 **상위 모델 N5800도 직접 찾았다.** 그러면 상위 모델의 문서가 후보가 아니라 직접 결과가 되고, 상위 모델의 인증 관계가 결과에 섞인다 (H-2 위반). 그래서 한 개체의 표기가 다른 개체의 더 긴 표기 안에만 있으면(그 긴 표기를 지운 나머지 질문에 다시 나오지 않으면) 그 개체를 뺀다. "N5800과 N5800-GB70-PU02 비교"처럼 따로 나오면 둘 다 찾는다. 상위 개념(concept)은 펼치기에 쓰이므로 빼지 않는다. 기존 그래프 테스트 30건이 그대로 통과한다.
2. 후보 문서는 직접 결과(질문 대상을 담은 순위) 뒤에 둔다. 문서 수 한도(`max_documents` 8)는 그대로라 직접 결과가 많으면 후보가 잘린다.
3. 상위 모델의 문서 중 파생 모델 문서와 같은 파일이면 `via`를 붙이지 않는다 (이미 직접 결과다).

## 테스트: 명령과 출력
```
.venv/Scripts/python.exe -m pytest tests/test_graph_spec.py -q
18 passed in 6.87s

.venv/Scripts/python.exe -m pytest tests -q
437 passed in 56.59s
```
| 지시서 테스트 | 테스트 |
|---|---|
| `graph_search("N5800")`의 matched에 `ref_type="product"`와 `ref_id` | `test_graph_search_matched_has_spec_ref` |
| `N5800`과 `N5800-GB70-PU02`가 다른 개체 (A5) | `test_n5800_and_variant_are_different_entities` (검색에서도 파생 모델만 물으면 상위 모델을 직접 찾지 않음, 둘 다 적으면 둘 다) |
| 파생 모델 질문에 상위 모델 문서가 via 표시와 함께 | `test_variant_question_gets_parent_documents_as_candidates_only` (뒤에 놓임, 상위 모델의 인증 관계 없음, variant_of 관계는 "사양 DB") |
| (추가) 도구 설명 | `test_graph_search_tool_doc_mentions_ref_and_via` |
