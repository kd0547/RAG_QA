# 인계: 통합 지시서(remaining) 진행 상황 — 2026-11-13

지시서: [opus_development_instructions_remaining.md](../opus_development_instructions_remaining.md)

## 끝난 것 (커밋됨, 전체 테스트 453 passed)

| 항목 | 커밋 | 기록 |
|------|------|------|
| R0 D 요약 | `24dc2dd` | [D-summary](D-summary.md) |
| E1 상속 허용·점검 스크립트 | `f9aa7c0` | [E-E1](E-E1.md), [E-spec-audit](E-spec-audit.md) |
| E2 사양 서비스 | `0c19740` | [E-E2](E-E2.md) |
| E3 사양 도구 4개·근거 | `d400196` | [E-E3](E-E3.md) |
| E4 물려받기 체크박스 | `d22ae7f` | [E-E4](E-E4.md) |
| H1 저장 구조·CHECK 마이그레이션 | `9bc911e` | [H-H1](H-H1.md) |
| H2 seed_specs | `36420d8` | [H-H2](H-H2.md) |
| H3 추출 정식 이름 | `77b3bea` | [H-H3](H-H3.md) |
| H4 검색 ref·via | `d9f2d8b` | [H-H4](H-H4.md) |
| G1 고객 이력·메모 API | `7bbe1d6` | [G-G1](G-G1.md) |
| G2 메모 화면 | `06a277d` | [G-G2](G-G2.md) |
| Z1 프롬프트 v3·절차 교체 | `166317e` | [Z-Z1](Z-Z1.md) |
| T2 마이그레이션 예행 | (이 인계 커밋) | [T-migration](T-migration.md) — 추가만 있음, graph_relation id·해시 동일, 2회 동일 |

## 진행 중 / 남은 것

1. **F1 deepagents 비교** — 시제품 코드 `tests/eval/deepagents_proto/`(이 커밋), API 정리는 [F-compare](F-compare.md) 1~3절에 씀.
   - 비교 실행이 백그라운드로 돌고 있었다 (현재 엔진 → 시제품 순, 9문항씩). 결과 폴더:
     `C:\Users\김동욱\AppData\Local\Temp\claude\17b9a6af8eebcf5c\dfe462b8-3696-4fbb-be30-5a54662aefa0\scratchpad\f_run\`
     (`current.json`, `proto.json`, `current.log`, `proto.log`, 끝나면 `done.txt`에 exit 코드)
   - 남은 일: 결과가 다 있으면 `.venv/Scripts/python.exe tests/eval/deepagents_proto/compare.py <위 폴더>`로 표를 만들어 F-compare.md 4절에 붙이고 해석(로컬 문서 2개뿐인 한계, 시제품은 langchain 1.5/langgraph 1.2.21) 적기. 결과가 없거나 중간에 끊겼으면 같은 명령으로 다시 돌린다 (README 참고).
   - 스모크 1문항(#6 TI600s↔C910G): 시제품 28초, 도구 14회(오류 0), 검증 통과.
   - **비교 실행 완료** (두 구성 exit 0). 표는 [F-compare-table.md](F-compare-table.md)에 생성해 둠: 9문항 모두 검증 통과(두 구성), 현재 엔진 도구 137회·오류 6·입력 1,457,313토큰·784초 / 시제품 도구 156회·오류 5·입력 2,256,057토큰·595초. 남은 일은 이 표를 F-compare.md 4절로 옮기고 문항별 해석(문서 2개 한계 포함)을 쓰는 것. 원본 JSON은 위 폴더.
2. **T1 기록** — 전체 테스트 453 passed. `npx tsc -b` 통과, `npm run build`는 임시 outDir로 통과(dist 안 건드림). `npx eslint src`는 **기존 `src/App.tsx` 오류 2건**(2026-11-05 이후 안 바뀐 파일, 이번 작업 무관)으로 실패 — 고친 폴더(spec·mail·knowledge)만 보면 통과. 사용자에게 알릴 것.
3. **Z2 `docs/dev_log/R-summary.md`** — 아직 안 씀. 항목·커밋 표(위 표), 전체 테스트 출력, 멈춘 항목(없음), 다르게 한 것(아래), 9절 확인 위치, **운영 DB 변경 표**(T-migration.md의 표 재사용: `customer_note` 테이블, `spec_attribute.inheritable`, `graph_entity.ref_type/ref_id`, `graph_relation` 재생성+`is_option`, v3 프롬프트 행, spec 관계 2개).
4. T3(사용자: DB 백업·`npm run build`·재시작), T4(사용자 지시 후 실서버 확인), T5(Gemini), T6(개발 서버) — 구현자가 먼저 하지 않는다.

## 지시서와 다르게 한 것 (R-summary에 옮길 것)
- 제품 이름은 모델명을 담을 때만 그래프 별칭·추출 "다른 표기"로 씀 (`Pro`/`Home`이 아무 질문에나 걸리는 문제) — H2·H3
- `graph_relation.is_option` 컬럼 추가 (옵션 여부 보관 위치가 지시서에 없음) — H1
- CHECK 마이그레이션은 외래키 검사를 끄고 옮김 — H1
- 별칭으로 통과는 정식 이름 목록에 있을 때만 — H3
- `find_entities`: 더 긴 모델명 안에만 있는 상위 모델은 직접 찾지 않음 (H-2 지키려고) — H4
- 고객 이력은 별도 저장소 `customer_history_repository.py` (D의 모델 입력 분리 경계 유지) — G1
- 사양 도구 `owner_id`에 정확한 모델명도 받음 — E3
- 인증 분류로 옮기는 것도 400 — E1

## 정리할 것
- 확인용 백엔드·프론트 dev 서버(포트 8010·5174, `.claude/launch.json`의 `rag-qa-stub8010-backend`)는 끄기. 임시 사본 폴더 `%TEMP%\ragqa-stub-*` 지우기.
- 사용자가 고친 `skills/skill-creator/SKILL.md`는 커밋하지 않는다.
