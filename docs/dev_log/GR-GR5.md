# GR-GR5 편집 제한 해제

## 변경 파일
- `graph_rag/edit_service.py`
  - `_update_entity`: `type` 바꾸기. 바꾸면 `type_locked=1`. 같은 종류·같은 이름이 있으면 409와 합치기 안내. 식별자 규칙과 다르면 `warnings`
  - `_reset_spec_entity` (신규): 사양 노드에 대한 사람의 편집(지운 관계 `graph_exclusion`·`graph_relation_block`, 바꾼 종류·표시 이름, 사양 관계를 바꿔 넣은 수동 관계)을 지운다
  - `_definition_update`: 기본 관계 종류 포함 이름·설명·허용 출발·도착 종류·추출 여부·활성·자기 연결 모두 수정. 속성 정의는 자료형·단위·선택지·적용 종류·복수 여부까지(`_definition_shape`, `_convert_values`, `_convert`)
  - `_validate_relation`: 오류 대신 경고 목록(허용 종류 아님, 사용 중지된 관계 종류, 자기 연결). 사양 DB 관계 편집 거부 삭제. 만들기·바꾸기·복구 응답에 `warnings`
  - `_create_entity`: 사양 참조 종류가 개체 종류와 같아야 하던 검사를 product/component 여부만으로 (제품군도 product 참조)
  - `rule_warnings()`, `spec_diff()` (신규), `GraphValueConversionError`
- `repository/graph_repository.py`: `get_entity`에 `spec_diff`
- `app/routers/graph.py`: `PATCH /graph/entities/{id}`가 `warnings`를 싣는다, `POST /graph/entities/{id}/reset-spec`(되돌린 뒤 다시 투영), `GET /graph/rule-warnings`, 값 변환 실패는 400 `{"code":"value_conversion","values":[...]}`
- 프론트: `EntityEditExtras.tsx`(신규: 종류 바꾸기, 사양 DB와 다름·되돌리기, 규칙 위반 목록), `DefinitionEditors.tsx`(신규: 관계 종류·속성 정의 수정), `EntityPanel.tsx`(관계 행 노란 경고, 관계 추가 경고 표시), `GraphEditing.tsx`(규칙 위반 목록 단추, 정의 목록 교체), `schemaContext.ts`(`ruleWarning`), `types.ts`
- 테스트: `tests/test_graph_unrestricted_edit.py`(신규), `tests/test_graph_edit.py`, `tests/test_graph_user_editing.py`(거부를 기대하던 3곳 → 만들어지고 경고)

## 결정한 것
- 사람의 편집에서 오류로 남긴 것: 없는 관계 종류·개체(404), 삭제·병합된 개체, revision 충돌, 같은 종류·같은 이름으로 종류 바꾸기(유일 키, 409), 값 형식 오류. 나머지 규칙(허용 종류, 사용 중지된 관계 종류, 자기 연결, 식별자)은 모두 경고.
- `type_locked`는 사양 노드가 아니어도 종류를 바꾸면 1로 둔다 (나중에 사양 노드로 데려와도 사람이 정한 종류를 지키게).
- "사양 DB 기준으로 되돌리기"는 지운 관계·종류·표시 이름에 더해, 사양 관계의 종류·방향을 바꿀 때 만든 수동 관계(같은 편집의 correlation_id로 찾는다)를 삭제 상태로 돌린다. 그 밖의 수동 관계는 건드리지 않는다. 사양 DB는 바꾸지 않는다.
- 속성 정의를 단일 값으로 바꿀 때 값이 여러 개인 객체가 있으면 409. enum 선택지를 바꿀 때도 기존 값이 선택지에 없으면 값 목록과 함께 저장하지 않는다.
- 규칙 위반 목록은 지우지 않고 보여 주기만 한다. 화면에서 항목을 누르면 그 개체로 간다.

## 테스트: 명령과 출력
```
$ .venv/Scripts/python.exe -m pytest tests/test_graph_unrestricted_edit.py -q
.......                                                                  [100%]
7 passed in 1.95s
$ .venv/Scripts/python.exe -m pytest tests -q
........................................................................ [ 90%]
.......................................................                  [100%]
559 passed in 85.60s (0:01:25)
$ npx tsc -b; npx eslint src/knowledge src/spec   (frontend/)
(출력 없음 = 통과)
```

## 확인하지 못한 것 / Gemini에게 요청할 검증
- 화면 동작은 GR8에서 임시 백엔드로 확인한다.
- `reset-spec`이 찾는 "바꿔 넣은 수동 관계"는 편집 이력의 correlation_id에 기댄다. 이력이 없는 옛 편집은 되돌리지 못한다.

## 커밋 해시
GR-summary.md에 모은다.
