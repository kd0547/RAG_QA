# 인계: 통합 지시서(remaining) 마무리 상태 — 2026-11-13

지시서: [opus_development_instructions_remaining.md](../opus_development_instructions_remaining.md)
전체 항목·커밋·DB 변경·검증 위치: **[R-summary](R-summary.md)**

## 이번 인계에서 끝낸 일

| 항목 | 결과 | 커밋·기록 |
|------|------|-----------|
| F1 비교 해석 | 원본 JSON으로 표 재생성·기존 표 일치 확인. F-compare 4절에 표와 9문항별 해석, 5~6절에 한계·재현 자료 작성 | `42c9b2a`, [F-compare](F-compare.md) |
| T1 재확인·기록 | pytest **453 passed**, 타입 검사·변경 폴더 린트·임시 outDir 빌드 통과. 전체 린트는 기존 App.tsx 오류 2건·경고 1건 | `8d59da5`, [T-T1](T-T1.md) |
| Z2 요약 | 전체 항목·커밋, 실제 테스트 출력, 미완료 범위, 설계와 다른 점, 운영 DB 변경 표, T1~T6·T5 세부 확인 위치 작성 | 본 인계 갱신과 같은 커밋, [R-summary](R-summary.md) |
| 확인 환경 정리 | 8010·5174 서버는 이미 종료. Temp의 `ragqa-stub-ebpja3pn`, `ragqa-stub-hbtt__fw` 사본 폴더 삭제 | [T-T1](T-T1.md) |

R0·E1~E4·H1~H4·G1~G2·Z1 구현과 T2 마이그레이션 예행은 이전에 완료됐다. 커밋표와 기록 링크는 R-summary에 모았다. 이번 마무리는 문서만 변경했다.

## 남은 것

1. **T1 기존 린트 오류**: `frontend/src/App.tsx` 315행 `react-hooks/immutability`, 319행 `react-hooks/preserve-manual-memoization`, 316행 의존성 경고. 마지막 변경은 2026-11-05 `52963dd`이며 이번 구현과 무관하다. 인계 지시대로 수정하지 않고 보고했다. T1 전체 통과로 표시하지 않는다.
2. **평가셋 빈 문항·정답**: 10번 주간판매 질문은 질문·mail_uid·task_id가 비어 있어 F1은 양쪽 9문항만 실행했다. 전 문항 `expected_evidence`·`expected_keywords`도 비어 있다. 담당자가 채워야 한다.
3. **T3 사용자 운영 반영**: 운영 `mail.db`·`agent_threads.db` 백업, frontend `npm run build`, 서버 재시작. 재시작 전 [R-summary의 DB 변경 표](R-summary.md#재시작-시-운영-db-변경-표)를 확인한다.
4. **T4 실환경 확인**: 사용자의 「통합 확인 진행」 지시 후 시행한다. 메일 흐름은 작업과 검토 알림을 발생시키며, S1 실제 승인 발송은 별도 지시가 필요하다. 결과는 `T-live-check.md`에 적을 예정이고 아직 파일을 만들지 않았다.
5. **T5 Gemini**: 읽기 전용 검증. [R-summary](R-summary.md)의 항목별 확인표와 D·I 요약을 사용한다.
6. **T6 개발 서버 기준선**: 사용자가 서버 주소를 제공한 뒤 문서 17개 환경에서 실행한다. 빈 문항·정답 칸 상태를 함께 기록한다.

## F 결과를 읽을 때

- 양쪽 9/9 서버 검증 통과는 정답률이 아니다. 시제품 3번은 `근거 줄 없음` 경고와 인용 0건이다.
- 현재 엔진: 도구 137회·오류 6·입력 1,457,313토큰·784.0초. 시제품: 도구 156회·오류 5·입력 2,256,057토큰·595.3초.
- 로컬 등록 문서는 2개다. 시제품은 langchain 1.5.0/langgraph 1.2.21과 자체 요약을 사용했고, 실제 문항에서 가상 `/docs/` 경로는 읽지 않았다. 상세 한계는 F-compare에 있다. 채택 여부는 결정하지 않았다.
- 원본 결과·평가 사본은 아래 폴더에 보존했다. 모델 실행을 다시 돌릴 필요 없이 `compare.py <폴더>`로 표를 재생성할 수 있다.

```text
C:\Users\김동욱\AppData\Local\Temp\claude\17b9a6af8eebcf5c\dfe462b8-3696-4fbb-be30-5a54662aefa0\scratchpad\f_run\
```

## 다음 작업에서도 유지할 경계

- 사용자의 `skills/skill-creator/SKILL.md` 수정과 기존 미추적 파일은 건드리거나 커밋하지 않는다.
- 운영 DB 점검은 저장소 모듈을 임포트하지 않고 `sqlite3`의 `mode=ro`로만 한다.
- 운영 반영·실메일 확인은 위 T3·T4 조건을 따른다. 인수인계 마무리만으로 진행하지 않는다.
- 구현과 설계의 차이 8건 및 F/T1 검증 차이는 [R-summary](R-summary.md)에 옮겼다.
