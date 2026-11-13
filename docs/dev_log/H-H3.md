# H-H3 추출할 때 사양 DB의 정식 이름에 맞추기

## 변경 파일
- `graph_rag/extractor.py`
  - `extract_page_graph(text, llm=None, concepts=None, known=None)`: `known`은 `[{"type", "name", "aliases"}]`
  - `_system_prompt(concepts, known)`: `known`이 있으면 "## 사양 DB의 정식 이름" 절을 붙인다 — "아래 목록의 대상과 같은 것이면 목록의 이름을 name으로 쓰고 문서 표기는 aliases에 넣는다", 목록에 없는 제품은 문서 표기 그대로, 비슷해도 다른 모델은 다른 대상(N5800 / N5800-GB70-PU02)
  - `_keep_grounded(graph, text, known_norms=None)`: 이름이 페이지에 있으면 통과(예전과 같음). 이름이 **정식 이름 목록에 있고** 별칭 중 하나가 페이지에 있어도 통과. 별칭은 페이지에 있는 것만 남긴다
- `graph_rag/service.py`
  - `spec_names()`(설정이 꺼져 있으면 None), `known_names(names, text)`: 제품은 전부, 부품은 그 페이지 텍스트에 정규화 문자열로 나오는 것만
  - `index_page`·`index_file`: 설정이 켜져 있을 때만 `known=`을 넘기고 `replace_page(…, link_specs=True)`. 꺼져 있으면 `known` 인자 자체를 넘기지 않는다 (추출 호출이 예전과 똑같다). 파일 하나를 뽑는 동안 사양 DB 이름은 한 번만 읽는다
- `repository/graph_repository.py` `replace_page(…, link_specs=False)`: 제품·부품 개체의 이름이나 별칭이 사양 DB 모델명과 (정규화해) 같으면 `ref_type`·`ref_id`를 단다. `_spec_ref_map`
- `tests/test_graph.py`: 기존 테스트의 가짜 추출 함수가 `known` 인자를 받게 했다 (기본 설정이 켜짐이라 새 인자가 넘어간다)
- `tests/test_graph_spec.py`: 4건 추가 (전체 14건)

## 결정한 것
1. **별칭으로 통과시키는 것은 정식 이름에만 허용했다.** 지시서는 "정식 이름이 아니라 별칭 중 하나가 페이지에 있으면 통과"다. 목록에 없는 이름(LLM이 지어낸 이름)까지 별칭으로 통과시키면 `_keep_grounded`가 지어낸 이름을 막지 못한다. 그래서 이름이 정식 이름 목록에 있을 때만 별칭으로 통과시킨다. 목록이 없으면(설정 꺼짐) 예전과 같다.
2. **제품 이름은 모델명을 담을 때만 "다른 표기"로 프롬프트에 넣는다** (H2의 별칭 규칙과 같다). `Pro`·`Home` 같은 이름을 다른 표기로 주면 LLM이 문서의 "Pro"를 파생 모델로 바꿀 수 있다.
3. ref는 개체에 아직 ref가 없을 때만 단다.
4. 이미 추출된 문서를 자동으로 다시 뽑지 않는다. 다시 뽑기는 기존 화면 기능(`/graph/rebuild`)을 쓴다.

## 테스트: 명령과 출력
```
.venv/Scripts/python.exe -m pytest tests/test_graph_spec.py -q
14 passed in 2.40s

.venv/Scripts/python.exe -m pytest tests -q
433 passed in 55.78s
```
| 지시서 테스트 | 테스트 |
|---|---|
| 사양 DB의 제품을 다른 표기로 적은 문서 두 개가 같은 개체에 붙는다 | `test_two_documents_with_different_notations_attach_to_one_entity` ("A650 Pro 모델 사양서" + "A650-GA70-PU02 KC 안전확인" → 한 개체, ref = 파생 모델, 프롬프트 문장·목록 확인) |
| `GRAPH_SPEC_SEED_ENABLED=false`면 추출 프롬프트가 지금과 같다 | `test_flag_off_keeps_old_prompt_and_no_refs` (프롬프트가 `_system_prompt(concepts)`와 같고 ref 없음) |
| (추가) 페이지에 나온 부품만 목록에, 그 부품 개체에 ref, 타사 모델은 ref 없음 | `test_components_on_page_get_ref_and_others_not_listed` |
| (추가) 별칭 통과는 정식 이름에만 | `test_keep_grounded_needs_name_or_alias_of_known_name` |
