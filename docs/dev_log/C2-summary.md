# 단계 C2 요약 (보완 지시서 P1~P8, Gemini 검증 요청)

[opus_followup_instructions_C2.md](../opus_followup_instructions_C2.md)의 P1~P8을 마쳤다. **D~H는 시작하지 않았다.**

| 항목 | dev_log | 커밋 |
|------|---------|------|
| P1 발송 중 서버가 꺼진 작업 → send_unknown | [C2-P1.md](C2-P1.md) | `93d03b0` |
| P2 긴 페이지 offset 이어 읽기 | [C2-P2.md](C2-P2.md) | `63ac9f7` |
| P3 검토 화면 실행 이력 전체 | [C2-P3.md](C2-P3.md) | `aa1d391` |
| P4 검토 알림 별도 스레드 | [C2-P4.md](C2-P4.md) | `186bb4d` |
| P5 생성 실패 재시도 API | [C2-P5.md](C2-P5.md) | `edf8561` |
| P6 웹 질문 대화·근거 정리 | [C2-P6.md](C2-P6.md) | `aea9c32` |
| P7 POP3·토큰 요청 시간 제한 | [C2-P7.md](C2-P7.md) | `0377045` |
| P8 빈 첨부 재파싱 방지 | [C2-P8.md](C2-P8.md) | `fd3fa23` |

## 회귀
```
.venv/Scripts/python.exe -m pytest tests -q

........................................................................ [ 25%]
........................................................................ [ 51%]
........................................................................ [ 76%]
.................................................................        [100%]
281 passed in 34.81s
```
시작 시점 257 → 281. 프론트 `npx tsc -b`, `npx eslint src/mail` 통과.

## Gemini C2 검증 항목 대응
| 항목 | 근거 |
|------|------|
| P1 | `test_mark_stale_sending_moves_to_send_unknown` (send_unknown 전환·task_send 결과·재승인 1회), `main.py` lifespan 순서 테스트 |
| P2 | `test_read_pages_reads_long_page_to_end_with_same_evidence`, `test_read_attachment_offset` |
| P3 | `test_detail_runs_keep_first_run_tools_after_rejection`, 화면은 dev 서버 대역 확인 (C2-P3) |
| P4 | `test_slow_notification_does_not_delay_next_draft` |
| P5 | `tests/test_retry.py` 5건 |
| P6 | `test_ask_uses_new_thread_each_call_and_leaves_none`, `test_ask_thread_removed_even_on_failure_but_task_thread_kept`, `test_purge_sessions_removes_only_old_session_rows` |
| P7 | `tests/test_email_receiver_timeout.py` 3건 |
| P8 | `test_empty_attachment_is_parsed_once` |

## 금지 사항 점검
- 실제 메일 발송 없음. 운영 DB 쓰기 없음: 테스트로 생긴 흔적(`t1` 등 소유자, `test` 모델) 0건. 운영 `mail.db`·`agent_threads.db`의 오늘 수정 시각은 10:39에 재시작된 사용자 서버가 쓴 것이다 (access_log 마지막 02:24:43Z와 같음).
- 바꾸지 않은 값: `MAX_READ_CHARS` 20,000, 실행 한도(검색 6·도구 25·모델 20), `recursion_limit` 200, 맥락 예산 24,000/40,000, DB 프롬프트.
- `scripts/inject_test_mail.py`로 운영 DB에 작업을 넣지 않았다.

## 지시서에 없던 것 (상세는 각 dev_log)
1. 검토 화면 `sending` 안내 문구 수정 (P1)
2. 여러 페이지 중 잘린 페이지에도 `next_offset` (P2)
3. 실행 머리줄에 입력 토큰 수, 실패·한도 실행 표시 (P3)
4. C1 테스트(ask 대화가 남는다)를 P6 동작에 맞게 고침 (P6)
5. msal 시간 제한을 별도 설정 `MSAL_TIMEOUT_SECONDS`로 (P7)

## 사용자 확인 필요
- **서버 재시작 + `npm run build`.** 재시작하면 `run.label`, `task_reviews`(retry 허용) 마이그레이션이 운영 DB에 적용된다. `mark_stale_sending`과 `purge_sessions`도 처음 실행된다.
- 운영 `agent_threads.db`에 남은 기존 `ask:` 대화 2개를 한 번 지울지 (P6은 새로 끝나는 질문만 지운다).
- POP3 응답 대기 중 종료하면 최대 30초 걸릴 수 있다 (무기한은 아님) (P7).
