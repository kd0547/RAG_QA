# A-A4 발송 상태 분기와 승인 선점

## 변경 파일
| 파일 | 변경 |
|------|------|
| `entity/type.py` | `TaskStatus`에 `PROCESSING`, `SENDING`, `SEND_FAILED`, `SEND_UNKNOWN` 추가. `FAILED`는 "답변 생성 실패" 전용으로 주석 변경 |
| `storage/schema.sql` | `task_send` 테이블 신규. `task_reviews.action` CHECK에 `'mark_sent'` 추가 |
| `repository/repo_connect.py` | `_migrate_task_reviews_action`: 기존 DB의 `task_reviews`를 새 CHECK로 재생성 (이력·review_id 보존) |
| `repository/task_repository.py` | `SENDABLE`, `claim_for_send`, `finish_send`, `get_sends`, `mark_sent`, `reset_processing` |
| `mail/email_send.py` | `SendOutcome`, `SendResult`. `send_email`이 결과를 돌려주고 예외를 던지지 않는다. `send_message` 대신 `mail`/`rcpt`/`data` 직접 호출 |
| `mail/email_service.py` | 처리 시작 시 `PROCESSING`. 검토 알림은 `SendResult`를 보고 실패를 로그로만 남김 |
| `app/routers/mails.py` | `mail_approve`: `claim_for_send` → `send_email` → `finish_send`. 신규 `POST /mails/{task_id}/mark-sent` |
| `main.py` | lifespan 시작부에서 `task_repo.reset_processing()` |
| `mail/templates.py` | 메일 링크 단독 페이지의 상태 이름표(`_STATUS_LABEL`)에 새 상태 추가, `failed` 이름을 "초안 생성 실패"로 |
| `frontend/src/mail/types.ts` | `MailStatus`에 네 값 추가 |
| `frontend/src/mail/format.ts` | 상태 배지·`REVIEW_STATUSES`·`ALL_STATUSES`, `SEND_ISSUE_STATUSES` |
| `frontend/src/mail/api.ts` | `markSent` |
| `frontend/src/mail/pages/MailReviewPage.tsx` | 재발송·발송 확인됨 버튼, 확인 문구, 안내 배너, '발송' 필터 |
| `frontend/src/mail/pages/MailInboxPage.tsx` | 탭 상태 목록·답장 제목에 새 상태 |
| `frontend/src/mail/pages/MailDashboardPage.tsx` | 상태 분포에 새 상태, 실패 KPI에 `send_failed`·`send_unknown` 포함 |
| `tests/test_email_send.py`(신규), `tests/test_mail_send_status.py`(신규), `tests/test_mail_list.py`, `tests/test_email_consumer.py` | 테스트 |

## 결정한 것
1. **`task_reviews` CHECK 제약 재생성.** 기존 스키마가 `CHECK (action IN ('reject'))`라 지시서 6번의 `action='mark_sent'`를 넣을 수 없다. SQLite는 CHECK를 ALTER로 바꿀 수 없어 `_migrate`에서 새 테이블을 만들어 행을 복사하고 이름을 바꾼다. `review_id`를 그대로 복사해 C3의 `last_review_id` 비교가 깨지지 않게 했다. 설계 변경이 아니라 구현 방법이라 충돌로 멈추지 않았다.
2. **`server.data()`가 `SMTPDataError`(DATA 명령에 354가 아닌 응답)를 던지면 `FAILED`.** 지시서 표는 "data 예외 → UNKNOWN"이지만 예시가 `SMTPServerDisconnected`, timeout, `OSError`다. `smtplib.data()`는 DATA 명령 자체를 거절당하면 본문을 보내기 전에 `SMTPDataError`를 던진다. 서버가 받지 않았음이 확실하므로 FAILED로 했다. 본문 전송 뒤의 비정상 코드는 예외가 아니라 반환값이라 표대로 FAILED.
3. **SMTP 타임아웃 60초 (`SMTP_TIMEOUT_SECONDS`).** 기존 코드는 타임아웃이 없어 연결이 멈추면 `sending`에 무한정 붙잡힌다. 본문 전송 중 타임아웃은 표대로 UNKNOWN.
4. **메시지 바이트화는 `BytesGenerator(...).flatten(msg, linesep="\r\n")`.** `send_message`가 내부에서 하는 방식과 같다 (테스트에서 CRLF 확인).
5. **승인 API에서 `send_email`이 예상 밖 예외를 던지면 `send_unknown`.** `send_email`은 예외를 던지지 않게 만들었지만, 만약 던지면 메일이 나갔는지 모르므로 안전한 쪽(담당자 확인)으로 둔다. `sending`에 남기지 않는다.
6. **수정본 저장 시점.** 예전에는 상태 확인 직후 `update_draft_answer`를 했다. 이제 `claim_for_send`가 성공한 뒤에 저장한다 (선점에 실패한 요청이 초안을 바꾸지 않게).
7. **실패 응답.** `send_failed`·`send_unknown` 모두 502. `detail`은 사람이 읽는 문장이고 상태 이름(`send_failed`/`send_unknown`)을 포함한다. 화면(`ApiError.message`)과 메일 링크 단독 페이지(`ERROR_TEXT[detail] || detail`)가 그대로 보여 준다.
8. **승인 가능 상태 = `drafted, send_failed, send_unknown`.** 예전과 같이 `in_review`는 승인 불가(409)다.
9. **`PROCESSING` 표시 위치.** `get_pending_tasks` 직후 전체를 한 번에 바꾸지 않고, 루프에서 각 작업을 처리하기 직전에 바꾼다. 대기 중인 작업이 "생성 중"으로 보이지 않게 하기 위해서다. 재시작 복구 의미는 같다.
10. **화면 필터.** 검토 페이지 왼쪽 필터는 폭(287px)이 좁아 세 상태를 각각 탭으로 두면 넘친다. `sending·send_failed·send_unknown`을 하나의 '발송' 탭으로 묶었다. 각 행의 배지는 상태별로 다르다(전송 중 / 전송 실패 / 전송 확인 필요). 전체 메일 페이지는 '검토 필요' 탭에 세 상태를 넣었다.
11. **반려·담당 버튼.** 발송 문제 상태(`sending/send_failed/send_unknown`)에서는 반려 버튼을 숨겼다. 백엔드 `REJECTABLE`이 `drafted, in_review`뿐이라 눌러도 409가 나기 때문이다.
12. **`mail/templates.py` 수정.** 지시서 파일 목록에 없지만 메일 링크 단독 페이지가 상태 이름을 보여 주고, `failed`를 "전송 실패"로 표시하고 있었다. `failed` 의미가 바뀌었으므로 이름표만 맞췄다.

## 테스트: 명령과 출력
```
.venv/Scripts/python.exe -m pytest tests/test_email_send.py tests/test_mail_send_status.py -v   (마지막 20줄)

tests/test_email_send.py::test_accepted_then_quit_fails_is_sent_with_warning PASSED [ 32%]
tests/test_email_send.py::test_sent_payload_is_crlf_mime PASSED          [ 36%]
tests/test_mail_send_status.py::test_approve_concurrent_requests_send_once PASSED [ 40%]
tests/test_mail_send_status.py::test_approve_records_failed_and_unknown[send_failed] PASSED [ 44%]
tests/test_mail_send_status.py::test_approve_records_failed_and_unknown[send_unknown] PASSED [ 48%]
tests/test_mail_send_status.py::test_approve_unexpected_exception_is_unknown_not_resent PASSED [ 52%]
tests/test_mail_send_status.py::test_approve_quit_warning_keeps_sent PASSED [ 56%]
tests/test_mail_send_status.py::test_reapprove_after_failure_sends_again[send_failed] PASSED [ 60%]
tests/test_mail_send_status.py::test_reapprove_after_failure_sends_again[send_unknown] PASSED [ 64%]
tests/test_mail_send_status.py::test_approve_refuses_other_statuses[sending] PASSED [ 68%]
tests/test_mail_send_status.py::test_approve_refuses_other_statuses[sent] PASSED [ 72%]
tests/test_mail_send_status.py::test_approve_refuses_other_statuses[pending] PASSED [ 76%]
tests/test_mail_send_status.py::test_approve_refuses_other_statuses[processing] PASSED [ 80%]
tests/test_mail_send_status.py::test_approve_refuses_other_statuses[failed] PASSED [ 84%]
tests/test_mail_send_status.py::test_approve_refuses_other_statuses[in_review] PASSED [ 88%]
tests/test_mail_send_status.py::test_mark_sent_only_from_send_unknown PASSED [ 92%]
tests/test_mail_send_status.py::test_reset_processing_restores_pending_but_not_sending PASSED [ 96%]
tests/test_mail_send_status.py::test_migration_allows_mark_sent_on_old_task_reviews PASSED [100%]

============================= 25 passed in 2.99s ==============================
```
`test_email_send.py`의 앞 9건(잘린 부분): 로그인 실패·연결 실패·RCPT 550 → FAILED, DATA 중 끊김·타임아웃 → UNKNOWN, DATA 554 거절·DATA 451 → FAILED, DATA 250 후 quit 예외 → SENT+`cleanup_warning`+로그 "경고=", 정상 발송 시 호출 순서 `ehlo, starttls, ehlo, login, mail, rcpt, data, quit`과 CRLF 확인.

지시서 테스트 대응:
- SMTP 대역 3종 → `test_login_failure_is_failed`, `test_disconnect_during_data_is_unknown`, `test_accepted_then_quit_fails_is_sent_with_warning`
- 동시 승인(대역 0.5초 지연, 두 스레드) → `test_approve_concurrent_requests_send_once`: 발송 대역 1회, 결과 `[409, "sent"]`, `task_send` 1행
- `mark-sent`는 `send_unknown`에서만 200 → `test_mark_sent_only_from_send_unknown` (나머지 모든 상태 409, 빈 사유 400, 없는 task 404, `task_reviews`에 `mark_sent` 기록)
- `reset_processing` 후 processing 0건 → `test_reset_processing_restores_pending_but_not_sending` (sending은 유지)

화면 확인 (개발 서버 `npm run dev`, 브라우저에서 `fetch`를 대역으로 바꿔 실제 서버에 POST가 가지 않게 함):
- `send_unknown` 메일: 안내 배너, "발송 확인됨"·"재발송" 버튼. 재발송 확인창 문구에 "자동 재발송은 하지 않습니다" 포함, 취소하면 요청 없음. 발송 확인됨 → 사유 입력 → `POST /mails/t-unknown/mark-sent {"reason":"보낸편지함에 있음"}`.
- `send_failed` 메일: "재발송"만 보임(반려·내가 검토 숨김). 확인 후 502 응답 → 오류 알림과 상세 다시 읽기(`GET /mails/t-failed`).
- `drafted` 메일: 기존과 같이 반려·내가 검토·승인하고 전송.
- `npx tsc -b`, `npx eslint src/mail` 통과.

## 확인하지 못한 것 / Gemini에게 요청할 검증
- 실제 SMTP 서버(outlook.office365.com)로 보내지 않았다 (발송 금지). `mail`/`rcpt`/`data` 직접 호출이 Office 365에서 `send_message`와 같게 동작하는지는 개발 서버에서 테스트 메일 1건으로 확인이 필요하다.
- 기존 운영 DB에 `_migrate_task_reviews_action`이 적용되는 것은 임시 DB(예전 스키마 재현)로만 확인했다. 서버 재시작 때 운영 DB에 처음 적용된다. 재시작 전에 `storage/mail.db` 백업을 권한다.
- 서버가 `sending` 중에 꺼지면 그 작업은 `sending`에 남고, 지금은 화면에서 풀 방법이 없다 (지시서대로 되돌리지 않음). 담당자 처리 경로(예: sending → send_unknown 수동 전환)가 필요한지 결정이 필요하다.
- `frontend/dist`는 다시 빌드하지 않았다. 새 화면은 `status=processing,...`로 목록을 요청하는데 재시작 전 구버전 서버는 이를 400으로 거절한다. **백엔드 재시작과 `npm run build`를 같이 해야 한다.**
- 기존 화면의 "재전송" 버튼(`failed` 상태, `POST /mails/{id}/retry`)은 백엔드에 해당 API가 없어 원래부터 404다. `failed`가 이제 "생성 실패" 전용이 되었으므로 이 버튼의 의미도 맞지 않지만, 지시서 범위 밖이라 손대지 않았다.
- 대시보드 KPI(`GET /mails/stats`)는 원래 0을 돌려주는 스텁이라 새 상태 반영 여부를 확인할 수 없다.

## 커밋 해시
- `7a7f827`
