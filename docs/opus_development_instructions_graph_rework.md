# Opus 개발 지시서 GR — 지식 그래프 정비

작성일: 2026-11-16 (같은 날 사용자 피드백으로 개정)
대상: 구현 담당 에이전트(Opus)
앞 문서: [opus_development_instructions.md](opus_development_instructions.md) (규칙 0절·보고 형식 7절 적용), [remaining](opus_development_instructions_remaining.md) (단계 H), [그래프 사용자 편집 계획](graph_user_editing_development_plan_2026-11-13.md)
근거: 사용자 지적·결정 2026-11-16

| 사용자 지적·결정 | 내용 |
|------------------|------|
| 1 | 별칭에서 넣은 상위 개념이 그래프까지 온다. **사용자가 다시 구현하기 전까지 시스템이 만드는 상위 개념을 완전히 없앤다** |
| 2 | 객체 종류가 7개로 고정돼 있다 |
| 3 | 제품 사양 DB가 그래프에 쓰이지 않는다. 구조화된 데이터라 그대로 그래프로 만들면 된다 |
| 4 | 의미 없는 연결이 생긴다 (`GeForce RTX 5070 -발급 기관-> NVIDIA`, 기술 이름이 부품, CPU가 제품) |
| 5 | **A650은 상위 모델(개념), A650-GA70-OU01은 실제 제품이다. 트리 구조로 구분한다** |
| 6 | **노드·객체·종류·관계·개념 등 전부를 사용자가 제한 없이 고칠 수 있어야 한다** |
| 7 | **숫자 사양도 노드로 만든다.** 예: `메모리 용량 64GB` 노드 |
| 8 | 제조사 관계를 문서에서 뽑힌 것만 쓰는 것은 사용자가 모두 고칠 수 있으면 유지해도 된다 |

---

## 0. 원인 (코드 확인 결과)

| 지적 | 원인 | 위치 |
|------|------|------|
| 1 | `aliases.yaml`의 `KC 인증 : [...]`를 서버 시작 때 `concept` 개체와 `part_of` 관계로 심는다. 추출 프롬프트·시스템 프롬프트·`graph_search`가 모두 이 개념을 쓴다 | `main.py` `seed_concepts`, `graph_rag/extractor.py` `_CONCEPT_GUIDE`, `agent/agent.py` `_graph_concepts`, `graph_rag/service.py` `expanded` |
| 2 | 개체 종류가 코드 상수(`ENTITY_TYPES`)와 LLM 출력 형식(`EntityType` Literal)에 박혀 있다 | `graph_rag/types.py`, `graph_rag/edit_service.py` `_types` |
| 3 | `seed_specs()`는 제품, 상위 모델, `product_component`(0건)만 심는다. A650의 CPU·GPU(`cpu_model`, `gpu_model`)와 메모리·SSD 같은 사양 값 1,572건이 그래프에 하나도 안 간다 | `repository/graph_repository.py` `seed_specs` |
| 4-가 | 추출한 관계의 출발·도착 개체 종류를 검사하지 않는다. 화면 편집만 검사한다 | `graph_repository.replace_page` |
| 4-나 | 회사를 가리키는 관계가 `issued_by`(발급 기관) 하나뿐이라 제조사도 거기에 들어간다 | `graph_rag/types.py` `RELATION_TYPES` |
| 4-다 | 관계에만 나온 이름을 관계 종류로 개체 종류를 정해 자동 생성한다 (`has_component`의 도착 → 무조건 부품) | `extractor._add_relation_endpoints` |
| 4-라 | "부품"의 정의가 넓어 기술·브랜드·아키텍처를 부품으로 뽑고, 제품과 부품의 구분 기준이 없다 | `ENTITY_TYPES` 설명 |
| 4-마 | 사양 DB에 같은 대상이 있어도 `™`·"프로세서" 때문에 이름이 맞지 않아 추출 종류가 그대로 남는다 | `_spec_ref_map`, `normalize` |
| 5 | 상위 모델과 판매 모델이 같은 `product` 종류다. 사양 DB는 `product.parent_id`로 트리를 갖고 있다 (A650 → A650-GA70-OU01, A650-GA70-PU02) | `graph_rag/types.py`, `seed_specs` |
| 6 | 편집에 막힌 곳이 있다: 개체 종류는 바꿀 수 없다, 기본 관계 종류의 이름·연결 규칙은 고정, 사양 DB에서 온 관계(`variant_of`, 사양 제품의 `has_component`)는 편집 거부, 속성 정의의 자료형·단위는 바꿀 수 없다, 관계를 만들 때 허용 종류가 아니면 거부 | `edit_service._update_entity`, `_definition_update`, `_validate_relation` |

참고
- 로컬 운영 DB에는 지금 등록 문서가 없다 (`file` 0건, 개체 8개). 캡처는 문서가 등록된 다른 서버의 화면이다. 그 서버의 그래프는 GR7의 재추출로 정리한다.
- 사양 DB 값: A650-GA70-OU01의 메모리 용량은 16, A650-GA70-PU02는 64다 (사용자 예시의 64GB는 PU02 값). 투영은 DB 값을 그대로 쓴다.

---

## 1. 해결 방향

| 지적 | 해결 |
|------|------|
| 1 | 시스템이 만드는 상위 개념을 코드·DB·프롬프트·화면에서 지우고 `aliases.yaml`을 지운다. 사용자가 원하면 GR2의 사용자 종류(예: "개념")와 사용자 관계로 직접 만들 수 있다 |
| 2 | 개체 종류를 DB 테이블로 옮기고, 기본 종류를 포함해 모두 고칠 수 있게 한다 |
| 3·7 | 사양 DB를 그래프로 **투영**한다. 제품군·제품·부품 전부를 노드로, 다른 대상을 가리키는 값(CPU 모델 등)은 그 대상 노드로, 나머지 값(메모리 64GB, USB-C 2개 등)은 **사양 값 노드**로 만든다 |
| 4 | 문서 추출 결과를 저장 전에 검사한다 (허용 종류, 식별자, 사양 DB 정식 종류 우선). 관계 끝 자동 생성을 없애고 `제조사` 관계를 더한다. 기존 그래프는 재추출로 정리한다 |
| 5 | `제품군` 종류를 새로 둔다. 사양 DB에서 하위 모델이 있는 제품은 제품군, 없는 제품은 제품이다. `하위 모델 → 상위 모델` 관계로 트리를 만들고 화면에 계층으로 보인다 |
| 6 | 편집 제한을 푼다. 규칙(허용 종류, 식별자 규칙 등)은 **문서 자동 추출만** 거른다. 사람의 편집은 막지 않고 규칙과 다르면 경고만 보인다. 사양 DB에서 온 노드·관계도 그래프에서 고칠 수 있고, 그 편집은 다시 투영해도 유지된다 (사양 DB 자체는 바뀌지 않는다) |
| 8 | 제조사 관계는 문서 추출과 사용자 입력으로만 생긴다. 이름의 "NVIDIA"로 추론하지 않는다 |

원칙: **자동으로 만드는 것은 보수적으로, 사람이 고치는 것은 자유롭게.** 자동 추출·투영은 규칙으로 거르고, 사람은 규칙 자체와 결과를 모두 고칠 수 있다.

---

## 2. 규칙

1. 순서: GR0 → GR1 → GR2 → GR3 → GR4 → GR5 → GR6 → GR7 → GR8. 항목마다 커밋 1개, `docs/dev_log/GR-<항목>.md` 1개, 마지막에 `GR-summary.md`. 항목마다 전체 테스트 통과 후 다음으로.
2. 작업 시작 전 작업 트리를 확인한다. 사용자가 고친 미커밋 파일이 있으면 건드리지 않고 커밋에 넣지 않는다.
3. 운영 DB에 쓰지 않는다. 점검은 `sqlite3` `mode=ro` SQL로만 한다 (저장소 모듈 임포트 금지, D-D2 사고 재발 방지). 마이그레이션 확인은 사본 DB로 한다.
4. 사양 데이터(`product`, `component`, `spec_value`, `product_component`)를 만들거나 고치지 않는다. 그래프에 투영만 한다. 그래프에서 사양 노드·관계를 고쳐도 사양 DB에 쓰지 않는다.
5. 제품 양식은 한 시트·공통 속성을 유지한다. 속성 사전에 **열**을 더하는 것은 되지만, 속성을 새로 만들거나 노트북/데스크톱을 나누지 않는다.
6. 사람이 화면에서 넣거나 고친 것(`origin='manual'`, `manual_retained=1`, 제외 목록)은 재추출·재투영으로 지우거나 되돌리지 않는다. **예외: 시스템이 만든 상위 개념 개체와 `part_of` 관계는 출처와 관계없이 GR1에서 지운다** (사용자 결정).
7. 실행 한도·맥락 예산·`recursion_limit`은 바꾸지 않는다. 그래프 관계는 답변 근거가 아니다 (지금과 같다).

---

## 3. GR0 — 점검 스크립트 (코드 변경 전에)

`scripts/audit_graph.py` (읽기 전용, `sqlite3` `mode=ro`, 저장소 임포트 금지, 경로 인자로 DB 지정). 마크다운으로 출력한다.

- 개체 종류별·출처별(`creation_origin`) 개수, 관계 종류별·출처별 개수
- 상위 개념 개체, `part_of` 관계 (출처 포함)
- 관계 종류의 허용 출발·도착 종류를 어긴 관계 목록 (출처, 문서·페이지)
- GR3의 식별자 규칙을 어기는 개체 목록 (출처 포함)
- 사양 DB 모델명과 정식 이름 맞춤 키(GR3-4)가 같은데 종류가 다른 개체
- 관계도 등장 위치도 없는 개체 수

GR1 이후에는 개체·관계 종류 테이블을 읽어 같은 점검을 한다 (스크립트가 두 스키마를 모두 읽는다). 로컬 운영 DB로 한 번 실행해 `docs/dev_log/GR-GR0.md`에 붙인다.

---

## 4. GR1 — 시스템 상위 개념 완전 제거

### 코드
| 위치 | 할 일 |
|------|-------|
| `aliases.yaml` | 파일 삭제 |
| `agent/agent.py` | `ALIAS_PATH`, `load_aliases`, `ALIASES`, `_graph_concepts` 삭제 |
| `agent/prompt.py` | `ALIAS_PATH`, `render_aliases`, `render_concepts`, `aliases`·`concepts` 인자 삭제. DB의 옛 프롬프트(v2, v3)에 남은 `**용어 별칭 (표준 이름 = 별칭)**` 줄과 `$aliases`는 렌더링할 때 지운다 |
| `main.py` | `seed_concepts` 호출 삭제 |
| `graph_rag/types.py` | `concept` 개체 종류, `part_of` 관계, `ExtractedEntity.concept` 삭제 |
| `graph_rag/extractor.py` | `_CONCEPT_GUIDE`, `_keep_known_concepts`, `concepts` 인자 삭제 |
| `graph_rag/service.py` | 개념 펼치기와 결과의 `expanded` 삭제. 문서 순위는 질문에서 찾은 개체 수로만 매긴다 |
| `repository/graph_repository.py` | `seed_concepts`, `concept_members`, `list_concepts`, `replace_page`의 `part_of` 처리, `relations_of`·`find_entities`·`_prune_orphans`의 `concept` 예외 삭제 |
| `repository/graph_migration.py` | 기본 관계 종류 목록에서 `part_of` 삭제 |
| `tools/tool.py` | `graph_search` 설명에서 상위 개념·`expanded` 문장 삭제 |
| 프론트 `knowledge/` | `concept` 색·크기 예외·패널 처리 삭제 |
| `tests/` | 개념을 기대하는 테스트는 지우거나 "개념이 없다"를 확인하는 테스트로 바꾼다. `tests/eval/deepagents_proto`도 같이 고친다 |

### 데이터 (서버 시작 마이그레이션, 몇 번 돌려도 같은 결과)
- `graph_relation`의 `part_of` 행 전부, `graph_exclusion`·`graph_relation_block`의 `part_of` 행
- `type='concept'` 개체와 그 별칭·등장 위치·속성 값
- `graph_relation_type`의 `part_of` 행
- 지운 개수를 `graph_edit_event`에 한 건(`action='migration'`, `target_kind='schema'`)으로 남기고 INFO 로그를 쓴다

### 결과로 달라지는 것
"KC 인증 자료"처럼 묶음 이름으로 묻는 질문은 더 이상 인증 종류로 펼쳐지지 않는다. 사용자가 다시 구현할 때까지의 의도된 저하다. 사용자가 그래프 화면에서 "개념" 같은 종류와 관계를 직접 만드는 것은 GR2·GR5로 된다. 그것을 검색 펼치기에 쓰는 기능은 이번에 만들지 않는다.

**테스트**: 서버 초기화 뒤 `concept` 개체·`part_of` 관계·관계 종류가 0건. 시스템 프롬프트에 "상위 개념"·"용어 별칭"이 없다 (옛 v3를 선택해도). `graph_search` 결과에 `expanded`가 없다. 마이그레이션을 두 번 돌려도 결과가 같다.

---

## 5. GR2 — 개체 종류를 DB로

### 테이블 (`graph_migration.py`)
```sql
CREATE TABLE IF NOT EXISTS graph_entity_type (
  key                 TEXT PRIMARY KEY,          -- ^[a-z][a-z0-9_]{1,29}$. 내부 식별자라 바꾸지 않는다 (이름·설명은 바꾼다)
  label               TEXT NOT NULL UNIQUE,      -- 화면 이름
  description         TEXT NOT NULL DEFAULT '',  -- 무엇이 이 종류인지. 추출 프롬프트에 그대로 들어간다
  color               TEXT NOT NULL,             -- #RRGGBB
  extract             INTEGER NOT NULL DEFAULT 0,-- 1이면 문서 추출 대상
  requires_identifier INTEGER NOT NULL DEFAULT 0,-- 1이면 문서 추출 결과의 이름에 식별자(GR3-3)가 있어야 받는다
  builtin             INTEGER NOT NULL DEFAULT 0,-- 기본 제공 표시일 뿐, 편집 제한이 아니다
  active              INTEGER NOT NULL DEFAULT 1,
  sort_order          INTEGER NOT NULL DEFAULT 0,
  revision            INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT
);
```

기본 종류 (없을 때만 넣는다. 이미 있으면 사용자가 고친 값을 덮지 않는다)

| key | label | description (추출 안내) | extract | requires_identifier |
|-----|-------|------------------------|---------|---------------------|
| product_line | 제품군 | 판매 모델들을 묶는 상위 모델(시리즈). 실제 판매 단위가 아니다. 예: A650 | 1 | 1 |
| product | 제품 | 실제 판매 단위의 완제품 모델(노트북·데스크톱·모니터·서버). 예: A650-GA70-OU01, N5800. CPU·GPU·SSD는 제품이 아니라 부품이다 | 1 | 1 |
| component | 부품 | 제품에 들어가는 부품의 모델명. 예: AMD Ryzen AI 7 350, GeForce RTX 5070, Samsung PM9C1b. 브랜드 이름(Ryzen, Radeon)·기술 이름(Tensor 코어, RT 코어)·아키텍처(Blackwell)는 부품이 아니다 | 1 | 1 |
| spec_value | 사양 값 | 사양 DB의 속성 값 하나. 예: 메모리 용량 64GB. 사양 DB에서만 만든다 | 0 | 0 |
| certification | 인증 | 인증·신고·시험의 종류. 예: 안전확인 신고, 적합성 등록 | 1 | 0 |
| cert_number | 인증번호 | 인증서·등록·신고·시험성적서 번호. 예: R-R-TGE-N5800 | 1 | 1 |
| organization | 기관·회사 | 회사, 제조사, 시험기관, 발급기관. 예: NVIDIA, 국립전파연구원 | 1 | 0 |
| standard | 규격 | 규격·표준·기준. 예: KN 32, IEC 62368-1 | 1 | 0 |

색은 지금 `meta.ts` 값을 옮기고, 새 종류는 고정 팔레트에서 고른다.

### 편집 (제한 없음)
- 모든 종류(기본 포함)의 이름·설명·색·추출 여부·식별자 규칙·활성·순서를 고칠 수 있다.
- 사용 중지한 종류: 새 추출에서 빠진다. 기존 개체는 그대로 보이고 검색된다. 사양 투영이 쓰는 종류(GR4-1 표)를 사용 중지하면 투영이 그 종류의 노드를 만들지 않고 요약에 건너뛴 수를 남긴다. 화면은 사용 중지 전에 "사양 투영이 이 종류를 씁니다"를 확인받는다.
- 종류 합치기: `POST /graph/entity-types/{key}/merge {into}` — 이 종류의 개체를 모두 다른 종류로 옮기고 종류를 지운다. 같은 이름의 개체가 옮길 종류에 있으면 개체 병합 규칙(기존 `merge_entities`)을 따른다. 기본 종류도 합칠 수 있다.
- 종류 삭제: 개체가 0개면 바로, 있으면 합치기를 쓰라고 안내한다 (개체를 잃지 않기 위해서다).
- `graph_relation_type`의 허용 출발·도착 종류에 넣을 수 있는 값은 이 테이블의 키다.
- 코드에서 `ENTITY_TYPES` 상수를 읽는 곳은 모두 테이블 조회로 바꾼다. 기본 종류 목록은 마이그레이션 기본값으로만 남긴다.

### 추출 형식을 실행 때 만든다
- `extract_page_graph`는 그때의 활성·추출 대상 종류로 Pydantic 모델을 만든다 (`type: Literal[...]`). 종류 목록이 같으면 재사용한다 (종류·관계 종류 테이블 revision 합으로 캐시).
- 관계도 같다: `graph_relation_type`에 `extract INTEGER NOT NULL DEFAULT 0` 열을 더한다.
- 추출 프롬프트의 종류·관계 안내는 테이블의 `description`과 허용 출발·도착 종류로 만든다.

### API·화면
- `GET /graph/schema`가 종류 목록 전체를 준다.
- `POST /graph/entity-types`, `PATCH /graph/entity-types/{key}`, `POST /graph/entity-types/{key}/merge`, `DELETE /graph/entity-types/{key}`. 기존 관계 종류 API와 같은 revision 충돌 검사와 편집 이력. `GRAPH_EDIT_*` 설정을 따른다.
- 지식 그래프 화면에 "개체 종류" 관리 영역: 목록, 추가, 수정, 사용 중지, 합치기. 설명 칸 옆에 "문서 추출 때 이 설명이 그대로 쓰입니다".
- 객체 추가 대화상자의 종류 목록, 범례, 노드 색이 모두 스키마 응답을 쓴다.

**테스트**: 기본 8종이 들어가고 두 번 넣지 않는다. 기본 종류의 이름·설명·색을 바꿀 수 있다. 사용자 종류(예: `concept_user` "개념")를 만들고 그 종류의 개체를 만들 수 있다. `extract=1`이면 추출 형식에 들어가고 끄면 빠진다. 종류 합치기 뒤 개체가 옮겨지고 종류가 사라진다. 개체가 있는 종류를 그냥 지우면 400과 합치기 안내.

---

## 6. GR3 — 문서 추출 결과 검사와 관계 정비

### GR3-1. 기본 관계 종류 (없을 때만 넣는다. 모두 사용자가 고칠 수 있다)

| key | 이름 | 출발 | 도착 | 추출 |
|-----|------|------|------|------|
| variant_of | 상위 모델 | product, product_line | product_line | 0 (사양 DB) |
| has_component | 부품 | product, product_line | component | 1 |
| has_spec | 사양 | product, product_line, component | spec_value | 0 (사양 DB) |
| has_certification | 인증 | product, product_line, component | certification | 1 |
| has_number | 번호 | product, product_line, component, certification | cert_number | 1 |
| issued_by | 발급 기관 | certification, cert_number | organization | 1 |
| **made_by** (신규) | 제조사 | product_line, product, component | organization | 1 |
| complies_with | 규격 준수 | product, product_line, component, certification | standard | 1 |

`issued_by`의 description에 "회사가 제품·부품을 만든 것은 발급이 아니다. 그것은 made_by"를 넣는다. 이미 있는 기본 관계는 **사용자가 고치지 않았을 때만**(revision 1) 허용 종류를 위 표로 갱신한다.

### GR3-2. 관계 끝 자동 생성 삭제
`extractor._add_relation_endpoints`와 `RELATION_ENDPOINT_TYPES`를 지운다. 개체 목록에 없는 이름을 가리키는 관계는 버린다.

### GR3-3. 저장 전 검사 `validate_page_graph(graph, schema, spec_index)` (문서 추출에만)
`replace_page` 앞에서 부른다. 순서대로 적용하고, 버린 것을 사유별로 센다.

1. **정식 종류 우선**: 개체 이름(또는 별칭)의 정식 이름 맞춤 키가 사양 투영 노드(GR4)와 같으면 그 노드의 **현재 종류**로 바꾸고 붙인다. 예: 문서의 `AMD Ryzen™ AI 7 350 프로세서`를 제품으로 뽑아도 부품 노드에 붙는다. 문서의 `A650`은 제품군 노드에 붙는다. 사용자가 그 노드의 종류를 바꿨으면 바뀐 종류를 따른다.
2. **종류 검사**: 활성·추출 대상 종류가 아니면 버린다.
3. **식별자 규칙**: 종류의 `requires_identifier=1`이면 이름이나 별칭 중 하나에 숫자가 든 영숫자 토큰(예: `N5800`, `5070`, `PM9C1b`, `R-R-TGE`)이 있어야 한다. 1번에서 붙은 개체는 건너뛴다. `Tensor 코어`, `RT 코어`, `Blackwell 아키텍처`, `Radeon`, `Ryzen`, `XDNA`는 여기서 빠진다.
4. **관계 검사**: 출발·도착이 남은 개체여야 하고, 관계 종류가 활성·추출 대상이어야 하며, 출발·도착 종류가 허용 종류여야 한다. 방향만 반대면 뒤집어 받는다. 그 밖에는 버린다. 예: `GeForce RTX 5070 -issued_by-> NVIDIA`는 버려진다 (같은 페이지에서 `made_by`로 뽑으면 그것이 남는다).
5. 자기 자신을 가리키는 관계는 버린다.

`replace_page`의 반환과 추출 로그에 `dropped: {"type": n, "identifier": n, "relation_endpoint": n, "relation_type": n}`를 싣는다.

**사람의 편집에는 이 검사를 적용하지 않는다** (GR5).

### GR3-4. 정식 이름 맞춤 키 `spec_match_key(name)`
`normalize`는 그대로 두고(기존 `norm`을 바꾸지 않기 위해) 사양 대조용 키를 따로 만든다.
- `™`·`®`·`©`를 NFKC 전에 지운다 (NFKC는 `™`를 `TM`으로 바꾼다)
- 끝 괄호 내용을 지운다: `NVIDIA GeForce RTX 5070 (105W)` → `NVIDIA GeForce RTX 5070`
- 끝의 일반 명사를 지운다: `프로세서`, `processor`, `cpu`, `gpu`, `그래픽`, `graphics`, `칩셋`
- 앞의 제조사 이름을 뺀 키도 함께 만든다: 첫 단어가 `config.GRAPH_VENDOR_PREFIXES`(기본: NVIDIA, AMD, Intel, Qualcomm, Samsung, SK hynix, Micron, Kingston, WD, Seagate, Realtek, MediaTek)에 있으면 뺀다
- 그 뒤 `normalize`

### GR3-5. 추출 프롬프트
종류·관계 안내를 테이블에서 만들고, 아래 규칙을 더한다.
- "브랜드·제품군 이름만 있는 표현, 기술·기능 이름, 아키텍처 이름은 개체로 뽑지 않는다."
- "회사가 제품·부품을 만들었으면 made_by, 인증·번호를 발급했으면 issued_by다."
- "관계의 출발과 도착은 위 표에 적힌 종류만 된다."

**테스트** (대역 모델 출력으로)
- 캡처의 두 페이지를 재현한 추출 결과를 넣으면: 기술·브랜드 이름 개체가 없다. `RTX 5070 -issued_by-> NVIDIA`가 없고, `made_by`로 뽑힌 것은 남는다. `AMD Ryzen™ AI 7 350 프로세서`가 부품 노드에 붙는다. 문서의 `A650`이 제품군 노드에 붙는다.
- 개체 목록에 없는 이름을 가리키는 관계가 개체를 새로 만들지 않는다.
- 방향만 반대인 관계는 뒤집혀 저장된다.
- 사용자가 관계 종류의 허용 종류를 바꾸면 다음 추출부터 바뀐 규칙으로 거른다.
- A5 규칙: `N5800`과 `N5800-GB70-PU02`가 다른 개체다.

---

## 7. GR4 — 사양 DB를 그래프로 투영

### GR4-1. 무엇을 노드·관계로 만드는가

| 사양 DB | 그래프 | 노드 종류 |
|---------|--------|-----------|
| 하위 모델이 있는 `product` | 노드 (`ref_type='product'`) | 제품군 (`product_line`) |
| 하위 모델이 없는 `product` | 노드 (`ref_type='product'`) | 제품 (`product`) |
| `product.parent_id` | `하위 → variant_of → 상위` | — |
| `component` 전부 | 노드 (`ref_type='component'`) | 부품 |
| `product_component` | `has_component` (`is_option`) | — |
| 속성의 그래프 방식이 `entity`인 값 | 값이 가리키는 대상 노드와 관계 (GR4-3) | 지정한 종류 |
| 속성의 그래프 방식이 `value_node`인 값 | 사양 값 노드와 `has_spec` 관계 (GR4-4) | 사양 값 |
| 속성의 그래프 방식이 `none`인 값 | 노드를 만들지 않는다. 패널에서 본다 | — |

투영 관계의 출처는 모두 `spec`. 사양 값은 **그 대상이 직접 가진 값만** 투영한다 (상속된 값은 상위 모델 노드에 이미 있다).

로컬 사양 DB 기준 예상 규모: 제품군 1(A650), 제품 3, 부품 123, 사양 값 노드 약 360개(같은 속성·같은 값은 한 노드), `has_spec` 관계 약 1,570개.

### GR4-2. 트리 (제품군 → 제품)
- 종류는 투영할 때마다 트리로 다시 정한다: 하위 모델이 생기면 제품 → 제품군, 하위 모델이 모두 없어지면 제품군 → 제품.
- **사용자가 그 노드의 종류를 직접 바꿨으면** 투영이 종류를 바꾸지 않는다. `graph_entity.type_locked INTEGER NOT NULL DEFAULT 0` 열을 더하고, 화면에서 종류를 바꾸면 1이 된다.
- 단계가 여러 개면(제품군 → 하위 제품군 → 제품) 그대로 여러 단계 트리다.
- 화면:
  - 개체 패널에 "모델 계층": 상위 경로와 하위 모델 목록 (클릭하면 이동).
  - 그래프 캔버스에 "계층 보기" 배치: `variant_of`를 위→아래 트리로 놓고, 다른 관계는 지금처럼 둔다. 제품군 노드를 고르면 기본으로 계층 보기다.
- `graph_search`: 제품군을 물으면 `relations`에 하위 모델들이 나온다. 하위 모델을 물으면 지금처럼 상위 모델 문서를 후보(`via`)로 더한다. 상위 모델의 인증을 하위 모델에 적용된 것으로 표시하지 않는다 (지금과 같다).

### GR4-3. 대상을 가리키는 값 (`entity` 방식)
- 도착 노드 이름 = 값에서 끝 괄호를 뺀 것 (`NVIDIA GeForce RTX 5070 (105W)` → `NVIDIA GeForce RTX 5070`). 값 원문과 제조사 이름을 뺀 이름(`GeForce RTX 5070`)을 별칭으로 넣는다.
- 도착 노드 찾기: 정식 이름 맞춤 키로 사양 DB 부품 → 같은 종류의 기존 노드 → 새 노드. 사양 DB 부품과 맞으면 `ref`를 단다.
- 관계: 대상 → 도착 노드, `is_option`은 값의 옵션 여부, `source_key='spec:value:<spec_value_id>'`.

### GR4-4. 사양 값 노드 (`value_node` 방식)
- 노드 이름: `<속성 화면 이름> <값 표기>`. 예: `메모리 용량 64GB`, `USB-C 단자 수 2`, `카드리더 지원`, `운영체제 Windows 11 Pro`.
- 값 표기
  - 숫자: `value_num`을 정규 표기(불필요한 소수점 제거)로 쓰고 속성 단위를 붙인다. 값 문자열에 다른 단위가 적혀 있으면 사양 서비스의 단위 환산(`to_attribute_unit`)으로 속성 단위로 바꾼다. 환산할 수 없으면 값 문자열 그대로.
  - 예/아니오: `지원` / `미지원`
  - 텍스트: 값 문자열 그대로
- 같은 속성의 같은 값은 **한 노드**다 (노드 키 = 속성 키 + 정규화한 값 표기). 그래서 `메모리 용량 64GB` 노드에서 그 값을 가진 제품들을 모두 볼 수 있다.
- 노드에 `ref_type='spec_attribute'`, `ref_id=<속성 키>`를 단다. 개체 패널은 속성 이름·단위·숫자 값을 보이고, 이 값을 가진 대상 목록을 보인다.
- 관계: 대상 → 사양 값 노드, `has_spec`, `is_option`, `source_key='spec:value:<spec_value_id>'`.
- 값이 바뀌면 이전 값 노드와의 관계가 사라지고 새 값 노드와 이어진다. 관계가 하나도 없게 된 사양 값 노드는 정리된다 (사용자가 고친 노드는 남는다).

### GR4-5. 속성마다 그래프 방식 지정
`spec_attribute`에 열 세 개 (`_migrate`). 속성을 새로 만드는 것이 아니다.
- `graph_mode TEXT NOT NULL DEFAULT 'value_node'` — `value_node` | `entity` | `none`
- `graph_relation_type TEXT` — `entity` 방식일 때 관계 종류 (예: `has_component`)
- `graph_entity_type TEXT` — `entity` 방식일 때 도착 노드 종류 (예: `component`)

기본값 (마이그레이션이 한 번만 넣는다. R&D가 바꾸면 덮지 않는다)

| 속성 | 기본 방식 |
|------|-----------|
| `cpu_model`, `gpu_model`, `chipset`, `wifi` | `entity` → `has_component` → `component` |
| 숫자·예/아니오 속성 | `value_node` |
| 텍스트 속성 중 값이 모두 40자 이하 | `value_node` |
| 텍스트 속성 중 40자를 넘는 값이 있는 것 (예: `io_ports`, `audio`, `software`) | `none` |

`/spec` 속성 탭에 "그래프" 칸: 사양 값 노드 / 대상 노드(관계·종류 선택) / 만들지 않음. 저장하면 투영이 다시 돈다. 엑셀 양식은 바꾸지 않는다.

### GR4-6. 동기화
- `seed_specs()`를 `project_specs()`로 바꾼다. 매번 `origin='spec'` 관계만 지우고 다시 넣는다. 문서 추출·사람이 넣은 관계는 건드리지 않고, 사람이 지운 관계(`graph_exclusion`·`graph_relation_block`)는 되살리지 않는다.
- 노드는 `ref`로 찾는다 (종류·이름이 아니라). 사용자가 이름·종류를 바꾼 사양 노드도 같은 노드로 이어진다. 사용자가 지운 사양 노드(`lifecycle_state='deleted'`)는 되살리지 않고 그 노드로 가는 관계도 만들지 않는다.
- 부르는 때: 서버 시작, 사양 저장 API 전부(제품·부품·값·연결·속성의 그래프 방식·엑셀 가져오기 적용).
- 투영 요약(`product_lines, products, components, value_nodes, variant_of, has_component, has_spec, entity_relations, skipped, blocked`)을 로그에 남긴다.
- 1,500개 넘는 관계를 매번 지우고 넣으므로 한 트랜잭션으로 하고, 걸린 시간을 로그에 남긴다. 2초를 넘으면 dev_log에 적는다.

### GR4-7. 개체 패널의 사양 값
- `GET /graph/entities/{id}`: `ref_type`이 `product`·`component`면 `spec` 항목에 `spec_service.effective_specs` 결과(속성, 값, 단위, 옵션, 상속 출처, 부품 경유). 그때의 사양 DB 값이다.
- 화면: 개체 패널에 "사양 DB" 영역, 분류별로 접기, "사양 화면에서 열기" 링크.

### GR4-8. 그래프 화면
- 관계 출처 표시(문서·사양 DB·사용자)를 범례에 둔다.
- 필터 기본값: "사양 값 노드"는 **고른 노드의 이웃으로만** 보인다 (전체 보기에서 360개가 화면을 덮지 않게). "관계 없는 사양 노드 숨기기" 켬. 둘 다 끌 수 있다.

### GR4-9. 검색 (`graph_search`)
- 질문에서 찾은 개체가 사양 값 노드가 아니면 `has_spec` 관계는 `relations`에 넣지 않는다 (문서·부품·인증 관계를 밀어내지 않게). 대신 `spec_values: n`(개수)만 싣는다.
- 질문이 사양 값 노드와 맞으면(예: "메모리 64GB 제품") 그 값을 가진 대상을 `relations`에 싣는다.
- 그래프 관계는 근거가 아니다. 답에 쓰려면 `get_specs`·`compare_specs`로 읽는다.

**테스트** (fixture DB)
- 하위 모델이 있는 제품은 제품군, 없는 제품은 제품. 하위 모델을 지우면 다음 투영에서 제품이 된다. 사용자가 종류를 바꾼 노드는 투영이 바꾸지 않는다.
- `A650-GA70-PU02 -variant_of-> A650`, 여러 단계 트리.
- `cpu_model = AMD Ryzen AI 7 350`이 사양 DB 부품 노드와 이어진다 (새 노드를 만들지 않는다). `gpu_model = NVIDIA GeForce RTX 5070 (105W)` 노드에 문서 추출의 `GeForce RTX 5070`이 붙는다.
- `ram_gb = 64`가 `메모리 용량 64GB` 노드가 되고, 같은 값을 가진 두 제품이 한 노드를 공유한다. `1TB`로 적힌 GB 속성 값이 `1000GB` 노드가 된다.
- 값을 바꾸면 관계가 새 값 노드로 옮겨지고 고아 값 노드가 정리된다.
- 사용자가 지운 사양 관계·노드, 바꾼 이름·종류가 재투영 뒤에도 유지된다.
- 속성의 그래프 방식을 `none`으로 바꾸면 그 값 노드·관계가 사라진다.
- 사양 데이터 행 수가 투영 전후 같다. 사양 쓰기 API 모두가 투영을 다시 부른다.
- `graph_search("A650")`에 하위 모델 관계가 있고 `has_spec` 관계는 없다(개수만). `graph_search("메모리 64GB")`에 그 값을 가진 제품이 있다.
- `GRAPH_SPEC_SEED_ENABLED=false`면 투영하지 않는다.

---

## 8. GR5 — 편집 제한 해제

사람은 모든 것을 고칠 수 있다. 규칙은 경고로만 보인다. 모든 편집은 지금처럼 revision 충돌 검사와 편집 이력(`graph_edit_event`)을 남긴다.

| 대상 | 지금 | 바꾼 뒤 |
|------|------|---------|
| 개체 종류 바꾸기 | 불가 | `PATCH /graph/entities/{id} {type}`. 사양 노드면 `type_locked=1`. 같은 종류에 같은 이름이 있으면 병합 안내 |
| 사양 노드 이름 | `display_name`으로 가능 | 그대로 |
| 사양 노드 삭제·복구 | 가능 | 그대로. 투영이 되살리지 않는다 |
| 기본 관계 종류 | 이름·의미·연결 규칙 고정 | 이름·설명·허용 출발·도착 종류·추출 여부·활성 모두 수정 |
| 사용자 관계 종류의 연결 규칙 | "새 정의로 이관" | 바로 수정 |
| 관계 만들기·바꾸기의 허용 종류 검사 | 어기면 400 | 만들어지고, 응답에 `warnings: ["허용 종류가 아닙니다: …"]`. 화면에 노란 표시 |
| 사양 DB에서 온 관계 (`variant_of`, `has_component`, `has_spec`) | 편집 거부 | 지우기(제외 목록), 종류 바꾸기·방향 바꾸기(제외 + 수동 관계로 바꿔 넣기) 가능. 사양 DB는 바뀌지 않는다 |
| 사양 노드에 수동 관계 추가 | 일부 거부 | 가능 |
| 속성 정의의 자료형·단위 | 바꿀 수 없음 | 바꿀 수 있다. 기존 값이 새 자료형으로 읽히지 않으면 그 값 목록을 응답으로 돌려주고 저장하지 않는다 (값을 먼저 고치게) |
| 개체 종류 | 고정 7종 | GR2 |

사양 DB와 그래프가 달라졌을 때
- 개체 패널에 "사양 DB와 다름" 표시를 둔다: 사람이 지운 사양 관계, 종류를 바꾼 사양 노드, 이름을 바꾼 사양 노드. "사양 DB 기준으로 되돌리기" 버튼이 사람의 편집을 지우고 다시 투영한다.
- 그래프 편집이 사양 DB를 고치지는 않는다. 사양 값을 바꾸려면 사양 화면에서 바꾼다 (패널의 링크).

규칙 위반 목록
- `GET /graph/rule-warnings`: 허용 종류를 어기는 관계, 식별자 규칙을 어기는 개체 (출처별). 지식 그래프 화면에 개수와 목록. 사람이 의도한 것이면 그대로 둔다.

**테스트**: 기본 관계 종류의 이름·허용 종류를 바꿀 수 있다. 허용되지 않는 관계를 만들면 201과 경고. 개체 종류를 바꾸면 사양 노드의 `type_locked`가 1이 되고 재투영이 종류를 되돌리지 않는다. 사양 관계를 지우거나 종류를 바꾸면 재투영 뒤에도 유지되고, "되돌리기"로 사양 DB 상태가 된다. 속성 정의 자료형을 바꿀 때 읽을 수 없는 값이 있으면 저장하지 않고 목록을 준다.

---

## 9. GR6 — 프롬프트 v4와 절차 문서

### 프롬프트 v4
`agent/prompt.py`에 `PROMPT_V4_NAME = "v4 근거 ID·사양·그래프 정비"`로 넣고 `ensure_seeded`로 한 번 등록·선택한다. v2·v3 행은 그대로 둔다. `SYSTEM_PROMPT_TEMPLATE`도 v4로. 본문은 **지금 v3 본문에서 아래만 바꾼다.**

1. `**용어 별칭 (표준 이름 = 별칭)**` 줄과 `$aliases` 줄을 지운다.
2. 도구 표의 `graph_search` 행을 다음으로 바꾼다:
   `| graph_search | 질문의 모델명·부품·인증·규격·사양 값으로 관련 개체, 관계, 문서(file_id)와 페이지를 찾는다. 관계에는 출처(문서·사양 DB·사용자 입력)가 붙는다. 제품군과 하위 모델이 구분된다. matched의 ref_type·ref_id는 get_specs에 넘길 수 있다 |`
3. "지켜야 할 것"의 `- 상위 개념이 펼쳐졌으면 속한 종류마다 문서를 찾고, 찾지 못한 종류는 "문서 없음"으로 밝힌다.`를 다음 두 줄로 바꾼다:
   `- 인증 묶음 이름(예: KC 인증)은 시스템이 속한 종류로 펼쳐 주지 않는다. 그 모델의 인증 관계와 인증서 문서에서 확인한 종류만 쓰고, 묶음에 무엇이 들어가는지 근거가 없으면 "확인 필요"로 밝힌다.`
   `- 제품군(예: A650)은 판매 모델이 아니다. 제품군을 물으면 하위 모델별로 나눠 답하고, 제품군의 값을 하위 모델의 값으로 단정하지 않는다.`

`docs/prompt_v4.md`에 바뀐 곳과 전문을 남긴다.

### 절차 문서 `skills/certification-bundle/SKILL.md` (version 3)
이 부분만 바꾸고 나머지는 그대로 둔다.
- 절차 1을 다음으로: `1. **요청한 인증과 모델을 찾는다.** graph_search에 모델명과 인증 이름을 넣는다. 결과 relations의 인증 관계(has_certification, has_number)와 documents를 본다. 인증 묶음 이름(예: KC 인증)은 시스템이 속한 종류로 펼쳐 주지 않는다.`
- 절차 5 뒤에: `6. **묶음 이름으로만 물었으면** 그 모델의 인증 관계와 인증서 문서에서 확인한 종류를 모두 적고, 묶음에 더 들어가야 할 종류가 있는지는 "확인 필요"로 밝힌다.`
- `metadata.version`을 `"3"`으로.

다른 절차 문서는 바꾸지 않는다. 절차 본문의 도구 이름 검사 테스트가 통과해야 한다.

**테스트**: v4가 한 번만 등록·선택된다. 렌더링된 시스템 프롬프트에 "상위 개념"·"용어 별칭"이 없고 제품군 문장이 있다. `certification-bundle` 본문에 "펼쳐진다"가 없다.

---

## 10. GR7 — 기존 그래프 정리

코드가 바뀌어도 이미 저장된 잘못된 개체·관계는 남는다. 문서 추출로 생긴 것(`origin='extract'`)은 재추출로 갈아끼운다.

1. 사용자가 서버 DB를 백업한다.
2. 서버 재시작 → GR1 마이그레이션(개념 삭제), GR2 테이블, GR4 투영이 적용된다.
3. 지식 그래프 화면의 전체 다시 만들기(`POST /graph/rebuild`)를 사용자가 실행한다.
4. GR0 점검 스크립트를 다시 돌려 전후를 비교한다.

구현자가 할 일: 위 절차를 `docs/dev_log/GR-GR7.md`에 사용자용으로 적고, 로컬에서 문서 2~3개를 사본 DB에 올려 재추출 전후 점검 결과를 붙인다. 운영 DB에서 재추출하지 않는다. 사람이 넣은 개체·관계 중 규칙을 어기는 것은 지우지 않고 규칙 위반 목록으로 사용자에게 넘긴다.

---

## 11. GR8 — 확인

### 자동
- `.venv/Scripts/python.exe -m pytest tests -q` 전체 통과
- `npx tsc -b`, `npx eslint src/knowledge src/spec`, `npm run build`
- 사본 DB 마이그레이션 예행: 두 번 실행해 결과가 같고, `concept`·`part_of` 0건, 사양 데이터 행 수 그대로, 수동 관계 수 그대로, 투영 요약 기록

### 실서버·실모델 (사용자가 재시작·재추출한 뒤, 읽기 전용)
캡처가 나온 서버에서 같은 화면을 다시 본다.

| 확인 | 기대 |
|------|------|
| A650 | 제품군 노드. 계층 보기에서 아래로 A650-GA70-OU01, A650-GA70-PU02 |
| A650-GA70-PU02 | 제품 노드. 이웃에 `메모리 용량 64GB`, `부품 → AMD Ryzen AI 7 350`, `부품 → NVIDIA GeForce RTX 5070` (사양 DB) |
| `메모리 용량 64GB` | 그 값을 가진 제품이 모두 이어져 있다 |
| GeForce RTX 5070 | `발급 기관 → NVIDIA` 없음. Tensor 코어·RT 코어·Blackwell 계열 부품 없음 |
| AMD Ryzen AI 7 350 | 종류가 부품. Radeon·Ryzen·XDNA 없음. 패널에 사양 값 |
| 상위 개념 | 시스템이 만든 것은 화면·목록·범례 어디에도 없음 |
| 편집 | 기본 종류 이름 바꾸기, 새 종류 만들기, 사양 관계 지우기 → 재시작 뒤에도 유지 |
| `/ask` "A650 GPU 알려줘" | 하위 모델별로 답하고 `get_specs` 근거를 쓴다 |
| `/ask` "N5800 KC 인증 자료" | 묶음을 펼치지 않고, 확인한 종류와 "확인 필요"를 밝힌다 |

결과는 `docs/dev_log/GR-live-check.md`. 기대와 다르면 코드를 고치지 말고 결과만 적는다.

### Gemini 검증
| 번호 | 조건 |
|------|------|
| GR-1 | 시스템이 만드는 상위 개념이 코드·DB·프롬프트·절차·화면에 없다. `aliases.yaml`이 없다 |
| GR-2 | 개체 종류가 DB에서 오고 추출·편집·화면이 같은 목록을 쓴다. 기본 종류도 고칠 수 있다 |
| GR-3 | 문서 추출 관계가 허용 종류 검사를 받는다. 관계 끝 자동 생성이 없다 |
| GR-4 | 식별자 규칙과 정식 종류 우선이 문서 추출 저장 전에 적용된다 |
| GR-5 | 제품군·제품 트리, 부품, 대상 값, 사양 값 노드가 투영되고 사양 데이터는 바뀌지 않는다 |
| GR-6 | 같은 속성·같은 값은 한 사양 값 노드다. 사양 값 관계가 그래프 검색 관계를 밀어내지 않는다 |
| GR-7 | 사람의 편집(종류·이름·삭제·관계)이 재투영·재추출 뒤에도 유지되고, 규칙은 경고로만 보인다 |
| GR-8 | 그래프 관계는 근거가 아니고, 답은 `get_specs`·`read_pages` 근거로만 쓴다 |
| GR-9 | 전체 테스트·타입·린트·빌드 통과, 실행 한도·맥락 예산 그대로 |

---

## 12. 하지 않는 것

- 시스템이 상위 개념·인증 묶음을 만들거나 검색에서 펼치는 기능 (사용자가 다시 구현한다)
- 사양 데이터 수정, `product_component` 자동 생성, 그래프 편집을 사양 DB에 되쓰기
- 제조사 관계를 이름에서 추론해 만드는 것 (문서 추출과 사용자 입력으로만)
- 운영 DB에서 재추출, 사람이 넣은 개체·관계 삭제
- 추출 대상 종류를 LLM이 스스로 늘리는 것

---

## 13. 사용자 확인 사항

1. 재시작 전에 그래프가 있는 서버의 DB를 백업한다. 재시작으로 시스템 상위 개념이 지워지고 테이블·열이 더해지며 사양 값 노드 수백 개가 생긴다.
2. 재시작 뒤 지식 그래프 화면에서 전체 다시 만들기를 실행해야 기존의 잘못된 연결이 사라진다.
3. "KC 인증 자료" 같은 묶음 질문은 다시 구현할 때까지 펼쳐지지 않는다.
4. 속성마다 그래프 방식(사양 값 노드 / 대상 노드 / 만들지 않음)은 `/spec` 속성 탭에서 바꾼다. 긴 서술 값(단자 구성, 소프트웨어 등)은 기본으로 노드를 만들지 않는다.
5. 캡처가 나온 서버의 DB 사본을 주면 GR0 점검을 그 데이터로도 돌린다.
