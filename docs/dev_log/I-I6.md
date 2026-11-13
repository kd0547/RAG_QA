# I-I6 업무 절차 화면 (`/skill`)

## 변경 파일
- `frontend/src/skill/`(신규)
  - `api.ts`: `/skills` API 클라이언트와 응답 타입
  - `SkillSection.tsx`: 상단 탭 세 개(검토 대기·사용 중 절차·문의 유형). 탭과 고른 초안·절차를 주소(`/skill?tab=…&doc=…&name=…`)에 둔다 (새로 고침·뒤로 가기 유지, 자동 선택은 기록을 늘리지 않게 `replace`)
  - `ReviewTab.tsx`: 초안 목록(이름, 유형, 생성 시각, 검사 결과, 상태, 상태 필터) + 상세(설명·본문 편집, 검사 errors·warnings, 재료 사례와 검토 화면 링크, 저장·승인·반려·다시 생성). `generating`은 진행 표시와 10초 주기 갱신, `error`는 사유, `rejected`는 반려 사유
    - 승인 버튼: 검사 errors가 있거나 저장하지 않은 변경이 있으면 비활성. 옆에 "승인하면 이후 답변에서 모델이 이 절차를 골라 읽을 수 있습니다"
    - 승인 대화상자: 메모 입력 + "로그인 기능이 없어 승인자는 요청한 PC의 IP 주소로만 기록됩니다"
    - 반려 대화상자: 사유 필수
  - `ActiveTab.tsx`: 저장소 절차와 승인본 목록(출처 배지 기본·생성, 버전, 최근 30일 사용, 서버 적용 여부, 채널). 상세에 본문·버전 이력. 승인본은 "고치기(새 버전 초안)"·"사용 중지"(확인 대화상자), 사용 중지된 것은 "다시 쓰기(새 버전 초안)". 저장소 절차는 보기만(고치는 방법 안내)
  - `TypesTab.tsx`: 유형별 분석 건수, 맡는 절차, 상태, 최근 사례(검토 화면 링크), 분석·실제 사용 어긋남 건수(누르면 어긋난 문의 목록). 버튼: 초안 만들기/초안 보기, 절차 불필요로 표시 ↔ 되돌리기, 다른 유형과 합치기(대화상자). 합쳐진 유형은 아래에 따로
  - `ui.tsx`(컴포넌트: 칩, 배지, 오류 상자, 작성 절차 없음 안내, 대화상자), `format.ts`(오류 문구·날짜·상태 표시·버튼 클래스), `paths.ts`(`skillPath`)
- `frontend/src/components/AppHeader.tsx`: 상단 메뉴 "업무 절차"(`/skill`, 지식 그래프와 프롬프트 사이)
- `frontend/src/Root.tsx`: `/skill` → `SkillSection`
- `frontend/src/lib/router.ts`: 경로 목록 주석, `navigate(path, { replace })` 선택 인자 (기존 호출은 그대로)
- `frontend/vite.config.ts`: 프록시 `/skills`

## 결정한 것
1. **API 실패 표시는 프롬프트 화면 방식**(오류 상자 + 다시 시도)을 따랐다. 메일 화면의 예시 데이터(MockBadge) 방식은 승인 화면에 맞지 않는다: 예시 초안을 실제 초안으로 오인해 승인을 누를 수 있기 때문이다.
2. 작성 절차(`create-skill`)가 없으면 세 탭 모두 위쪽에 "작성 절차 없음" 안내(서버가 준 사유 포함)를 보이고 초안 만들기·다시 생성 버튼을 끈다.
3. 본문 편집·보기는 고정폭 글꼴 대신 기본 글꼴(Pretendard)을 쓴다. 고정폭 글꼴에 한글 글리프가 없어 자간이 벌어져 보였다.
4. 초안 목록에서 생성 중·실패 초안은 이름 대신 "이름 정하는 중"/"이름 없음"으로 보인다 (서버가 임시 이름을 숨긴다, I5).

## 테스트: 명령과 출력
```
cd frontend
npx tsc -b            → 출력 없음 (exit 0)
npx eslint src/skill src/lib/router.ts src/Root.tsx src/components/AppHeader.tsx   → 출력 없음
```

dev 서버 확인 (운영 DB 사본)
- 백엔드: 운영 `storage/mail.db`를 `mode=ro`로 읽어 scratchpad에 사본을 만들고, `sqlite3.connect`를 가로채 운영 경로를 사본으로 돌린 뒤 `/skills` 라우터만 8010 포트에 띄웠다 (메일·분석 스레드 없음, Chroma 대역). 사본에 확인용 유형 2개·분석 7건·초안 2건(정상 1, 없는 도구 이름 1)을 넣었다.
- 프론트: `VITE_PROXY_TARGET=http://127.0.0.1:8010 npm run dev -- --port 5174`
- 순서: `warranty-terms` 초안 본문 수정 → 저장("저장했습니다. 검사를 통과했습니다.") → 승인 대화상자(메모, IP 안내) → 승인 → 사용 중 절차 탭에 `warranty-terms v1 · 생성` → 사용 중지 → 목록에서 빠지고 이력에 `v2 사용 중지`, 버튼이 "다시 쓰기"로
- 검사 오류 초안(`repair-intake`): 승인 버튼 비활성(`title=검사 오류가 있어 승인할 수 없습니다`), API 직접 호출도 400 "검사 오류가 있어 승인할 수 없습니다: 없는 도구 이름을 가리킵니다: read_warranty_table …"
- 휴대폰 폭(375px)에서 세 탭 모두 가로 넘침 없음 (`scrollWidth == clientWidth == 375`)
- 콘솔 오류: 404 여러 건(확인용 백엔드에 `/skills` 외 API가 없어서 생김), 400 1건(위의 직접 승인 호출)

화면 캡처
- `docs/dev_log/img/I-I6-approve-dialog.jpg` — 승인 대화상자
- `docs/dev_log/img/I-I6-active-retired.jpg` — 사용 중지 뒤 상세와 버전 이력
- `docs/dev_log/img/I-I6-review-errors.jpg` — 검사 오류 초안 (승인 불가)

## 확인하지 못한 것 / Gemini에게 요청할 검증
- 운영 서버의 `npm run build` 결과물로는 확인하지 않았다 (빌드는 사용자 몫).
- "다시 생성"·"초안 만들기"의 실제 생성은 `create-skill`이 없어 화면에서 확인하지 못했다 (버튼이 꺼지고 안내가 보이는 것까지 확인).
- I-10(초안 화면에 재료 사례와 검사 결과, errors면 승인 불가): 위 화면 확인과 `tests/test_skill_api.py`.

## 커밋 해시
(I-summary.md에 적는다)
