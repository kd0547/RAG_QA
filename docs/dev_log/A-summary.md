# 단계 A 요약 (Gemini B-A 검증 요청)

단계 A(A1~A6) 구현을 마쳤다. 지시서 0-1에 따라 **B는 시작하지 않았다.** Gemini의 B-A 판정을 기다린다.

| 항목 | dev_log | 커밋 |
|------|---------|------|
| A1 메일 상세 출처 복구 | [A-A1.md](A-A1.md) | `0849c2e` |
| A2 출처 수집 통일·2중 적재 제거 | [A-A2.md](A-A2.md) | `9026f93` |
| A3 초안 저장 후 알림 | [A-A3.md](A-A3.md) | `af4f11c` |
| A4 발송 상태 분기와 승인 선점 | [A-A4.md](A-A4.md) | `7a7f827` |
| A5 한국어 개체 매칭 | [A-A5.md](A-A5.md) | `986e67a` |
| A6 기준선 10문항 | [A-A6.md](A-A6.md) | `c40c955` |

## 회귀: 전체 테스트
```
.venv/Scripts/python.exe -m pytest tests -q

........................................................................ [ 37%]
........................................................................ [ 75%]
..............................................                           [100%]
190 passed in 21.26s
```
단계 A 시작 전: `149 passed`. 기존 테스트 중 바뀐 것은 `tests/test_mail_list.py`뿐이다 (A1 출처 기대값, 발송 대역이 `SendResult`를 돌려주도록).

## 금지 사항 점검
- 메일 실제 발송: 없음. 모든 발송은 대역. 화면 확인도 브라우저에서 `fetch`를 대역으로 바꿔 서버에 POST가 가지 않게 했다.
- 운영 DB 쓰기: 없음. `tests/conftest.py`가 운영 DB 경로 연결을 임시 폴더로 돌린다. `storage/mail.db` 수정 시각 `2026-11-10 17:20:49` 그대로.
- 자동 재발송: 없음. `send_email(` 호출은 승인 API(`app/routers/mails.py`)와 검토 알림(`mail/email_service.py`) 두 곳뿐이고 둘 다 재시도 루프가 없다. `send_failed`·`send_unknown`은 담당자가 승인 API를 다시 부를 때만 다시 보낸다.
- `check_answerability`·`read_source_document`: 건드리지 않음 (단계 B 범위).

## 지시서와 다르게 하거나 지시서에 없던 것 (상세는 각 dev_log)
1. `tests/conftest.py` 신설 — 테스트가 운영 DB·Chroma를 열지 않게 (A2).
2. `task_reviews` CHECK 제약 재생성 마이그레이션 — `mark_sent`를 넣기 위해 (A4).
3. `SMTPDataError`(DATA 명령 거절)는 UNKNOWN이 아니라 FAILED (A4).
4. SMTP 타임아웃 60초 추가 (A4).
5. 검토 페이지 필터는 세 발송 상태를 '발송' 탭 하나로 묶음 (A4).
6. `mail/templates.py` 상태 이름표 갱신 (A4).
7. 평가셋의 주간판매 문항은 기준선에 없어 빈 자리 (A6).

## 배포 시 주의 (사용자 확인 필요)
- 백엔드 재시작과 `frontend` 빌드(`npm run build`)를 **같이** 해야 한다. 새 화면이 새 상태값으로 목록을 요청하면 구버전 서버는 400을 낸다.
- 재시작 때 운영 DB에 `task_send` 테이블 생성과 `task_reviews` 재생성이 처음 적용된다. 재시작 전 `storage/mail.db` 백업을 권한다.
- 서버가 `sending` 중에 꺼진 작업은 `sending`에 남고 화면에서 풀 수 없다 (지시서대로 되돌리지 않음). 처리 경로가 필요한지 결정이 필요하다.
