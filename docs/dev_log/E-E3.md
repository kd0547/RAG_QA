# E-E3 사양 도구 4개와 근거 등록

## 변경 파일
- `tools/tool.py`: `list_spec_attributes`, `search_spec_items`, `get_specs`, `compare_specs`와 근거 등록 `_register_spec_evidence`
- `agent/agent.py`
  - `BASE_TOOLS`(기존 9개) + `SPEC_TOOLS`(사양 4개), `active_tools()`가 `config.SPEC_TOOLS_ENABLED`를 **호출 때** 읽어 목록을 만든다
  - `create_rag_agent`가 `active_tools()`를 쓴다. `TOOLS = active_tools()`는 예전 이름으로 남겼다 (기존 테스트·임포트 호환)
- `agent/skill_author.py` `tool_names()`: `active_tools()`를 쓴다 → 절차 초안 생성·검사(I4)의 도구 목록에 새 도구가 자동으로 들어가고, 설정으로 끄면 빠진다
- `config.py`: `_flag()`와 `SPEC_TOOLS_ENABLED` (기본 켬, `0`/`false`면 끔)
- `tests/conftest.py` `agent_env`: `spec_repo`도 임시 DB로 바꾼다
- `tests/test_spec_tools.py`(신규) 10건

## 도구

| 도구 | 하는 일 | 근거 |
|------|---------|------|
| `list_spec_attributes(category=None, kind=None)` | 속성 사전 (키·이름·자료형·단위·분류·상속 허용) | 등록 안 함 |
| `search_spec_items(query=None, owner_type=None, kind=None, conditions=None, limit=20)` | E2 (마). `query`·`conditions` 둘 다 없으면 오류 dict | 등록 안 함 |
| `get_specs(owner_type, owner_id, attribute_keys=None)` | E2 (나). 최대 60개 값, 넘으면 `truncated`+안내 | 대상 하나에 하나 |
| `compare_specs(owner_type, owner_ids, conditions)` | E2 (라). 대상 최대 10개 (넘으면 앞 10개 + 안내) | 대상마다 하나 |

## 근거 등록
- `origin_type="spec_value"`, `source_name="사양 DB: <모델명>"`, `file_id` 없음, `revision`은 돌려준 값들의 가장 늦은 `updated_at`.
- 본문: 첫 줄 `사양 DB: <모델명> (제품|부품)`, 다음 줄부터 값마다 `속성 이름(키) = 값 [옵션] [상위 모델 ○○에서 상속] [부품 ○○]`.
  - **첫 줄에 대상 이름을 넣은 이유**: 근거 중복 제거 키(소유자·원천·파일·페이지·revision·본문 해시)에 대상이 없다. 값이 똑같은 서로 다른 대상(예: 같은 사양의 SSD 두 개)이 같은 근거 ID로 합쳐지지 않게 본문에 대상을 넣었다.
- `compare_specs`의 근거 본문은 **판정에 쓴 속성의 값만** 담는다. `get_specs`(전체)와 본문이 다르면 근거 ID도 다르다. 같은 대상·같은 값이면 같은 ID다.
- 값이 하나도 없으면 근거를 만들지 않는다 (`evidence_id: null`, "사양 DB에 이 대상의 값이 없습니다 (근거 없음). 문서에서 찾으세요.").
- 근거를 `read`로 기록하므로 B6 검증(읽은 근거만 인용, 다른 소유자 거부)이 그대로 적용된다.
- 검토 화면 출처에 `source`가 "사양 DB: N5800"으로 나온다. 답장 첨부 후보는 `task_sources`를 `file`과 JOIN해 만들므로(`get_source_files`) 파일이 없는 사양 근거는 후보에 나오지 않는다.

## 결정한 것
1. `owner_id`에 **정확한 모델명**도 받는다 (`spec_service.find_owner`). 모델이 id 대신 모델명을 넘기는 실수를 오류로 돌려보내지 않기 위해서다. 같은 모델명이 여럿이면 받지 않는다.
2. 오류는 예외가 아니라 결과로 돌려준다: 없는 대상 → `{"error": …}`(get_specs) 또는 `errors` 목록(compare_specs), 없는 속성 키 → 그 조건만 `unknown`, 실행 컨텍스트 밖 → 오류 dict.
3. `search_spec_items`·`list_spec_attributes`는 근거를 만들지 않으므로 실행 컨텍스트 검사를 하지 않는다.
4. 도구 설명에 지시서 문장 두 개를 그대로 넣고, `op` 목록과 조건 예시를 적었다.
5. 실행 한도(검색 6·도구 25·모델 20)는 바꾸지 않았다. 사양 도구는 전체 도구 한도(25)에 들어간다.

## 테스트: 명령과 출력
```
.venv/Scripts/python.exe -m pytest tests/test_spec_tools.py -q
10 passed in 6.78s

.venv/Scripts/python.exe -m pytest tests -q
419 passed in 53.17s
```
| 지시서 테스트 | 테스트 |
|---|---|
| `get_specs`·`compare_specs`가 근거를 등록하고 인용 답변이 검증 통과 | `test_get_specs_registers_evidence_and_citation_passes`, `test_compare_specs_registers_one_evidence_per_target` |
| `search_spec_items`만 부르고 답하면 오류 | `test_search_only_answer_fails_validation` ("근거를 읽지 않고 답변") |
| 같은 호출 두 번이면 같은 근거 ID | `test_same_call_twice_gives_same_evidence_id` (값을 고치면 새 ID) |
| 다른 메일의 사양 근거 인용 → 오류 | `test_other_tasks_spec_evidence_is_rejected` |
| `SPEC_TOOLS_ENABLED=false`면 도구 목록에 없음 | `test_spec_tools_switch_and_skill_author_tool_list`, `test_disabled_spec_tools_are_not_bound_to_agent` (에이전트 도구 노드까지) |
| I4 도구 목록에 자동으로 들어감 | `test_spec_tools_switch_and_skill_author_tool_list` |
| (추가) 출처 이름 "사양 DB: N5800", 파일 없음 / 오류 결과 / 값 없는 제품 / 도구 설명 문장 | 나머지 |

## 확인하지 못한 것
- 실모델이 조건을 속성 키로 바꾸는지는 9절 T4(W3·W4·M1)에서 본다.
- 프롬프트 v2 도구 표에는 새 도구가 없다. Z1에서 v3로 바뀐다 (도구 설명은 지금도 모델에 전달된다).
