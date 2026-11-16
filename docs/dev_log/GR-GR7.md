# GR-GR7 기존 그래프 정리

코드가 바뀌어도 이미 저장된 잘못된 개체·관계는 남는다. 문서 추출로 생긴 것(`origin='extract'`)은 재추출로 갈아끼운다.
사람이 넣은 개체·관계는 규칙을 어겨도 지우지 않는다(규칙 위반 목록으로 넘긴다).

## 사용자 절차 (그래프가 있는 서버마다)

1. **DB 백업**: 서버를 멈추고 `storage/mail.db`를 복사해 둔다 (예: `storage/mail.db.bak-YYYYMMDD`).
   재시작하면 아래가 자동으로 적용된다 — 되돌리려면 이 백업이 필요하다.
   - 시스템 상위 개념(`concept` 개체, `part_of` 관계·관계 종류, 그 차단 기록) 삭제 (GR1)
   - `graph_entity_type` 테이블과 기본 8종, 관계 종류의 `extract` 열·`made_by`·`has_spec`, 기본 관계의 허용 종류 갱신(사용자가 고치지 않은 것만) (GR2·GR3)
   - `graph_entity.type_locked`·`ref_value`, `spec_attribute.graph_mode` 등 열 추가와 기본값 (GR4)
   - 사양 DB 투영: 제품군·제품·부품·사양 값 노드 수백 개와 `has_spec` 관계 천여 개 (GR4)
   - 프롬프트 v4 등록·선택 (GR6)
2. **서버 재시작**. 로그에서 확인:
   - `시스템 상위 개념 삭제 (GR1): {...}` (지울 것이 있을 때만)
   - `사양 DB 그래프 투영: {'product_lines': .., 'products': .., 'components': .., 'value_nodes': .., ..., 'seconds': ..}`
   - `프롬프트 등록·선택: v4 근거 ID·사양·그래프 정비`
3. **지식 그래프 화면 → "전체 다시 만들기"** (`POST /graph/rebuild`). 페이지마다 LLM을 부르므로 문서 양에 따라 오래 걸린다(백그라운드). 끝나면 로그에 파일마다 `그래프 파일 추출: {..., 'dropped': {'type': n, 'identifier': n, 'relation_endpoint': n, 'relation_type': n}}`가 남는다.
4. **점검 스크립트로 전후 비교**: 1번 백업과 지금 DB에 각각 돌려 비교한다 (읽기 전용, 운영 DB를 고치지 않는다).
   ```
   .venv/Scripts/python.exe scripts/audit_graph.py --db storage/mail.db.bak-YYYYMMDD > before.md
   .venv/Scripts/python.exe scripts/audit_graph.py --db storage/mail.db > after.md
   ```
5. **규칙 위반 목록 확인**: 지식 그래프 화면 "규칙 위반 목록". 사람이 넣은 것 중 의도한 것은 그대로 두고, 아닌 것만 화면에서 고친다.

## 로컬 예행 (사본 DB, 실제 문서 3개, 실모델)

- 사본: 운영 DB(`mode=ro`)를 백업 API로 복사. 모든 스크립트는 `sqlite3.connect` 가드(운영 경로 → 임시 폴더)를 먼저 설치하고 실행했다.
- 문서: `tests/data`의 A650 제안서(docx, 1쪽), N5800 세일즈 가이드(pdf, 12쪽), N5800 KC 안전확인 신고증명서(pdf, 21쪽) = 34쪽. 파서 OCR과 추출은 설정된 로컬 vLLM(`qwen3.8-flash-next`)을 썼다.
- 전: GR 이전 코드(`d68d721`, 별도 worktree)로 옛 서버 시작(aliases.yaml 상위 개념 심기·`seed_specs`) + 문서 3개 추출. 1,196초.
- 후: 같은 사본에 새 코드로 재시작(마이그레이션·투영) + 전체 다시 만들기(`index_all`). 투영 0.22초, 재추출 1,325초.

### 추출 요약 (파일별)
| 문서 | 전 (개체/관계) | 후 (개체/관계) | 후 dropped |
|------|---------------|----------------|-----------|
| A650 제안서 | 16 / 10 | 15 / 10 | relation_endpoint 2 |
| N5800 세일즈 가이드 | 38 / 5 | 17 / 6 | identifier 1, relation_endpoint 2 |
| N5800 KC 인증서 | 442 / 275 | 446 / 729 | identifier 1, relation_endpoint 17 |

### 점검 스크립트 전후
| 항목 | 전 | 후 |
|------|----|----|
| 상위 개념 개체 / part_of 관계 | 1 / 10 (seed 4, **extract 6**) | 0 / 0 |
| 허용 종류를 어긴 관계 | 3 (component -issued_by-> 회사 2, component -has_number-> 1) | 0 / 활성 관계 2,298 |
| 식별자 규칙을 어기는 개체 | 7 (extract 6: AMD Kracken Mobile Platform, Intel® Core U-Series (Series 1), HD Digital Video (HDMI), USB 2.0 Type-A 포트, Micro SD 카드리더, Kensington Lock / legacy 1: Windows 11) | 2 (Windows 11 legacy, AMD Kracken Mobile Platform — 사양 DB 부품 노드에 붙은 것이라 규칙을 건너뜀) |
| 사양 DB와 이름이 같은데 종류가 다른 개체 | 1 (A650 Series: product, 기준 product_line) | 0 |
| 관계 종류 | — | made_by 44 (예: `AMD Ryzen AI 7 350 -made_by-> AMD`, `GeForce RTX 5070 -made_by-> NVIDIA`), issued_by 32 |
| 사양 투영 | variant_of 2 | product_line 1, product 3, 부품 123, 사양 값 노드 341, has_spec 1,539, entity 12 |
| 사양 데이터 행 수 (product/component/spec_value/product_component) | 4/123/1572/0 | 4/123/1572/0 |
| 수동 관계 | 1 | 1 |

- 이번 실행에서 LLM은 두 번 모두 Tensor 코어·RT 코어·Blackwell·Radeon·XDNA 같은 이름을 뽑지 않았다(실모델 출력이 매번 다르다). 캡처의 그런 잡음이 걸러지는 것은 대역 모델 테스트(`tests/test_graph_extract_rules.py::test_capture_page_is_cleaned_before_saving`)로 확인했다.
- KC 인증서의 관계 수가 275 → 729로 는 것은 같은 페이지를 다시 부른 LLM 출력 차이(파생 모델 목록과 번호 관계를 더 많이 뽑음)가 크다. 버린 관계는 끝 개체가 없는 것 17개였다.
- 사람이 넣은 개체·관계는 지우지 않았다. 남은 규칙 위반은 화면의 "규칙 위반 목록"에 보인다.

### 전체 점검 결과 (후)
```
# 지식 그래프 점검 (읽기 전용)

- 스키마: GR2 이후 (graph_entity_type)
- 개체 종류: product_line, product, component, spec_value, certification, cert_number, organization, standard
- 관계 종류: complies_with, has_certification, has_component, has_number, has_spec, issued_by, made_by, variant_of

## 1. 개체 종류별·출처별 개수 (활성)

| 종류 | 출처(creation_origin) | 개수 |
|---|---|---|
| cert_number | extract | 20 |
| certification | extract | 8 |
| component | extract | 42 |
| component | legacy | 1 |
| component | spec | 123 |
| organization | extract | 27 |
| product | extract | 140 |
| product | legacy | 3 |
| product_line | legacy | 1 |
| spec_value | spec | 341 |
| standard | extract | 4 |

상태별: active 710

## 1. 관계 종류별·출처별 개수 (활성)

| 관계 종류 | 출처(origin) | 개수 |
|---|---|---|
| complies_with | extract | 49 |
| has_certification | extract | 71 |
| has_component | extract | 323 |
| has_component | spec | 12 |
| has_number | extract | 226 |
| has_spec | spec | 1539 |
| issued_by | extract | 32 |
| made_by | extract | 44 |
| variant_of | spec | 2 |

## 2. 상위 개념 개체와 part_of 관계

(없음)

(없음)

## 3. 허용 출발·도착 종류를 어긴 관계 (활성)

위반 0건 / 활성 관계 2298건

(없음)

## 4. 식별자 규칙을 어기는 개체 (활성)

식별자가 필요한 종류: cert_number, component, product, product_line

위반 2건 (출처별: {'legacy': 1, 'extract': 1})

| id | 종류 | 이름 | 출처 | 사양 참조 |
|---|---|---|---|---|
| 100 | component | Windows 11 | legacy |  |
| 191 | component | AMD Kracken Mobile Platform | extract |  |

## 5. 사양 DB 모델명과 맞춤 키가 같은데 종류가 다른 개체

(없음)

## 6. 관계도 등장 위치도 없는 개체

1개
```

## 결정한 것
- "전"을 운영 DB 사본 + GR 이전 코드로 만들었다(운영 DB는 GR1 사고로 이미 개념이 지워져 있었으므로, 옛 코드의 서버 시작이 aliases.yaml 개념을 다시 심게 했다). 그래서 "전"에는 옛 서버와 같은 개념·part_of가 있다.
- 운영 DB에서는 재추출하지 않았다.

## 확인하지 못한 것
- 캡처가 나온 서버에서의 재추출 결과 (사용자 실행 후 GR8 실서버 확인).

## 커밋 해시
GR-summary.md에 모은다.
