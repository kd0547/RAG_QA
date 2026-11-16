# GR-GR8 확인

## 자동
| 확인 | 결과 |
|------|------|
| `.venv/Scripts/python.exe -m pytest tests -q` | `564 passed in 82.51s` (기준선 493 → GR 테스트 71개 추가) |
| `npx tsc -b` (frontend/) | 통과 (출력 없음) |
| `npx eslint src/knowledge src/spec` | 통과 (출력 없음) |
| `npm run build` | `✓ built` (500kB 넘는 청크 경고는 기존 MarkdownEditor) |
| 사본 DB 마이그레이션 예행 | 가드 설치 후 두 번 실행, 결과 같음. concept·part_of 0건, 사양 데이터 행 수 그대로(4/123/1572/0), 수동 관계 1 → 1, 투영 요약 `{'product_lines': 1, 'products': 3, 'components': 123, 'value_nodes': 341, 'variant_of': 2, 'has_component': 0, 'has_spec': 1539, 'entity_relations': 12, 'skipped': 0, 'blocked': 0, 'seconds': 0.073}` (GR-GR4.md) |
| 사본 재추출 전후 | GR-GR7.md |

## 화면 (임시 백엔드 8010 + Vite 5174, 운영 DB 사본)
- 지식 그래프: 범례 칩이 스키마 응답(제품군 1·제품 3·부품 127·사양 값 341). 전체 보기에 사양 값 노드 없음. 두 필터(사양 값은 이웃만, 관계 없는 사양 노드 숨기기) 기본 켬.
- A650(제품군) 선택: 계층 보기 자동 켬(제품군 위, 하위 모델 아래), 패널에 종류 바꾸기, "사양 DB와 다름"(사람이 지운 관계 `Windows 11 -부품→ A650 Series`)과 되돌리기 단추, 모델 계층(하위 모델 2), 사양 DB 34개 분류별 접기.
- 개체 종류 대화상자: 기본 8종, 기본 종류 `제품군` 이름을 `제품군(시리즈)`로 저장 → 목록·필터 칩에 반영. 이때 저장 단추 글자가 안 보이는 문제(흰 배경 클래스와 겹침)를 찾아 `EntityTypes.tsx`·`DefinitionEditors.tsx`에서 고쳤다.
- 규칙 위반 목록: 관계 0, 식별자 없는 부품 2(사양 DB 1·기존 데이터 1).
- 사양 화면 속성 탭: "그래프" 칸 — cpu_model 대상 노드(관계·종류 선택), 숫자 속성 사양 값 노드.
- 콘솔 오류는 임시 백엔드에 없는 `/config`, `/groups` 404 두 종류뿐(그래프와 무관).
- 기존 `GraphEditing.tsx`의 주 단추(`primary`)도 같은 클래스 겹침이 있다. 이번 범위 밖이라 고치지 않았다.

## 실서버·실모델
`GR-live-check.md`.
