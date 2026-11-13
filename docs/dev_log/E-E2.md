# E-E2 사양 서비스 `agent/spec_service.py`

## 변경 파일
- `agent/spec_service.py`(신규): DB를 읽기만 하는 함수들. LLM 없음. 저장소는 `repository.spec_repo.db`의 연결만 쓴다
  - (가) `resolve_items(query, owner_type=None, kind=None, limit=10)`, `find_owner(owner_type, owner_id)`
  - (나) `effective_specs(owner_type, owner_id, attribute_keys=None)`
  - (다) `to_attribute_unit` — E1의 `entity/spec_units.py`를 다시 내보낸다. 값 문자열은 `read_number`로 읽는다
  - (라) `compare(owner_type, owner_id, conditions)`, `summarize(results)`
  - (마) `search_items(owner_type=None, kind=None, conditions=None, query=None, limit=20)`
  - E3 도구용 `list_attributes(category=None, kind=None)`
- `tests/test_spec_service.py`(신규) 15건

## 결정한 것
1. **대상 찾기 (가)**
   - 완전 일치: 정규화한 모델명 또는 제품 이름이 질문과 같으면 그것만 돌려준다.
   - 어절 포함: 하이픈으로 이은 모델명은 한 어절이다 (`N5800` ≠ `N5800-GB70-PU02`). 질문의 어절이 모델명 어절에 모두 있거나(`Samsung 980` → `Samsung 980 …` 전부), 모델명 어절이 질문에 모두 있을 때(`Samsung 980 500GB 대체 가능한 모델` → `Samsung 980 500GB`)만 맞는다. 일부 어절만 겹치는 것(`500GB`만 같음)은 후보로 내지 않는다 — 부품 122개 중 같은 용량이 많아서다.
   - 상위·파생 모델이 함께 맞으면 상위만 돌려주고 파생은 `variants`에 모델명으로 싣는다. 제품 결과에는 항상 `variants`(자식 모델명)와 `parent_model`이 있다.
   - `find_owner`는 id가 없으면 **정확한 모델명**으로도 찾는다 (모델이 id 대신 모델명을 넘기는 경우). 같은 모델명이 둘 이상이면 찾지 않는다.
2. **유효 사양 (나)**
   - 자기 값 → (자기 값이 없는 속성 중) `inheritable=1`이고 `cert`가 아닌 속성을 **가장 가까운** 상위 모델에서 → 연결된 부품의 값 순서. 상위 모델에 값이 여러 행(옵션)이면 그 행을 모두 가져온다.
   - 부품 값은 제품 자기 값이 있어도 같이 싣는다 (`via_component`로 구분). 연결이 옵션이면 값도 옵션이다.
   - 상위 모델의 부품 연결은 물려받지 않는다 (연결되지 않은 부품의 값은 제품 사양에 넣지 않는다).
   - `attribute_keys`를 주면 `missing_attributes`(사전에 있지만 값 없음)와 `unknown_attributes`(사전에 없는 키)를 함께 돌려준다.
3. **비교 (라)**
   - 판정 합치기: 기본 값 중 하나라도 만족 → `met`. 기본 값 중 판정 불가가 있으면 → `unknown` (기본 값을 모르는데 옵션으로 만족한다고 쓰지 않는다). 옵션 값만 만족 → `met_with_option`. 값이 있고 어느 것도 만족하지 않음 → `not_met`. 값 없음 → `unknown`.
   - number: 조건 `unit`을 주면 그 단위를 속성 단위로 바꾼다. 비우면 조건 값에 붙은 단위를 읽고(`"1000GB"`), 없으면 속성 단위로 본다. 저장 값도 `value_num`이 아니라 `value_text`를 같은 규칙으로 읽는다 (지시서 (다) "저장된 값도 같은 규칙으로"). 비교는 소수 9자리에서 반올림해 `1.5kg`과 `1500g`이 같다. `contains`는 숫자 속성에 쓰지 않는다(`unknown`). `exists`는 값이 있으면 만족.
   - bool: `exists`는 "지원(1)"과 같고, `==`는 조건 값을 예/아니오로 읽는다. 저장 값 0이면 `not_met`(명시적 미지원), 행이 없으면 `unknown`.
   - text: `==`는 정규화해 같을 때, `contains`는 정규화해 포함할 때만 `met`. 나머지는 `unknown`이고 사유에 조건 값과 저장 값을 둘 다 적는다.
   - 결과마다 판정에 쓴 값 목록(`value_text, is_option, inherited_from, via_component`)과 사유. 사유는 값마다 환산한 숫자와 ✓/✗를 적는다.
   - 없는 대상은 `None`(도구가 오류 dict로 바꾼다), 없는 속성 키는 그 조건만 `unknown`.
4. **조건으로 찾기 (마)**: `query`와 `conditions`를 함께 주면 `query`로 찾은 대상만 비교한다. 정렬은 `met` 많은 순 → `met_with_option` 많은 순 → `not_met` 적은 순 → `unknown` 적은 순 → 모델명. 대상마다 `met, met_with_option, not_met, unknown` 개수와 `not_met_attributes`, `unknown_attributes`, `option_attributes`. 결과는 후보라 값 본문을 싣지 않는다.

## 테스트: 명령과 출력
```
.venv/Scripts/python.exe -m pytest tests/test_spec_service.py -q
15 passed in 3.71s

.venv/Scripts/python.exe -m pytest tests -q
409 passed in 51.60s
```
| 지시서 테스트 | 테스트 |
|---|---|
| 자식 값이 부모 값보다 먼저, `inheritable=0`은 물려받지 않음, `cert`는 1로 못 바꿈 | `test_child_value_wins_over_parent`, `test_inherits_only_allowed_attributes_from_nearest_parent`, `test_grandchild_takes_nearest_ancestor`, `test_cert_attribute_never_inherited` |
| RAM 32GB 이상: 16 → not_met, 옵션 32 → met_with_option, 32 → met, 값 없음 → unknown, 최대 용량은 따로 | `test_ram_32_verdicts_base_option_missing_and_max_separate` |
| `1.5kg` = `1500g`, GB 속성의 `1TB` = 1,000GB, 모르는 단위 unknown | `test_units_kg_g_and_tb_gb_and_unknown_unit` |
| 연결되지 않은 부품 값 제외, 옵션 연결 값은 옵션 | `test_only_linked_component_values_and_option_link_is_option` |
| `N5800`으로 `N5800-GB70-PU02`를 같은 대상으로 찾지 않음 | `test_resolve_keeps_n5800_and_variant_apart` |
| 값 없음과 bool 미지원이 다름 | `test_no_value_and_explicit_unsupported_bool_differ` |
| text 표기만 다르면 unknown | `test_text_attribute_same_or_unknown_never_not_met` |
| 기준 부품 값으로 만든 조건 → 기준 이상인 부품만 met 전부 | `test_search_with_reference_conditions_lists_only_better_parts_as_all_met` |
| (추가) 없는 속성 키·숫자 없는 조건·모르는 op, 어절 포함 찾기, 조건 없는 후보, 속성 사전 | 나머지 4건 |

## 확인하지 못한 것
- 운영 사양 DB(부품 122개)로 성능을 재지 않았다. 조건 찾기는 대상마다 값 조회 2~3번이다 (9절 통합 확인에서 시간을 본다).
