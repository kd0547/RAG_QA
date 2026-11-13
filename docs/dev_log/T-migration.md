# T2 마이그레이션 예행 (운영 DB 사본)

## 방법
- 운영 `storage/mail.db`를 `mode=ro`로 열어 sqlite backup으로 임시 폴더에 복사했다. 운영 경로로 가는 `sqlite3.connect`를 모두 사본으로 돌린 뒤 저장소를 임포트했다 (`agent_threads.db`도 임시 파일로).
- 서버 초기화 중 **DB를 바꾸는 단계만** `main.py` lifespan과 같은 순서로 불렀다: `Database`(스키마 + `_migrate`) → `ensure_default` → `ensure_v2` → `ensure_v3` → `ensure_seed_types` → `seed_concepts(aliases.yaml)` → `seed_specs`. 메일 수신·처리·분석 스레드, 임베딩·LLM, 벡터DB는 띄우지 않았다.
- 같은 사본에 두 번 돌려 결과를 비교했다. 끝난 뒤 사본을 지웠다 (스크립트 종료 때 파일이 잡혀 있어 바로 지워지지 않아, 프로세스가 끝난 뒤 다시 지웠다).
- 실행 전후 운영 `mail.db`의 수정 시각·크기가 같았다 (`prod_untouched: true`).

## 마이그레이션 (`_migrate`) 전후

| 항목 | 전 | 후 |
|------|----|----|
| 새 테이블 | — | `customer_note` (0행) |
| `spec_attribute` 컬럼 | … | + `inheritable` (기존 90개 모두 0) |
| `graph_entity` 컬럼 | … | + `ref_type`, `ref_id` |
| `graph_relation` 컬럼 | … | + `is_option` (기존 행 모두 0) |
| `graph_relation` CHECK에 `spec` | 없음 | 있음 |
| `graph_relation` 인덱스 | 3개 | 3개 (`idx_graph_relation_unique`·`_dst`·`_file` 다시 만듦) |
| `graph_relation` 행 | 31 | 31, **id 목록과 (id, src, dst, type, file, page, origin, created_at) 해시 `3664d086eee0ddeb` 동일** |
| 기존 테이블 행 수 | — | **모두 같음** (마이그레이션만으로 바뀐 행 수 0) |
| 외래키 위반 (`PRAGMA foreign_key_check`) | 0 | 0 |

## 초기화 단계 (1회차)

| 단계 | 결과 |
|------|------|
| `ensure_v2` | 이미 있음 (None) |
| `ensure_v3` | `v3 근거 ID·사양` 등록·선택 (id 4). v2(id 3)는 내용 그대로, 선택만 풀림 |
| `ensure_seed_types` | 0 (이미 있음) |
| `seed_concepts` | part_of 2개 (예전과 같음) |
| `seed_specs` | 제품 4, 부품 0 (연결 0건), `variant_of` 2, `has_component` 0, 막힌 관계 0 |

행 수가 바뀐 테이블 (실행 전 → 1회차 뒤): `prompt` 3 → 4, `graph_relation` 31 → 33 (`spec` 2), `graph_alias` 96 → 97 (제품 이름 별칭 하나), `customer_note` 없음 → 0. `graph_entity`는 그대로다 — 제품 4개가 이미 문서에서 뽑힌 개체로 있어 새로 만들지 않고 ref만 달았다.

## 2회차
- `ensure_v3` None (다시 넣지 않음), 테이블·컬럼·행 수가 1회차 뒤와 **같다** (`seed_specs`는 spec 관계를 지우고 같은 2개를 다시 넣는다).
- 관계 출처: extract 28, manual 1, seed 2, spec 2 — 1회차 뒤와 같다.

## 사용자가 재시작 때 보게 될 것
- 프롬프트 화면에 `v3 근거 ID·사양`이 새로 생기고 선택된다. 다른 프롬프트를 고르면 다시 시작해도 그 선택이 유지된다.
- 지식 그래프에 `A650-GA70-OU01 → A650`, `A650-GA70-PU02 → A650`(상위 모델, 사양 DB) 관계 2개가 생긴다.
