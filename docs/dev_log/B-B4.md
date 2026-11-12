# B-B4 첨부를 도구 읽기로

## 변경 파일
- `storage/schema.sql`: `attachment_page(attachment_id, seq, page, text, parser_version, created_at)` (PK: attachment_id, seq)
- `entity/type.py`: `Attachment.attachment_id: Optional[int] = None`
- `repository/email_repository.py`: 첨부 조회에 `attachment_id` 포함, `attachment_for_task`, `attachment_pages`, `save_attachment_pages`
- `tools/tool.py`: `read_attachment`, `resolve_attachment`, `attachment_page_texts`, `ATTACHMENT_PARSER_VERSION = "parse_file/1"`
- `agent/agent.py`: `_attachment_to_block` → `_attachment_to_blocks`. 문서는 안내 한 줄, 이미지는 안내 줄 + `image_url`. `_invoke_logged(…, preread=)`
- `agent/evidence_context.py`: 세션 임시 첨부 보관소 `temp_attachments()`
- `app/routers/questions.py`: 주석만
- `tests/test_attachments.py`(신규)

## 결정한 것
1. **메시지를 만들 때 한 번 파싱해 저장한다.** 안내 줄에 "12페이지"를 넣으려면 페이지 수를 알아야 한다. 그래서 메시지를 만들 때 첨부를 한 번 파싱해 `attachment_page`에 저장하고, `read_attachment`는 저장된 페이지를 읽는다. 저장이 없을 때만 파싱하는 규칙(`attachment_page_texts`)은 두 곳이 같이 쓴다. 지시서의 "그 첨부만 1회 파싱해 저장"은 그대로 지켜진다 (테스트: 메시지 생성 + 읽기 2회 → 파싱 1회).
2. **`/ask/attachments` 임시 첨부는 세션 안에서 음수 번호(-1, -2…)를 쓴다.** 지시서는 "session evidence로만 등록하고 응답 후 삭제(현재 동작 유지)"다. `attachment_page`에 저장하지 않고 파싱 결과를 세션 보관소(contextvar dict)에만 둔다. 양수 번호인 메일 첨부와 겹치지 않는다.
3. **첨부 소유 검증:** 양수 번호는 `tasks.mail_uid = mail_attachments.mail_uid` 조인으로 현재 task의 메일 첨부인지 확인한다. 세션 소유자는 양수 번호를 읽을 수 없다.
4. **이미지:** 근거 텍스트는 `"이미지 첨부: 파일명 (약 N KB)"`. 실행 시작 전에 이미 모델에 보여 주는 것이므로 `preread`로 넘겨 `start_run` 직후 `read`로 기록한다. 안내 줄에 `evidence_id`를 넣어 인용할 수 있게 했다.
5. **파싱 실패:** `"[첨부 1] x.hwp (hwp) — 파일을 읽지 못했습니다"` 한 줄 (기존 동작과 같은 취지).
6. **첨부 근거의 revision은 파서 버전.** 파서를 바꿔 다시 파싱해야 하면 `ATTACHMENT_PARSER_VERSION`을 올린다. 다만 이미 저장된 `attachment_page`를 버전으로 무효화하는 코드는 넣지 않았다.

## 테스트: 명령과 출력
```
.venv/Scripts/python.exe -m pytest tests/test_attachments.py -v

tests/test_attachments.py::test_fifty_page_pdf_is_read_by_page PASSED    [ 16%]
tests/test_attachments.py::test_saved_attachment_pages_are_not_parsed_again PASSED [ 33%]
tests/test_attachments.py::test_other_mails_attachment_is_refused PASSED [ 50%]
tests/test_attachments.py::test_temp_attachment_for_ask_session PASSED   [ 66%]
tests/test_attachments.py::test_unreadable_attachment_keeps_a_note PASSED [ 83%]
tests/test_attachments.py::test_tool_message_has_no_full_attachment_text PASSED [100%]

============================== 6 passed in 6.18s ==============================
```
- 50페이지 PDF(페이지당 약 600자): user 메시지 텍스트 < 500자, `"attachment_id=…, 50페이지"` 포함, 본문 없음. `read_attachment(pages=[25])` → 25페이지.
- 페이지 지정 없이 읽으면 기본 6000자에서 잘리고 `truncated`·`next_pages` (전문이 메시지에 들어가지 않음).

## 확인하지 못한 것 / Gemini에게 요청할 검증
- 실제 hwp/hwpx/pdf 첨부로 파싱하지 않았다 (파서 대역). 기준선 첨부 3건(인천공항·공군·LLM 서버)으로 개발 서버 확인이 필요하다.
- 파싱 결과가 0페이지인 첨부는 저장할 행이 없어 읽을 때마다 다시 파싱한다. 빈 결과를 기록하는 표시는 넣지 않았다.

## 커밋 해시
- `21c01d0`
