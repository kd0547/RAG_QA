# Opus 개발 지시서 GR — 지식 그래프 정비

작성일: 2026-11-16
대상: 구현 담당 에이전트(Opus)
앞 문서: [opus_development_instructions.md](opus_development_instructions.md) (규칙 0절·보고 형식 7절 적용), [remaining](opus_development_instructions_remaining.md) (단계 H), [그래프 사용자 편집 계획](graph_user_editing_development_plan_2026-11-13.md)
근거: 사용자 지적 2026-11-16 (지식 그래프 화면 캡처 3장)

| 사용자 지적 | 화면에서 본 것 |
|-------------|----------------|
| 1. 별칭에서 넣은 상위 개념이 그래프까지 온다. **사용자가 다시 구현하기 전까지 완전히 없앤다** | `KC 인증` 개체와 `part_of` 관계, 객체 추가 목록의 "상위 개념" |
| 2. 객체 종류가 7개로 고정돼 있다 | 객체 추가 목록 |
| 3. 제품 사양 DB가 그래프에 쓰이지 않는다. 구조화된 데이터라 그대로 그래프로 만들면 된다 | A650의 CPU·GPU가 사양 DB에 있는데 그래프에는 문서 추출 결과만 있다 |
| 4. 의미 없는 연결이 생긴다 | `GeForce RTX 5070 -발급 기관-> NVIDIA`, `GeForce RTX 5070 -부품-> Tensor 코어·RT 코어·Blackwell 아키텍처`, `AMD Ryzen AI 7 350`이 제품으로 잡히고 `Radeon`·`Ryzen`·`XDNA`가 그 부품 |

---

## 0. 원인 (코드 확인 결과)

| 지적 | 원인 | 위치 |
|------|------|------|
| 1 | `aliases.yaml`의 `KC 인증 : [...]`를 서버 시작 때 `concept` 개체와 `part_of` 관계로 심는다. 추출 프롬프트·시스템 프롬프트·`graph_search`가 모두 이 개념을 쓴다 | `main.py` `seed_concepts`, `graph_rag/extractor.py` `_CONCEPT_GUIDE`, `agent/agent.py` `_graph_concepts`, `graph_rag/service.py` `expanded` |
| 2 | 개체 종류가 코드 상수(`ENTITY_TYPES`)와 LLM 출력 형식(`EntityType` Literal)에 박혀 있다. 관계 종류는 DB(`graph_relation_type`)로 옮겼지만 개체 종류는 안 옮겼다 | `graph_rag/types.py`, `graph_rag/edit_service.py` `_types` |
| 3 | `seed_specs()`는 제품, 상위 모델, `product_component`만 심는다. `product_component`는 0건이고, A650의 CPU·GPU는 `spec_value`(`cpu_model = AMD Ryzen AI 7 350`, `gpu_model = NVIDIA GeForce RTX 5070 (105W)`)에 있다. 사양 값 1,572건이 그래프에 하나도 안 간다 | `repository/graph_repository.py` `seed_specs` |
| 4-가 | 추출한 관계의 출발·도착 개체 종류를 검사하지 않는다. `graph_relation_type`에 허용 종류가 적혀 있지만 화면 편집만 검사하고 추출 저장(`replace_page`)은 검사하지 않는다. 그래서 `부품 -발급 기관-> 회사`, `부품 -부품-> 부품`이 들어간다 | `graph_repository.replace_page` |
| 4-나 | 회사를 가리키는 관계가 `issued_by`(발급 기관) 하나뿐이다. 제조사를 표현할 관계가 없어 LLM이 `issued_by`에 넣는다 | `graph_rag/types.py` `RELATION_TYPES` |
| 4-다 | 관계에만 나오고 개체 목록에 없는 이름을 관계 종류로 개체 종류를 정해 자동으로 만든다. `has_component`의 도착이면 무조건 부품이 된다 (`Tensor 코어` → 부품) | `extractor._add_relation_endpoints` |
| 4-라 | "부품"의 정의가 넓어서 기술 이름·브랜드·아키텍처를 부품으로 뽑는다. 제품과 부품의 구분 기준도 없다 (CPU를 제품으로 뽑음) | `ENTITY_TYPES` 설명, 추출 프롬프트 |
| 4-마 | 사양 DB에 있는 대상과 이름이 같아도 추출 결과의 종류를 그대로 쓴다. `AMD Ryzen™ AI 7 350 프로세서`는 `™`·"프로세서" 때문에 사양 DB의 `AMD Ryzen AI 7 350`과 맞지 않는다 | `_spec_ref_map`, `normalize` |

참고: 로컬 운영 DB에는 지금 등록 문서가 없다 (`file` 0건, 개체 8개). 캡처는 문서가 등록된 다른 서버의 화면이다. 그 서버의 그래프는 GR6의 재추출로 정리한다.

---

## 1. 해결 방향

| 지적 | 해결 |
|------|------|
| 1 | 상위 개념을 코드·DB·프롬프트·화면에서 모두 지운다. `aliases.yaml`도 지운다 (git 이력에 남는다) |
| 2 | 개체 종류를 DB 테이블(`graph_entity_type`)로 옮겨 화면에서 추가·수정·사용 중지한다. 추출은 DB에서 "추출 대상"으로 표시된 종류만 쓴다 |
| 3 | 사양 DB를 그래프로 **투영**한다. 제품·부품은 전부 개체로, 다른 대상을 가리키는 사양 값(CPU 모델, GPU 모델 등)은 관계로 만든다. 숫자 값(메모리 16GB 등)은 개체로 만들지 않고 개체 패널에 사양 DB에서 바로 읽어 보인다 |
| 4 | 추출 결과를 저장 전에 서버가 검사한다: 관계 출발·도착 종류, 식별자 규칙, 사양 DB 정식 종류 우선. 관계 끝 자동 채우기를 없애고 `제조사` 관계를 더한다. 기존 그래프는 재추출로 정리한다 |

숫자 값을 개체로 만들지 않는 이유: `16GB` 같은 값 개체는 관계없는 제품들을 한 점으로 묶어 그래프 검색 결과를 오염시킨다. 값 비교는 `compare_specs`가 이미 한다. 그래프에는 "무엇이 무엇에 들어가는가·누가 만드는가" 같은 대상 사이의 관계만 둔다.

---

## 2. 규칙

1. 순서: GR0 → GR1 → GR2 → GR3 → GR4 → GR5 → GR6 → GR7. 항목마다 커밋 1개, `docs/dev_log/GR-<항목>.md` 1개, 마지막에 `GR-summary.md`. 항목마다 전체 테스트 통과 후 다음으로.
2. 작업 시작 전 작업 트리를 확인한다. 사용자가 고친 미커밋 파일이 있으면 건드리지 않고 커밋에 넣지 않는다.
3. 운영 DB에 쓰지 않는다. 점검은 `sqlite3` `mode=ro` SQL로만 한다 (저장소 모듈 임포트 금지, D-D2 사고 재발 방지). 마이그레이션 확인은 사본 DB로 한다.
4. 사양 데이터(`product`, `component`, `spec_value`, `product_component`)를 만들거나 고치지 않는다. 그래프에 투영만 한다.
5. 제품 양식은 한 시트·공통 속성을 유지한다. 속성 사전에 **열**을 더하는 것은 되지만, 속성을 새로 만들거나 노트북/데스크톱을 나누지 않는다.
6. 사람이 화면에서 넣은 개체·관계·속성(`origin='manual'`, `manual_retained=1`)은 이번 정비로 지우지 않는다. 검사 규칙을 어기는 수동 관계는 GR0 점검 결과에 목록으로만 남긴다. **예외: 상위 개념 개체와 `part_of` 관계는 출처와 관계없이 GR1에서 지운다** (사용자 결정).
7. 실행 한도·맥락 예산·`recursion_limit`은 바꾸지 않는다.

---

## 3. GR0 — 점검 스크립트 (코드 변경 전에)

`scripts/audit_graph.py` (읽기 전용, `sqlite3` `mode=ro`, 저장소 임포트 금지, 경로 인자로 DB 지정). 마크다운으로 출력한다.

- 개체 종류별·출처별(`creation_origin`) 개수, 관계 종류별·출처별 개수
- 상위 개념 개체, `part_of` 관계 (출처 포함)
- 관계 종류의 허용 출발·도착 종류(`graph_relation_type`)를 어긴 관계 목록 (출처, 문서·페이지)
- GR3의 식별자 규칙을 어기는 제품·부품·인증번호 개체 목록 (출처 포함)
- 사양 DB의 부품·제품 모델명과 정식 이름 맞춤 키(GR3-4)가 같은데 종류가 다른 개체
- 관계도 등장 위치도 없는 개체 수

로컬 운영 DB로 한 번 실행해 `docs/dev_log/GR-GR0.md`에 붙인다. 캡처가 나온 서버의 DB는 사용자가 사본을 주면 같은 스크립트로 실행한다 (GR6에서 전후 비교에 쓴다).

---

## 4. GR1 — 상위 개념 완전 제거

### 코드
| 위치 | 할 일 |
|------|-------|
| `aliases.yaml` | 파일 삭제 |
| `agent/agent.py` | `ALIAS_PATH`, `load_aliases`, `ALIASES`, `_graph_concepts` 삭제. `render_prompt` 호출에서 별칭·개념 인자 제거 |
| `agent/prompt.py` | `ALIAS_PATH`, `render_aliases`, `render_concepts`, `aliases`·`concepts` 인자 삭제. DB에 저장된 옛 프롬프트(v2, v3)에 남은 `**용어 별칭 (표준 이름 = 별칭)**` 줄과 `$aliases`는 렌더링할 때 지운다 (옛 프롬프트를 골라도 빈 절이 남지 않게) |
| `main.py` | `seed_concepts` 호출 삭제 |
| `graph_rag/types.py` | `concept` 개체 종류, `part_of` 관계, `ExtractedEntity.concept` 삭제 |
| `graph_rag/extractor.py` | `_CONCEPT_GUIDE`, `_keep_known_concepts`, `concepts` 인자 삭제 |
| `graph_rag/service.py` | `list_concepts` 전달, `concept_members` 펼치기, 결과의 `expanded` 삭제. 문서 순위는 질문에서 찾은 개체 수로만 매긴다 |
| `repository/graph_repository.py` | `seed_concepts`, `concept_members`, `list_concepts`, `replace_page`의 `part_of` 처리, `relations_of`·`find_entities`·`_prune_orphans`의 `concept` 예외 삭제 |
| `repository/graph_migration.py` | 기본 관계 종류 목록에서 `part_of` 삭제 |
| `tools/tool.py` | `graph_search` 설명에서 상위 개념·`expanded` 문장 삭제 |
| 프론트 `knowledge/` | `meta.ts`의 `concept`, 크기 예외(`GraphCanvas`), 패널·타입의 개념 처리 삭제 |
| `tests/` | 개념을 기대하는 테스트는 지우거나 "개념이 없다"를 확인하는 테스트로 바꾼다. `tests/eval/deepagents_proto`도 같이 고친다 |

### 데이터 (서버 시작 마이그레이션, 한 번만, 몇 번 돌려도 같은 결과)
- `graph_relation`의 `part_of` 행 전부(출처 무관), `graph_exclusion`·`graph_relation_block`의 `part_of` 행
- `type='concept'` 개체와 그 별칭·등장 위치·속성 값
- `graph_relation_type`의 `part_of` 행
- 지운 개수를 `graph_edit_event`에 이벤트 한 건(`action='migration'`, `target_kind='schema'`)으로 남기고 INFO 로그를 쓴다

### 결과로 달라지는 것 (사용자에게 알린다)
"KC 인증 자료"처럼 묶음 이름으로 묻는 질문은 더 이상 인증 종류로 펼쳐지지 않는다. 모델은 질문에 적힌 이름과 그 모델의 인증 관계로만 찾는다. 사용자가 묶음 기능을 다시 구현할 때까지의 의도된 저하다.

**테스트**: 서버 초기화 뒤 `concept` 개체·`part_of` 관계·관계 종류가 0건. 시스템 프롬프트에 "상위 개념"·"용어 별칭"이 없다 (옛 v3 프롬프트를 선택해도). `graph_search` 결과에 `expanded`가 없다. 추출 프롬프트에 상위 개념 절이 없다. 마이그레이션을 두 번 돌려도 결과가 같다.

---

## 5. GR2 — 개체 종류를 DB로

### 테이블 (`graph_migration.py`)
```sql
CREATE TABLE IF NOT EXISTS graph_entity_type (
  key                 TEXT PRIMARY KEY,          -- ^[a-z][a-z0-9_]{1,29}$, 바꿀 수 없다
  label               TEXT NOT NULL UNIQUE,      -- 화면 이름
  description         TEXT NOT NULL DEFAULT '',  -- 무엇이 이 종류인지. 추출 프롬프트에 그대로 들어간다
  color               TEXT NOT NULL,             -- #RRGGBB
  extract             INTEGER NOT NULL DEFAULT 0,-- 1이면 문서 추출 대상
  requires_identifier INTEGER NOT NULL DEFAULT 0,-- 1이면 이름에 식별자(GR3-3)가 있어야 추출 결과로 받는다
  builtin             INTEGER NOT NULL DEFAULT 0,
  active              INTEGER NOT NULL DEFAULT 1,
  sort_order          INTEGER NOT NULL DEFAULT 0,
  revision            INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT
);
```

기본 종류 (없을 때만 넣는다. 이미 있으면 사용자가 고친 값을 덮지 않는다)

| key | label | description (추출 안내) | extract | requires_identifier |
|-----|-------|------------------------|---------|---------------------|
| product | 제품 | 판매 단위의 완제품 모델 (노트북·데스크톱·모니터·서버). 예: N5800, A650-GA70-PU02. CPU·GPU·SSD는 제품이 아니라 부품이다 | 1 | 1 |
| component | 부품 | 제품에 들어가는 부품의 모델명. 예: AMD Ryzen AI 7 350, GeForce RTX 5070, Samsung PM9C1b. 브랜드 이름(Ryzen, Radeon)·기술 이름(Tensor 코어, RT 코어)·아키텍처(Blackwell)는 부품이 아니다 | 1 | 1 |
| certification | 인증 | 인증·신고·시험의 종류. 예: 안전확인 신고, 적합성 등록, 에너지소비효율 등급 | 1 | 0 |
| cert_number | 인증번호 | 인증서·등록·신고·시험성적서 번호. 예: R-R-TGE-N5800 | 1 | 1 |
| organization | 기관·회사 | 회사, 제조사, 시험기관, 발급기관. 예: NVIDIA, 국립전파연구원, KTL | 1 | 0 |
| standard | 규격 | 규격·표준·기준. 예: KN 32, IEC 62368-1 | 1 | 0 |

색은 지금 `meta.ts` 값을 옮긴다.

### 규칙
- `product`·`component`는 사양 DB 투영이 쓰므로 사용 중지할 수 없다. 다른 기본 종류는 사용 중지할 수 있다.
- 사용 중지한 종류: 새 추출·새 개체 만들기에서 빠진다. 이미 있는 개체는 그대로 보이고 검색된다. 종류 삭제는 그 종류의 개체가 0개일 때만 된다 (사용자 종류만).
- 사용자가 만든 종류는 기본 `extract=0`이다. 추출 대상으로 켜면 다음 추출부터 쓰인다. 기존 문서를 자동으로 다시 뽑지 않는다.
- `graph_relation_type.source_entity_types`·`target_entity_types`에 넣을 수 있는 값은 이 테이블의 키다 (`edit_service._types`가 상수 대신 테이블을 본다).
- 코드에서 `ENTITY_TYPES` 상수를 읽는 곳(`app/routers/graph.py`, `edit_service.py` 등)은 모두 테이블 조회로 바꾼다. 기본 종류 목록은 마이그레이션의 기본값으로만 남긴다.

### 추출 형식을 실행 때 만든다
- `extract_page_graph`는 그때의 활성·추출 대상 종류로 Pydantic 모델을 만든다 (`type: Literal[...]`). 종류 목록이 같으면 만든 모델을 재사용한다 (종류 테이블 revision 합으로 캐시).
- 관계도 같다: `graph_relation_type`에 `extract INTEGER NOT NULL DEFAULT 0` 열을 더하고, 기본 관계 중 `variant_of`를 뺀 것은 1. 사용자 관계 종류는 기본 0, 켜면 추출에 쓰인다.
- 추출 프롬프트의 종류·관계 안내는 테이블의 `description`과 허용 출발·도착 종류로 만든다.

### API·화면
- `GET /graph/schema`가 종류 목록(키, 이름, 설명, 색, 추출 여부, 식별자 규칙, 활성)을 준다.
- `POST /graph/entity-types`, `PATCH /graph/entity-types/{key}`: 이름·설명·색·추출 여부·식별자 규칙·활성·순서. 기존 관계 종류 API와 같은 revision 충돌 검사와 편집 이력(`graph_edit_event`). `GRAPH_EDIT_*` 설정을 따른다.
- 지식 그래프 화면에 "개체 종류" 관리 영역: 목록, 추가, 수정, 사용 중지. 설명 칸 옆에 "문서 추출 때 이 설명이 그대로 쓰입니다" 안내.
- 객체 추가 대화상자의 종류 목록, 범례, 노드 색이 모두 스키마 응답을 쓴다. 색이 없는 종류는 고정 팔레트에서 고른다.

**테스트**: 기본 6종이 들어가고 두 번 넣지 않는다. 사용자 종류를 만들면 화면 편집으로 그 종류의 개체를 만들 수 있다. `extract=1`로 켜면 추출 형식(Literal)에 들어가고, 끄면 빠진다. 사용 중지한 종류는 추출·생성에서 빠지지만 기존 개체는 조회된다. `product`·`component` 사용 중지는 400. 개체가 있는 종류 삭제는 400. 관계 종류의 허용 종류에 없는 키를 넣으면 400.

---

## 6. GR3 — 추출 결과 검사와 관계 정비

### GR3-1. 관계 종류 정비 (기본 관계, 없을 때만 넣고 허용 종류는 기본 관계에 한해 갱신)

| key | 이름 | 출발 | 도착 | 추출 |
|-----|------|------|------|------|
| has_component | 부품 | product | component | 1 |
| has_certification | 인증 | product, component | certification | 1 |
| has_number | 번호 | product, component, certification | cert_number | 1 |
| issued_by | 발급 기관 | certification, cert_number | organization | 1 |
| **made_by** (신규) | 제조사 | product, component | organization | 1 |
| complies_with | 규격 준수 | product, component, certification | standard | 1 |
| variant_of | 상위 모델 | product | product | 0 (사양 DB만) |

`issued_by`의 description에 "회사가 제품·부품을 만든 것은 발급이 아니다. 그것은 made_by"를 넣는다.

### GR3-2. 관계 끝 자동 채우기 삭제
`extractor._add_relation_endpoints`와 `RELATION_ENDPOINT_TYPES`를 지운다. 개체 목록에 없는 이름을 가리키는 관계는 버린다.

### GR3-3. 저장 전 검사 `validate_page_graph(graph, schema, spec_index)`
`replace_page` 앞에서 부른다. 순서대로 적용하고, 버린 것을 사유별로 센다.

1. **정식 종류 우선**: 개체 이름(또는 별칭)의 정식 이름 맞춤 키가 사양 DB 제품·부품, 또는 사양 투영으로 만든 개체(GR4)와 같으면 그 종류로 바꾸고 `ref`를 단다. 예: 문서의 `AMD Ryzen™ AI 7 350 프로세서`를 제품으로 뽑아도 부품 `AMD Ryzen AI 7 350`에 붙는다.
2. **종류 검사**: 활성·추출 대상 종류가 아니면 버린다.
3. **식별자 규칙**: 종류의 `requires_identifier=1`이면 이름이나 별칭 중 하나에 숫자가 들어간 영숫자 토큰(예: `N5800`, `5070`, `PM9C1b`, `R-R-TGE`)이 있어야 한다. 1번에서 정식 이름에 붙은 개체는 이 검사를 건너뛴다. `Tensor 코어`, `RT 코어`, `Blackwell 아키텍처`, `Radeon`, `Ryzen`, `XDNA`는 여기서 빠진다.
4. **관계 검사**: 출발·도착이 남은 개체여야 하고, 관계 종류가 활성·추출 대상이어야 하며, 출발·도착 종류가 `graph_relation_type`의 허용 종류여야 한다. 방향만 반대면(도착→출발로 허용되면) 뒤집어 받는다. 그 밖에는 버린다. 예: `GeForce RTX 5070 -issued_by-> NVIDIA`는 부품이 `issued_by`의 출발이 될 수 없어 버려진다 (같은 페이지에서 LLM이 `made_by`로 뽑으면 그것이 남는다).
5. 자기 자신을 가리키는 관계는 버린다.

`replace_page`의 반환과 추출 로그에 `dropped: {"type": n, "identifier": n, "relation_endpoint": n, "relation_type": n}`를 싣는다.

화면 편집(`edit_service._validate_relation`)과 사양 투영(GR4)도 같은 허용 종류 표를 쓴다 (규칙을 한 곳에 둔다).

### GR3-4. 정식 이름 맞춤 키 `spec_match_key(name)`
`normalize`는 그대로 두고(기존 개체의 `norm`을 바꾸지 않기 위해) 사양 대조용 키를 따로 만든다.
- `™`·`®`·`©`를 NFKC 전에 지운다 (NFKC는 `™`를 `TM`으로 바꾼다)
- 끝의 괄호 내용을 지운다: `NVIDIA GeForce RTX 5070 (105W)` → `NVIDIA GeForce RTX 5070`
- 끝의 일반 명사를 지운다: `프로세서`, `processor`, `cpu`, `gpu`, `그래픽`, `graphics`, `칩셋`
- 앞의 제조사 이름을 뺀 키도 함께 만든다: 첫 단어가 `config.GRAPH_VENDOR_PREFIXES`(기본: NVIDIA, AMD, Intel, Qualcomm, Samsung, SK hynix, Micron, Kingston, WD, Seagate, Realtek, MediaTek)에 있으면 뺀다. `GeForce RTX 5070`과 `NVIDIA GeForce RTX 5070`이 같은 키를 갖는다
- 그 뒤 `normalize`

### GR3-5. 추출 프롬프트
종류·관계 안내를 테이블에서 만들고, 아래 규칙을 더한다.
- "브랜드·제품군 이름, 기술·기능 이름, 아키텍처 이름은 개체로 뽑지 않는다."
- "회사가 제품·부품을 만들었으면 made_by, 인증·번호를 발급했으면 issued_by다."
- "관계의 출발과 도착은 위 표에 적힌 종류만 된다."

**테스트** (대역 모델 출력으로)
- 캡처의 두 페이지를 재현한 추출 결과(RTX 5070 페이지, Ryzen AI 7 350 페이지)를 넣으면: `Tensor 코어`·`RT 코어`·`Blackwell 아키텍처`·`Radeon`·`Ryzen`·`XDNA`가 없다. `RTX 5070 -issued_by-> NVIDIA`가 없고, 같은 출력에 `made_by`가 있으면 그것은 남는다. `AMD Ryzen™ AI 7 350 프로세서`가 사양 DB 부품에 붙고 종류가 부품이다.
- 개체 목록에 없는 이름을 가리키는 관계가 개체를 새로 만들지 않는다.
- 방향만 반대인 관계는 뒤집혀 저장된다.
- 사용자 관계 종류를 `extract=1`로 켜면 추출 형식에 들어가고 허용 종류 검사를 받는다.
- 화면 편집으로 허용되지 않는 관계를 만들면 지금처럼 400.
- `dropped` 개수가 반환·로그에 남는다.
- A5 규칙: `N5800`과 `N5800-GB70-PU02`가 다른 개체다.

---

## 7. GR4 — 사양 DB를 그래프로 투영

### GR4-1. 무엇을 개체·관계로 만드는가

| 사양 DB | 그래프 | 출처 |
|---------|--------|------|
| `product` 전부 | 제품 개체 (`ref_type='product'`) | spec |
| `component` 전부 | 부품 개체 (`ref_type='component'`) | spec |
| `product.parent_id` | `variant_of` | spec |
| `product_component` | `has_component` (`is_option`) | spec |
| 그래프 연결이 지정된 속성의 값 (GR4-2) | 값이 가리키는 개체와 관계 | spec |
| 그 밖의 사양 값 (숫자·예/아니오·서술) | 개체로 만들지 않는다. 개체 패널이 사양 DB에서 바로 읽어 보인다 (GR4-4) | — |

지금은 연결된 부품만 심는다(지시서 H2). 이번에 **부품 전부**로 바꾼다. 관계 없는 부품이 화면을 덮는 문제는 GR4-5의 화면 필터로 푼다.

### GR4-2. 속성의 그래프 연결 지정
`spec_attribute`에 열 두 개 (`_migrate`). 속성을 새로 만드는 것이 아니다.
- `graph_relation_type TEXT` (예: `has_component`). NULL이면 그래프 연결 없음
- `graph_entity_type TEXT` (예: `component`). 관계의 도착 종류

값 하나가 관계 하나다.
- 도착 개체 이름 = 값 문자열에서 끝 괄호를 뺀 것 (`NVIDIA GeForce RTX 5070 (105W)` → `NVIDIA GeForce RTX 5070`). 값 원문은 별칭으로, 제조사 이름을 뺀 이름(`GeForce RTX 5070`)도 별칭으로 넣는다.
- 도착 개체 찾기: 정식 이름 맞춤 키로 사양 DB 부품 → 이미 있는 같은 종류 개체 → 새 개체 순서. 사양 DB 부품과 맞으면 `ref`를 단다. 새로 만든 개체는 `creation_origin='spec'`.
- 관계: 제품 → 도착 개체, `origin='spec'`, `is_option`은 값의 옵션 여부, `source_key='spec:value:<spec_value_id>'`.
- 출발(제품)·도착 종류는 GR3-1의 허용 종류 검사를 받는다. 맞지 않는 지정은 저장할 때 400.
- 관계를 만들 수 없는 값(빈 값, 식별자 규칙을 어기는 값)은 건너뛰고 투영 요약에 개수를 남긴다.

기본 지정 (열이 NULL이고 속성 키가 있을 때 한 번만 넣는다. R&D가 바꾸면 덮지 않는다)

| 속성 키 | 연결 |
|---------|------|
| `cpu_model` | `has_component` → `component` |
| `gpu_model` | `has_component` → `component` |
| `chipset` | `has_component` → `component` |
| `wifi` | `has_component` → `component` |

이 네 개 말고는 R&D가 `/spec` 속성 탭에서 지정한다 (GR4-6).

### GR4-3. 동기화
- `seed_specs()`를 `project_specs()`로 바꾼다. 매번 `origin='spec'` 관계만 지우고 다시 넣는다 (지금과 같다). 문서 추출·사람이 넣은 관계는 건드리지 않고, 화면에서 지운 관계(`graph_exclusion`·`graph_relation_block`)는 되살리지 않는다.
- 부르는 때: 서버 시작, 사양 저장 API 전부(제품·부품·값·연결·속성의 그래프 연결 지정·엑셀 가져오기 적용). 지금 `reseed_spec_graph`를 부르지 않는 쓰기 경로가 있으면 다 붙인다.
- 사양 DB에서 사라진 대상을 가리키는 `ref`는 지금처럼 지운다. 투영으로 만든 개체(`creation_origin='spec'`)가 등장 위치도 관계도 없게 되면 정리된다.
- 투영 요약(`products, components, variant_of, has_component, value_relations, skipped_values, blocked`)을 로그에 남긴다.

### GR4-4. 개체 패널의 사양 값
- `GET /graph/entities/{id}`: `ref`가 있으면 `spec` 항목에 `spec_service.effective_specs` 결과를 싣는다 (속성 이름, 값, 단위, 옵션, 상속 출처, 부품 경유). 복사본이 아니라 그때의 사양 DB 값이다.
- 화면: 개체 패널에 "사양 DB" 영역. 분류별로 접어서 보이고, "사양 화면에서 열기" 링크(`/spec?product=` 또는 `?component=`, 이미 있는 URL 쿼리).
- 사양 값은 그래프 화면에서 고치지 않는다 (사양 화면에서 고친다).

### GR4-5. 그래프 화면
- 관계 출처 표시(문서·사양 DB·사용자)를 범례에 둔다 (이미 있는 `ORIGIN_META` 사용).
- "관계 없는 사양 개체 숨기기"를 기본 켬으로 둔다. 끄면 부품 123개가 모두 보인다.
- 개체 종류 필터와 출처 필터가 같이 동작한다.

### GR4-6. 사양 화면
`/spec` 속성 탭에 "그래프 연결" 칸: 연결 없음 / 관계 종류 + 도착 개체 종류 선택. 고르면 저장 뒤 투영이 다시 돈다. 인증 분류(`cert`) 속성도 지정할 수 있다 (예: `cert_model` → 사용자가 정할 관계). 엑셀 양식은 바꾸지 않는다.

### GR4-7. 검색
`graph_search`는 바꿀 것이 거의 없다. 투영 관계가 `relations`에 `(사양 DB)` 근거로 이미 나온다. 확인할 것:
- `graph_search("A650 GPU")`의 관계에 `A650 -[has_component]-> NVIDIA GeForce RTX 5070 (사양 DB)`가 나오고, 도착 개체의 `matched`에 `ref`가 있으면 `get_specs`로 이어진다.
- 그래프 관계는 여전히 근거가 아니다. 답에 쓰려면 `get_specs`로 사양 값을 읽는다 (프롬프트 v4에 그대로).

**테스트** (fixture DB)
- 제품·부품 전부가 개체가 되고 `ref`가 달린다. 연결 없는 부품도 개체가 있다.
- `cpu_model = AMD Ryzen AI 7 350` 값이 `제품 -has_component-> AMD Ryzen AI 7 350`이 되고, 같은 이름의 사양 DB 부품에 붙는다 (새 개체를 만들지 않는다).
- `gpu_model = NVIDIA GeForce RTX 5070 (105W)`이 `NVIDIA GeForce RTX 5070` 개체가 되고, 문서 추출의 `GeForce RTX 5070`이 같은 개체에 붙는다.
- 옵션 값은 `is_option=1` 관계.
- 값을 지우면 관계가 사라지고, 다시 투영해도 화면에서 지운 관계는 돌아오지 않는다.
- 속성의 그래프 연결을 허용되지 않는 종류로 지정하면 400.
- 사양 데이터 행 수가 투영 전후 같다.
- 사양 쓰기 API 모두가 투영을 다시 부른다.
- 개체 패널 응답의 사양 값이 사양 DB를 고친 직후 바뀐다.
- `GRAPH_SPEC_SEED_ENABLED=false`면 투영하지 않는다.

---

## 8. GR5 — 프롬프트 v4와 절차 문서

### 프롬프트 v4
`agent/prompt.py`에 `PROMPT_V4_NAME = "v4 근거 ID·사양·그래프 정비"`로 넣고 `ensure_seeded`로 한 번 등록·선택한다. v2·v3 행은 그대로 둔다. `SYSTEM_PROMPT_TEMPLATE`도 v4로. 본문은 **지금 v3 본문에서 아래만 바꾼다.**

1. `**용어 별칭 (표준 이름 = 별칭)**` 줄과 `$aliases` 줄을 지운다.
2. 도구 표의 `graph_search` 행을 다음으로 바꾼다:
   `| graph_search | 질문의 모델명·부품·인증·규격으로 관련 개체, 관계, 문서(file_id)와 페이지를 찾는다. 관계에는 출처(문서·사양 DB·사용자 입력)가 붙는다. matched의 ref_type·ref_id는 get_specs에 넘길 수 있다 |`
3. "지켜야 할 것"의 `- 상위 개념이 펼쳐졌으면 속한 종류마다 문서를 찾고, 찾지 못한 종류는 "문서 없음"으로 밝힌다.`를 다음으로 바꾼다:
   `- 인증 묶음 이름(예: KC 인증)은 시스템이 속한 종류로 펼쳐 주지 않는다. 그 모델의 인증 관계와 인증서 문서에서 확인한 종류만 쓰고, 묶음에 무엇이 들어가는지 근거가 없으면 "확인 필요"로 밝힌다.`

`docs/prompt_v4.md`에 바뀐 곳과 전문을 남긴다.

### 절차 문서 `skills/certification-bundle/SKILL.md` (version 3)
설계자가 정한 문장이다. 이 부분만 바꾸고 나머지는 그대로 둔다.
- 절차 1을 다음으로 바꾼다: `1. **요청한 인증과 모델을 찾는다.** graph_search에 모델명과 인증 이름을 넣는다. 결과 relations의 인증 관계(has_certification, has_number)와 documents를 본다. 인증 묶음 이름(예: KC 인증)은 시스템이 속한 종류로 펼쳐 주지 않는다.`
- 절차 5 뒤에 한 줄을 더한다: `6. **묶음 이름으로만 물었으면** 그 모델의 인증 관계와 인증서 문서에서 확인한 종류를 모두 적고, 묶음에 더 들어가야 할 종류가 있는지는 "확인 필요"로 밝힌다.`
- `metadata.version`을 `"3"`으로.

다른 절차 문서는 바꾸지 않는다. 절차 본문의 도구 이름 검사 테스트가 통과해야 한다.

**테스트**: v4가 한 번만 등록·선택된다. 렌더링된 시스템 프롬프트에 "상위 개념"·"용어 별칭"이 없다. `certification-bundle` 본문에 "펼쳐진다"가 없다.

---

## 9. GR6 — 기존 그래프 정리

코드가 바뀌어도 이미 저장된 잘못된 개체·관계는 남는다. 문서 추출로 생긴 것(`origin='extract'`)은 재추출로 갈아끼운다.

1. 사용자가 서버 DB를 백업한다.
2. 서버 재시작 → GR1 마이그레이션(개념 삭제), GR2·GR3 테이블, GR4 투영이 적용된다.
3. 지식 그래프 화면의 전체 다시 만들기(`POST /graph/rebuild`)를 사용자가 실행한다. 문서 수에 비례해 로컬 모델 시간이 걸린다.
4. GR0 점검 스크립트를 다시 돌려 전후를 비교한다.

구현자가 할 일: 위 절차를 `docs/dev_log/GR-GR6.md`에 사용자용으로 적고, 로컬에서 문서 2~3개를 사본 DB에 올려 재추출 전후 점검 결과를 붙인다. 운영 DB에서 재추출하지 않는다.

수동 개체·관계 중 검사 규칙을 어기는 것은 지우지 않고 점검 결과 목록으로 사용자에게 넘긴다.

---

## 10. GR7 — 확인

### 자동
- `.venv/Scripts/python.exe -m pytest tests -q` 전체 통과
- `npx tsc -b`, `npx eslint src/knowledge src/spec`, `npm run build`
- 사본 DB 마이그레이션 예행: 두 번 실행해 결과가 같고, `concept`·`part_of` 0건, 사양 데이터 행 수 그대로, 수동 관계 수 그대로

### 실서버·실모델 (사용자가 재시작·재추출한 뒤, 읽기 전용)
캡처가 나온 서버에서 같은 화면을 다시 본다.

| 확인 | 기대 |
|------|------|
| GeForce RTX 5070 개체 | `발급 기관 → NVIDIA` 없음 (문서에 근거가 있으면 `제조사 → NVIDIA`). Tensor 코어·RT 코어·Blackwell 아키텍처·Blackwell Max-Q 부품 없음. A650 제품들에서 `부품(사양 DB)` 관계로 들어옴 |
| AMD Ryzen AI 7 350 | 종류가 부품. Radeon·Ryzen·XDNA 없음. 사양 DB 부품과 같은 개체이고 패널에 사양 값이 보임 |
| 상위 개념 | 화면·객체 추가 목록·범례 어디에도 없음 |
| 객체 추가 | 개체 종류 목록이 DB에서 오고, 사용자 종류를 만들면 목록에 나타남 |
| `/ask` "A650 GPU 알려줘" | `graph_search`가 사양 DB 관계를 보여 주고, 답은 `get_specs` 근거로 씀 |
| `/ask` "N5800 KC 인증 자료" | 묶음을 펼치지 않음. 확인한 종류와 "확인 필요"를 밝힘 |

결과는 `docs/dev_log/GR-live-check.md`. 기대와 다르면 코드를 고치지 말고 결과만 적는다.

### Gemini 검증
| 번호 | 조건 |
|------|------|
| GR-1 | 코드·DB·프롬프트·절차·화면 어디에도 상위 개념이 없다. `aliases.yaml`이 없다 |
| GR-2 | 개체 종류가 DB에서 오고, 추출·편집·화면이 같은 목록을 쓴다. `product`·`component`는 사용 중지할 수 없다 |
| GR-3 | 추출 관계가 허용 종류 검사를 받는다. 관계 끝 자동 채우기가 없다 |
| GR-4 | 식별자 규칙과 정식 종류 우선이 저장 전에 적용된다 |
| GR-5 | 사양 DB 제품·부품 전부와 지정된 속성 값이 그래프에 투영되고, 사양 데이터는 바뀌지 않는다 |
| GR-6 | 숫자 사양 값은 개체가 아니고, 패널은 사양 DB를 실시간으로 읽는다 |
| GR-7 | 화면에서 지운 관계·수동 관계가 투영·재추출 뒤에도 유지된다 |
| GR-8 | 그래프 관계는 근거가 아니고, 답은 `get_specs`·`read_pages` 근거로만 쓴다 |
| GR-9 | 전체 테스트·타입·린트·빌드 통과, 실행 한도·맥락 예산 그대로 |

---

## 11. 하지 않는 것

- 상위 개념·인증 묶음의 대체 기능 (사용자가 다시 구현한다)
- 사양 데이터 수정, `product_component` 자동 생성 (값에서 관계를 투영할 뿐 사양 DB에 연결 행을 만들지 않는다)
- 숫자·서술 사양 값을 개체로 만드는 것
- 제조사 관계를 이름에서 추론해 만드는 것 (`NVIDIA GeForce …`에서 `made_by NVIDIA`를 만들지 않는다. 문서 추출로만 생긴다)
- 운영 DB에서 재추출, 수동 개체·관계 삭제
- 추출 대상 종류를 LLM이 스스로 늘리는 것

---

## 12. 사용자 확인 사항

1. 재시작 전에 그래프가 있는 서버의 DB를 백업한다. 재시작으로 상위 개념이 지워지고 테이블·열이 더해진다.
2. 재시작 뒤 지식 그래프 화면에서 전체 다시 만들기를 실행해야 기존의 잘못된 연결이 사라진다.
3. "KC 인증 자료" 같은 묶음 질문은 다시 구현할 때까지 펼쳐지지 않는다.
4. CPU·GPU·칩셋·무선 LAN 말고 그래프로 연결할 속성은 `/spec` 속성 탭에서 지정한다.
5. 캡처가 나온 서버의 DB 사본을 주면 GR0 점검을 그 데이터로도 돌린다.
