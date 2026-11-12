# A-A3 초안 저장 후 알림

## 변경 파일
- `mail/email_service.py`
  - `email_consumer_loop`: `task_repo.save_draft(...)`를 검토 알림 발송보다 먼저 호출한다.
  - `_notify_reviewer`(신규): 알림 발송을 감싼다. 예외가 나거나(A3) 결과가 `SENT`가 아니면(A4 이후) `logger.exception`/`logger.error`만 남기고 상태는 바꾸지 않는다. 초안은 `drafted`로 남는다.
- `tests/test_email_consumer.py`(신규): 소비자 루프를 한 주기만 돌리는 `stop_event` 대역과 메모리 `task_repo` 대역으로 상태 전이를 확인한다.
- `tests/conftest.py`: 메일 모듈 임포트용 더미 계정 환경변수 추가.

## 결정한 것
- `save_draft`가 실패하면 기존처럼 바깥 `except`가 `FAILED`로 바꾼다. 이때 알림은 나가지 않는다.
- 알림 발송 실패는 `logger.exception`(예외) 또는 `logger.error`(서버가 받지 않음)로 남긴다. 지시서의 "`logger.exception`만"은 예외 경로에 그대로 적용했고, A4에서 `send_email`이 예외 대신 결과를 돌려주게 되어 결과 분기도 같은 취지로 처리했다.

## 테스트: 명령과 출력
```
.venv/Scripts/python.exe -m pytest tests/test_email_consumer.py -v

tests/test_email_consumer.py::test_draft_is_saved_before_reviewer_notification PASSED [ 25%]
tests/test_email_consumer.py::test_notification_not_sent_when_draft_save_fails PASSED [ 50%]
tests/test_email_consumer.py::test_notification_failure_keeps_drafted PASSED [ 75%]
tests/test_email_consumer.py::test_notification_rejected_by_server_keeps_drafted PASSED [100%]

============================== 4 passed in 5.29s ==============================
```
(위 출력은 A4 반영 후. 4번째 테스트와 `PROCESSING` 검사는 A4에서 더했다.)

## 확인하지 못한 것 / Gemini에게 요청할 검증
- 실제 SMTP로 알림 실패를 재현하지 않았다 (메일 발송 금지).

## 커밋 해시
- `af4f11c` (A4 커밋 `7a7f827`에서 알림 결과 분기와 테스트 보강)
