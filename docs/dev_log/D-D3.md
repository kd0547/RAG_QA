# D-D3 고객방 화면 (조회 전용)

## 변경 파일
- `frontend/src/mail/pages/MailCustomersPage.tsx`(신규)
  - 왼쪽 발신자 목록: 아바타, 주소, 마지막 수신 시각, 마지막 제목, 문의 수, 검토 필요 배지, 주소·제목 검색(300ms 지연)
  - 오른쪽 타임라인: 문의 묶음 머리줄(상태 칩, 제목, 수신 시각, "검토 화면에서 열기 →" `reviewPath(task_id)`), 사건 말풍선
    - `received`: 왼쪽 말풍선, 첨부 파일명 칩
    - `draft`: 오른쪽 말풍선. `current`가 아니면 흐리게 + "이전 초안", 본문 null이면 "본문 기록 없음", 적용 절차 이름 칩
    - `reject`·`retry`·`mark_sent`·`send`: 가운데 안내 줄 (반려 사유 그대로, 발송 결과·수신자·첨부, 보낸 본문 펼치기)
    - `run_failed`: 가운데 경고 줄
    - `inferred`: "기록 이전 작업이라 시각·본문이 정확하지 않을 수 있음", `truncated`: "8,000자까지만 표시"
  - 긴 본문은 `isLongBody` 기준으로 접음, 처음 열면 맨 아래(최근 문의)로 스크롤, 위쪽 "이전 문의 더 보기"(`next_before`)는 불러온 뒤 보던 위치 유지
  - 주소창 `?sender=`와 선택 동기화 (`replaceState`)
  - 승인·반려·편집 버튼 없음
- `MailSection.tsx`: 탭 "고객방"을 "전체 메일"과 "메일 검토" 사이에, 경로 `mail/customers`
- `format.ts`: `MAIL_PATHS.customers`, `customerPath(sender)`
- `types.ts`: `Customer`, `CustomerListResponse`, `TimelineEvent`(사건 종류별 유니언), `TimelineInquiry`, `CustomerTimeline`, `AppliedSkill`
- `api.ts`: `customerApi.list`, `customerApi.timeline`
- `ui.tsx` `ReceivedMessage`: 발신자 옆에 "고객방" 링크 (검토 화면·전체 메일 상세 공통)
- `mockData.ts`: `MOCK_CUSTOMERS`, `mockCustomers(q)`, `mockTimeline(sender)` — 추정 사건, 반려 전후 초안, 실행 실패 포함
- `lib/router.ts`(주석), `vite.config.ts`(프록시 `/customers`)

## 결정한 것
- 목록은 한 번에 200명까지 불러온다 (운영 발신자 3명). 페이지 넘김 UI는 넣지 않았다.
- API가 실패하면 목록·타임라인 모두 예시 데이터로 바꾸고, 고객방 제목 옆에 `MockBadge`를 띄운다 (메일 섹션 머리의 배지는 검토 대기열 기준이라 따로 둠).
- 초안 말풍선은 검토 화면처럼 마크다운으로 그린다. 접을 때는 `max-h-32`로 자른다 (마크다운에는 `line-clamp`가 맞지 않음).

## 확인: 명령과 결과
```
cd frontend && npx tsc -b && npx eslint src/mail
(출력 없음, 종료 코드 0)
```
dev 서버 확인 (`npm run dev -- --port 5174`, 프록시 → 확인용 백엔드 8010):
- 확인용 백엔드는 운영 `mail.db`의 **사본**(임시 폴더, sqlite backup)으로 `customers`·`mails` 라우터만 띄웠다. 운영 DB 연결을 사본으로 돌린 뒤 임포트한다.
- 발신자 선택: 3명 표시(문의 38/88/2, 검토 29/83/2), `dongwook.kim…` 선택 → 문의 20개, 맨 아래로 스크롤(scrollTop 9216 / 높이 9972)
- 가장 최근 문의 `[주입] KC 인증번호 확인`: 고객 질문 → 이전 초안(본문 기록 없음, D1 이전 실행) → 담당자 반려 "표를 빼고…" → AI 초안(`tasks.draft_answer`)
- 이전 문의 더 보기: 누른 뒤 문의 38개(검토 화면 링크 38개 모두 다름 = 겹침 없음), 버튼 사라짐, 스크롤 위치 유지
- 검토 화면 이동: "검토 화면에서 열기" → `/mail/review?task_id=6b40…`, 검토 화면 발신자 옆 "고객방" → `/mail/customers?sender=dongwook.kim%40trigem.co.kr`로 돌아와 같은 고객 선택
- 고객방 본문 영역의 승인·반려·편집·수정 버튼 0개
- API 실패 대역(`fetch` 거부) → "예시 데이터" 배지, 예시 고객 2명과 예시 타임라인
- 콘솔 오류는 확인용 백엔드에 없는 `/config`·`/files`·`/groups` 404뿐

화면 캡처
- [img/D3-timeline.jpg](img/D3-timeline.jpg) — 고객방 (1280×860)
- [img/D3-review-link.jpg](img/D3-review-link.jpg) — 검토 화면 발신자 옆 "고객방" 링크

## 확인하지 못한 것 / Gemini에게 요청할 검증
- 운영 서버(8000) 화면은 서버 재시작과 `npm run build` 뒤에 보인다.

## 커밋 해시
- (summary에 기록)
