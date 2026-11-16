# GR-GR2 개체 종류를 DB로

## 변경 파일
- `graph_rag/defaults.py` (신규): 기본 개체 종류 8개(GR2 표), 고정 팔레트, 사양 투영 종류, 기본 관계 종류(지금 값). DB·저장소 임포트 없음
- `graph_rag/schema.py` (신규): `load_schema`/`default_schema`, `page_graph_model(schema)` — 활성·추출 대상 종류로 `type: Literal[...]` 구조화 출력 형식을 실행 때 만든다. key·revision·active·extract 목록으로 캐시
- `graph_rag/types.py`: `ENTITY_TYPES`·`EntityType`·`RelationType` Literal 삭제. `ExtractedEntity.type`/`ExtractedRelation.type`은 `str`. `RELATION_TYPES`·`NON_EXTRACT_RELATIONS`는 기본값에서 만든다
- `graph_rag/extractor.py`: `build_extract_prompt(schema)` — 종류 안내는 테이블 `description`, 관계 안내는 `description`과 허용 출발·도착 종류. `extract_page_graph(..., schema=)`. 뽑을 종류가 없으면 LLM을 부르지 않는다
- `graph_rag/service.py`: 파일·페이지 추출 때 `graph_repo.extraction_schema()`를 넘긴다
- `graph_rag/edit_service.py`: 종류 목록을 테이블에서 읽는다(`_type_keys`). 명령 `create_entity_type`, `update_entity_type`, `merge_entity_type`, `delete_entity_type`. `schema()`가 종류 전체(+`used_by_projection`, `entity_count`)를 준다. 관계 종류 생성·수정에 `extract`
- `repository/graph_migration.py`: `graph_entity_type` 테이블과 기본 8종(테이블이 비었을 때만), `graph_relation_type.extract` 열(열이 생길 때 기존 추출 관계를 1로)
- `repository/graph_repository.py`: `extraction_schema()`, `entity_type_keys()`
- `app/routers/graph.py`: `GET/POST /graph/entity-types`, `PATCH /graph/entity-types/{key}`, `POST /graph/entity-types/{key}/merge`, `DELETE /graph/entity-types/{key}`. 종류 필터 검사를 테이블로
- 프론트: `EntityTypes.tsx`(신규, 개체 종류 관리: 목록·추가·수정·사용 중지·합치기·삭제), `schemaContext.ts`(`EntityTypeDefinition`, `entityMeta`, `typeKeys`), `meta.ts`(고정 `ENTITY_META` 삭제), `types.ts`(`EntityType = string`), `EntityPicker.tsx`, `EntityPanel.tsx`, `GraphCanvas.tsx`, `GraphEditing.tsx`, `KnowledgeSection.tsx` — 범례·노드 색·객체 추가 종류 목록이 모두 스키마 응답을 쓴다
- 테스트: `tests/test_graph_entity_types.py`(신규), `tests/test_graph.py`, `tests/test_graph_no_concepts.py`

## 결정한 것
- 기본 종류는 **테이블이 비어 있을 때만** 넣는다. 한 번 넣은 뒤에는 사용자가 지운 기본 종류를 재시작이 되살리지 않는다 ("사용자가 고친 값을 덮지 않는다"를 삭제에도 적용).
- 기본 관계 종류의 허용 종류는 이번 항목에서 바꾸지 않았다(GR3-1에서 갱신). 그래서 GR2 시점에는 `product_line`이 추출 형식에는 있지만 어느 관계의 출발·도착에도 없다.
- 종류 합치기: 옮길 종류에 같은 이름(이름·별칭 정규화)의 개체가 있으면 기존 `merge_entity` 규칙으로 합친다(종류가 달라도 되게 `allow_type_change`). 한쪽이 삭제 상태면 409로 멈춘다(복구 후 다시). 관계 종류의 허용 종류·속성 정의의 적용 종류·`graph_relation_block`의 종류도 함께 바꾼다. 병합된 흔적 행(`lifecycle_state='merged'`)은 옛 종류 key를 그대로 둔다(유일 키 충돌을 피하고 이력 보존).
- 종류 삭제는 병합 흔적을 뺀 개체가 0개일 때만. 이 종류만 허용하는 관계 종류·속성 정의가 있으면 400(허용 목록이 비면 편집 검사가 깨진다).
- 사용 중지 확인("사양 투영이 이 종류를 씁니다")은 화면에서 받는다. 서버는 `used_by_projection`만 알려 준다.
- 사용 중지된 종류도 개체가 있으면 화면 필터·범례에 보인다(기존 개체는 그대로 보이고 검색된다).
- 새 종류 색을 안 주면 팔레트에서 아직 안 쓴 첫 색. `product_line`은 `#0E7490`, `spec_value`는 `#94A3B8`.

## 테스트: 명령과 출력
```
$ .venv/Scripts/python.exe -m pytest tests/test_graph_entity_types.py -q
...........                                                              [100%]
11 passed in 3.05s
$ .venv/Scripts/python.exe -m pytest tests -q
........................................................................ [ 95%]
.......................                                                  [100%]
527 passed in 73.44s (0:01:13)
$ npx tsc -b; npx eslint src/knowledge src/spec   (frontend/)
(출력 없음 = 통과)
```

## 확인하지 못한 것 / Gemini에게 요청할 검증
- 화면 동작(개체 종류 관리 대화상자)은 GR8에서 임시 백엔드로 한 번에 확인한다.
- 실모델(vLLM)이 동적 Literal 형식을 지금과 같이 따르는지는 확인하지 못했다.

## 커밋 해시
GR-summary.md에 모은다.
