# GR-GR4 사양 DB를 그래프로 투영

## 변경 파일
- `repository/graph_projection.py` (신규): `project_specs(conn)` — 제품군/제품 트리(`variant_of`), 부품 전부, `product_component`→`has_component`, 속성 그래프 방식별 값 투영(`entity`→대상 노드, `value_node`→사양 값 노드+`has_spec`, `none`), 사람이 지운 관계·노드 존중, `type_locked` 존중, 고아 사양 값 노드 정리, 요약+걸린 시간
- `repository/graph_repository.py`: `seed_specs` → `project_specs`(한 트랜잭션, 로그, 2초 넘으면 경고). `_link_spec_entity` 삭제. `hierarchy()`, `count_relations()`, `relations_of(exclude_types=)`, `get_entity`에 `hierarchy`·`spec_attribute`, `view(spec_values=, hide_isolated_spec=)`, `find_entities`의 사양 값 노드 거르기(`_keep_matching_value_nodes`)
- `repository/graph_migration.py`: `graph_entity.type_locked`, `graph_entity.ref_value` 열. `effective_graph_entity` 뷰를 다시 만들어 두 열을 넣음
- `repository/repo_connect.py`: `spec_attribute.graph_mode`·`graph_relation_type`·`graph_entity_type` 열과 기본값(열이 생길 때 한 번)
- `repository/spec_repository.py`: `update_attribute`가 그래프 방식 저장·검증. 새 속성·기본 속성 추가 때 기본 방식(`_default_graph_mode`)
- `entity/spec.py`: `GRAPH_MODES`, `GRAPH_ENTITY_ATTRIBUTES`, `GRAPH_TEXT_NODE_MAX`, `GRAPH_NONE_ATTRIBUTES`
- `graph_rag/rules.py`: `strip_trailing_parens`
- `graph_rag/service.py`: `graph_search`가 `has_spec`을 relations에서 빼고 `spec_values` 개수를 싣는다. 질문이 사양 값 노드면 그 값을 가진 대상을 relations에
- `app/routers/specs.py`: 재투영(`reseed_spec_graph` → `project_specs`)을 사양 쓰기 API 전부에(제품·부품·연결·값·속성·기본 속성·표 가져오기). `/specs/meta`에 `graph_modes`. 속성 수정에 그래프 방식 필드
- `app/routers/graph.py`: `GET /graph/entities/{id}`의 `spec`(effective_specs), `GET /graph/view`의 `spec_values`·`hide_isolated_spec`
- `main.py`: 서버 시작 때 `project_specs`
- 프론트: `knowledge/SpecPanels.tsx`(신규: 모델 계층·사양 DB·사양 값), `layout.ts`(`layoutHierarchy`), `KnowledgeSection.tsx`(계층 보기 단추, 사양 값 필터 두 개, 범례에서 seed 숨김), `EntityPanel.tsx`(사양 값 관계 접기), `api.ts`, `types.ts`, `meta.ts`(manual → "사용자 입력"), `spec/GraphModeCell.tsx`(신규), `spec/AttributesTab.tsx`, `spec/api.ts`
- 테스트: `tests/test_graph_projection.py`(신규), `tests/test_graph_spec.py`, `tests/test_graph_user_editing.py`

## 결정한 것
- **사양 값 노드의 식별**: 지시서는 `ref_type='spec_attribute'`, `ref_id=<속성 키>`를 단다고 했지만 속성 키 하나에 값 노드가 여럿이라 노드를 하나로 가리킬 수 없다. `graph_entity.ref_value`(정규화한 값 표기) 열을 더해 (ref_type, ref_id, ref_value)로 찾는다. 사람이 이름을 바꿔도 같은 노드로 이어진다.
- 값 노드 이름은 속성 이름이 바뀌면 따라 바꾼다(사람이 이름을 고치지 않았고 `manual_retained=0`일 때만).
- 숫자 표기는 `read_number`(단위 환산 포함)로 속성 단위의 숫자를 얻고 단위를 띄우지 않고 붙인다. 그래서 `usb_c_ports`(단위 '개')는 `USB-C 단자 수 2개`가 된다(지시서 예시는 단위 없는 `2`). 환산할 수 없으면 값 문자열 그대로.
- 예/아니오는 `value_num`(1/0)으로 지원/미지원. 없으면 글자로 판단.
- 대상 값(`entity`)의 도착 노드가 사양 DB 부품이 아니면 ref 없는 새 노드를 만든다(creation_origin='spec'). 관계가 없어지면 다음 투영에서 정리된다.
- 부품 노드는 이름이 겹치면(종류만 다른 같은 모델명) `모델명 (종류)`로 만든다. 제품 노드의 모델명이 바뀌면 지금처럼 새 모델명을 별칭으로 더한다.
- 사양 노드를 데려올 때(ref가 아직 없는 같은 이름 개체): 제품은 product·product_line 종류, 부품은 component·product 종류에서 찾는다(예전에 CPU를 제품으로 뽑은 개체를 부품으로 바로잡는다). 종류를 바꿀 때 같은 종류·이름의 ref 없는 개체가 있으면 노드로 합친다(이력 남김, 병합 흔적의 norm은 `:merged:id`로 비켜 둔다).
- 사용 중지된 종류: 그 종류의 노드를 새로 만들지 않고(`skipped`), 그 종류로 바꾸지도 않는다. 이미 있는 노드의 관계는 계속 투영한다.
- 새 DB에서 "기본 속성 추가"로 넣는 서술형 속성(`io_ports, audio, software, accessory, keyboard, m2_slots, webcam`)은 `none`으로 둔다. 기존 DB는 마이그레이션이 값 길이(40자)로 정한다. 둘 다 R&D가 바꾸면 덮지 않는다.
- `graph_search`의 사양 값 노드 매칭은 "값 표기와 속성 이름의 한 어절이 질문에 있을 때"만 남긴다. "메모리 64GB"에 `메모리 용량 16GB`, `SSD 용량 64GB`가 함께 걸리는 것을 막기 위해서다.
- 그래프 화면: 사양 값 노드는 전체 보기에 넣지 않고(종류 필터로 고르면 넣음), 중심 개체의 바로 이웃으로만 보이며 거기서 더 펼치지 않는다. 개체 패널의 관계 목록에서 `has_spec`은 접어 둔다(수백 개).
- 계층 보기는 중심 개체가 제품군이면 자동으로 켜지고, 단추로 끄고 켠다. 트리 노드를 끌면 그 자리에 고정된다.

## 운영 DB 사본 예행 (가드 설치 후, `storage/mail.db` 수정 시각 변화 없음)
```
마이그레이션 2회 → 투영 2회
투영 요약: {'product_lines': 1, 'products': 3, 'components': 123, 'value_nodes': 341, 'variant_of': 2, 'has_component': 0,
          'has_spec': 1539, 'entity_relations': 12, 'skipped': 0, 'blocked': 0, 'seconds': 0.073}   (두 번째 0.063초)
사양 데이터 행 수 전후 같음: product 4, component 123, spec_value 1572, product_component 0
수동 관계 1 → 1, concept 0, part_of 0
활성 개체 종류: component 127(부품 123 + 대상 값 노드 4), product 3, product_line 1, spec_value 341
```
- 사양 값 1,572건 중 `has_spec` 1,539 + `entity` 12, 나머지 21건은 `none` 속성(서술형 7개 속성 × 3제품).
- 투영 뒤 고아 정리로 aliases.yaml이 심었던 인증 종류 2개(`안전확인신고`, `자율안전확인`, 문서·관계 없음)가 지워졌다. 기존 `seed_specs`의 정리 규칙과 같다.
- 2초 기준을 넘지 않았다.

## 테스트: 명령과 출력
```
$ .venv/Scripts/python.exe -m pytest tests/test_graph_projection.py -q
...............                                                          [100%]
15 passed in 3.93s
$ .venv/Scripts/python.exe -m pytest tests -q
........................................................................ [ 91%]
................................................                         [100%]
552 passed in 87.86s (0:01:27)
$ npx tsc -b; npx eslint src/knowledge src/spec   (frontend/)
(출력 없음 = 통과)
```

## 확인하지 못한 것 / Gemini에게 요청할 검증
- 화면(계층 보기, 사양 DB 영역, 그래프 칸)은 GR8에서 임시 백엔드로 확인한다.
- 캡처 서버의 사양 DB로 투영한 결과(값 노드 수, 시간)는 사용자 재시작 뒤 확인.

## 커밋 해시
GR-summary.md에 모은다.
