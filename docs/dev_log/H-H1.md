# H-H1 그래프 저장 구조 (사양 DB 대상·spec 출처·variant_of)

## 변경 파일
- `storage/schema.sql`
  - `graph_entity`: `ref_type TEXT`(`product`·`component`), `ref_id TEXT`
  - `graph_relation.origin` CHECK에 `spec`, 새 컬럼 `is_option INTEGER NOT NULL DEFAULT 0 CHECK (is_option IN (0, 1))`
- `repository/repo_connect.py`
  - `_migrate_graph_relation_origin`: CHECK에 `spec`이 없으면 `graph_relation_new`를 만들어 기존 행을 **id·created_at까지** 복사하고, 옛 테이블을 지우고 이름을 바꾼 뒤 인덱스 3개(유일 인덱스 포함)를 다시 만든다. `_migrate_task_reviews_action`과 같은 방식
  - `graph_entity`에 `ref_type`·`ref_id`가 없으면 `ALTER TABLE … ADD COLUMN`, 인덱스 `idx_graph_entity_ref(ref_type, ref_id)`
- `graph_rag/types.py`: `RELATION_TYPES["variant_of"]`(파생 모델 → 상위 모델), `NON_EXTRACT_RELATIONS = {part_of, variant_of}`. LLM 추출 형식(`RelationType`)에는 넣지 않았다
- `graph_rag/extractor.py`: 추출 프롬프트의 관계 목록에서 `NON_EXTRACT_RELATIONS`를 뺀다 (지금까지는 `part_of`만 뺐다)
- `repository/graph_repository.py`
  - `_prune_orphans`: `ref_id`가 있는 개체는 지우지 않는다
  - `merge_entities`: 관계를 옮길 때 `is_option`도 옮기고, 합쳐지는 개체의 사양 대상 표시를 target에 없을 때만 옮긴다
- 프론트 `frontend/src/knowledge/types.ts`·`meta.ts`: 관계 `variant_of`("상위 모델", "파생 모델 → 상위 모델 (사양 DB)"), 출처 `spec`("사양 DB", 보라색 점선)
- `tests/test_graph_spec.py`(신규) 4건

## 결정한 것
1. **`graph_relation.is_option`을 더했다.** 지시서 H2는 "옵션 여부는 관계에 남긴다"이고 H1 저장 구조에는 컬럼 이름이 없다. CHECK 때문에 어차피 테이블을 새로 만드므로 같은 마이그레이션에서 컬럼을 더했다. 다른 출처의 관계는 0이다. (충돌이 아니라 지시서가 정하지 않은 구현 방법이라 멈추지 않았다.)
2. **옮기는 동안 외래키 검사를 끈다.** 외래키를 켠 채 `INSERT … SELECT`를 하면, 예전에 외래키 없이 남은 행(지워진 파일을 가리키는 관계) 하나 때문에 마이그레이션이 실패하고 서버가 뜨지 않는다. 목적은 "기존 행을 그대로 옮기기"이므로 검사를 끄고 옮긴 뒤 다시 켠다. 열린 트랜잭션이 있으면 외래키 설정이 바뀌지 않아 먼저 `commit`한다. 실패하면 되돌린다.
3. 프론트 출처 표(`ORIGIN_META`)는 모든 출처를 키로 가진 `Record`라 `spec`을 넣지 않으면 그래프 화면이 `spec` 관계에서 깨진다. 지시서의 "관계 이름 표"와 함께 출처 표도 고쳤다.

## 테스트: 명령과 출력
```
.venv/Scripts/python.exe -m pytest tests/test_graph_spec.py -q
4 passed in 0.80s

.venv/Scripts/python.exe -m pytest tests -q
423 passed in 54.53s

cd frontend && npx tsc -b && npx eslint src/knowledge
(출력 없음)
```
- `test_check_migration_keeps_rows_ids_and_indexes`: 예전 CHECK 테이블의 관계 3개(id 7·12·40, 출처 extract·seed·manual)가 id·created_at까지 그대로, 두 번 열어도 같음. 새 CHECK가 `spec`을 받고 모르는 출처는 거부, 유일 인덱스 유지, `is_option` 0, `ref_type`·`ref_id` 한 번씩
- `test_migration_copies_rows_even_with_dangling_file`: 지워진 파일을 가리키는 행이 있어도 옮긴다
- `test_variant_of_is_known_but_not_extracted`: 관계 종류에는 있고 추출 프롬프트·추출 형식에는 없다
- `test_prune_keeps_entities_with_spec_ref`

## 확인하지 못한 것
- 운영 DB 마이그레이션은 9절 T2(사본 예행)에서 확인한다.
