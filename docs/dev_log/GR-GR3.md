# GR-GR3 문서 추출 결과 검사와 관계 정비

## 변경 파일
- `graph_rag/defaults.py`: 기본 관계 종류를 GR3-1 표로 (variant_of, has_component, has_spec, has_certification, has_number, issued_by, **made_by**, complies_with). issued_by 설명에 "회사가 제품·부품을 만든 것은 발급이 아니다. 그것은 made_by"
- `repository/graph_migration.py`: 없는 기본 관계는 넣고, 있는 기본 관계는 **revision 1일 때만** 설명·허용 출발·도착 종류·추출 여부를 표로 맞춘다(revision은 올리지 않는다)
- `graph_rag/types.py`: `RELATION_ENDPOINT_TYPES` 삭제
- `graph_rag/extractor.py`: `_add_relation_endpoints` 삭제(GR3-2). 프롬프트 규칙 3줄(GR3-5)과 "entities에 없는 이름을 가리키는 관계는 버려집니다" 추가
- `graph_rag/validate.py` (신규): `validate_page_graph(graph, schema, spec_index)` — 정식 종류 우선 → 종류 → 식별자 → 관계(끝·종류·허용 종류, 방향 반대면 뒤집기) → 자기 연결. 사유별 `dropped`
- `repository/graph_repository.py`: `replace_page`가 저장 전에 검사하고 반환에 `dropped`. 사양 노드 색인(`_spec_node_index`: ref가 있는 활성 노드의 현재 종류·이름·별칭). `_spec_ref_map`을 정식 이름 맞춤 키로, 제품군도 product 참조
- `graph_rag/service.py`: 파일 추출 요약·로그에 `dropped` 합계
- `config.py`: `GRAPH_VENDOR_PREFIXES` (기본값 = `rules.DEFAULT_VENDOR_PREFIXES`)
- `graph_rag/schema.py`: 허용 종류 목록을 정렬해 기본값과 DB 값의 프롬프트가 같게
- 테스트: `tests/test_graph_extract_rules.py`(신규), `tests/test_graph.py`, `tests/test_graph_user_editing.py`(식별자 없는 이름 'Alpha'/'Chip' → 'Alpha100'/'Chip200')

## 결정한 것
- 검사는 `replace_page` 안(같은 트랜잭션)에서 부른다. `replace_page`를 부르는 곳은 문서 추출뿐이라 "문서 추출에만"과 같다. 사람의 편집(`GraphEditService`)은 이 경로를 타지 않는다.
- 정식 종류 우선의 대상 노드 = `ref_id`가 있는 **활성** 개체(사양 DB 노드). GR4 투영 전에도 기존 `seed_specs`가 만든 제품·부품 노드에 붙는다. 같은 맞춤 키를 두 노드가 가지면 그 키로는 붙이지 않는다(모호).
- 붙일 때 개체 이름을 노드의 현재 이름으로 바꾸고 문서 표기를 별칭으로 남긴다. 저장은 이름으로 다시 찾지 않고 그 노드 id에 바로 붙인다.
- `dropped` 사유 배정: 끝 개체가 없거나 버려졌거나 자기 연결이면 `relation_endpoint`, 관계 종류가 활성·추출 대상이 아니거나 출발·도착 종류가 허용되지 않으면 `relation_type`.
- 지시서 테스트 "사용자가 관계 종류의 허용 종류를 바꾸면 다음 추출부터 바뀐 규칙"은 편집 API가 GR5에서 열리므로 이번에는 테이블 값을 직접 바꿔 확인했다. GR5에서 API로 다시 확인한다.
- 기존 테스트 중 식별자 없는 제품·부품 이름('Alpha', 'Chip')을 쓰던 두 편집 테스트는 이름만 바꿨다 (검사가 문서 추출 경로에 들어갔기 때문).

## 테스트: 명령과 출력
```
$ .venv/Scripts/python.exe -m pytest tests/test_graph_extract_rules.py -q
..........                                                               [100%]
10 passed in 1.59s
$ .venv/Scripts/python.exe -m pytest tests -q
........................................................................ [ 93%]
.................................                                        [100%]
537 passed in 77.14s (0:01:17)
```

## 확인하지 못한 것 / Gemini에게 요청할 검증
- 실제 캡처 서버의 문서로 재추출한 결과는 사용자 재추출 후(GR7·GR8) 확인한다. 위 캡처 재현은 대역 모델 출력이다.
- 식별자 3자 하한이 2자 모델명(예: "X1")을 놓치는지.

## 커밋 해시
GR-summary.md에 모은다.
