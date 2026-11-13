# H-H2 사양 DB를 그래프에 심기 `GraphRepository.seed_specs()`

## 변경 파일
- `repository/graph_repository.py`
  - `seed_specs()`: spec 관계를 지우고 다시 넣는다. 반환 `{products, components, variant_of, has_component, blocked}`
  - `_link_spec_entity()`: 그 대상을 이미 가리키는 개체 → 같은 이름(정규화)의 개체 → 새 개체 순서로 찾고 `ref_type`·`ref_id`를 단다
  - `_add_alias()`, `spec_names()`(H3에서 씀)
- `config.py`: `GRAPH_SPEC_SEED_ENABLED` (기본 켬)
- `main.py` lifespan: 상위 개념 심기 뒤에 `graph_repo.seed_specs()` (꺼져 있으면 INFO 로그만, 실패해도 서버는 뜬다)
- `app/routers/specs.py`: `reseed_spec_graph(reason)` — 제품 등록·수정·삭제, 부품 연결·해제, 부품 삭제, 연결된 부품 수정 뒤에 부른다. 실패해도 요청은 성공(사양 저장은 끝남)
- `app/routers/spec_import.py`: 표 가져오기에서 새 제품·부품이나 상위 모델이 생기면 다시 심는다
- `tests/test_graph_spec.py`: 6건 추가 (전체 10건)

## 동작
- 제품은 전부: `product.model` → `product` 개체, `parent_id` → `variant_of`(파생 → 상위)
- 부품은 제품에 연결된 것만: `product_component` → `has_component`, `is_option`에 옵션 여부. 연결되지 않은 부품은 심지 않는다 (운영은 연결 0건이라 지금은 부품이 하나도 심어지지 않는다)
- `origin='spec'` 관계만 지우고 다시 넣는다. 문서에서 뽑은 관계(`extract`)·사람이 넣은 관계(`manual`)·상위 개념(`seed`)은 건드리지 않는다
- 화면에서 지운 관계(`graph_relation_block`)는 되살리지 않는다 (`blocked`로 센다)
- 이미 문서에서 뽑힌 같은 이름의 개체가 있으면 새로 만들지 않고 그 개체에 ref를 단다
- 사양 DB에서 사라진 제품·부품을 가리키는 ref는 지운다. 그 개체가 문서에도 안 나오고 관계도 없으면 정리된다

## 결정한 것
1. **제품 이름은 모델명을 담을 때만 별칭으로 넣는다.** 지시서는 "`name`은 별칭"이다. 운영 제품 이름에는 `Home`, `Pro`(A650 파생 모델 두 개)가 있다. 그래프 검색은 "별칭이 질문 안에 들어 있으면" 개체를 찾으므로, `Pro`를 별칭으로 넣으면 "Windows 11 Pro"가 들어간 모든 질문에 A650-GA70-PU02가 걸린다. 그래서 `N5800 14세대 노트북`, `A650 Series`처럼 정규화한 모델명을 담은 이름만 별칭으로 넣었다. (지시서 규칙을 좁힌 것이라 R-summary "다르게 한 것"에 적는다.)
2. 다시 심는 시점은 API 계층(라우터)에 두었다. 저장소(`SpecRepository`)가 그래프 저장소를 부르게 하면 두 저장소가 서로를 알게 된다.
3. 사양 값(속성 값)만 바뀌는 요청(`/specs/values`)에서는 다시 심지 않는다. 그래프에는 제품·연결만 들어가기 때문이다.
4. 같은 이름의 개체가 이미 **다른** 사양 대상을 가리키면 ref를 바꾸지 않는다 (정규화한 모델명이 겹치는 드문 경우).

## 테스트: 명령과 출력
```
.venv/Scripts/python.exe -m pytest tests/test_graph_spec.py -q
10 passed in 2.00s

.venv/Scripts/python.exe -m pytest tests -q
429 passed in 55.34s
```
| 지시서 테스트 | 테스트 |
|---|---|
| 그래프를 다시 뽑아도 spec 관계와 ref 개체가 남는다. 사양 DB에서 연결을 지우면 spec 관계가 사라진다 | `test_reextract_keeps_spec_relations_and_unlink_removes_them` |
| 화면에서 지운 spec 관계가 다시 심어도 돌아오지 않는다 | `test_deleted_spec_relation_is_not_reseeded` |
| (추가) 제품 전부·연결된 부품만·옵션·별칭 규칙 | `test_seed_products_variants_and_linked_components_only` |
| (추가) 같은 이름 개체 재사용, 두 번 심어도 같음 | `test_seed_reuses_extracted_entity_and_is_idempotent` |
| (추가) 지운 제품의 ref 정리 | `test_deleted_product_ref_is_cleared` |
| (추가) 사양 API 변경 뒤 다시 심기, 설정을 끄면 안 심음 | `test_router_changes_reseed_and_flag_off_skips` |
