# C-C5 검토 화면 보강

## 변경 파일
- `app/routers/mails.py` `GET /mails/{id}`: `trace`(가장 최근 실행의 `tool_calls_json` → `[{tool, args_summary, at}]`), `read_sources`(이 메일의 실행들에서 읽었지만 `sources`에 없는 근거). `validation`은 B6에서 이미 추가
- `frontend/src/mail/types.ts`: `MailTraceItem`, `MailDetail.trace`, `MailDetail.read_sources`
- `frontend/src/mail/ui.tsx`: `SourceList(sources, readSources)`. 인용 근거 목록 아래에 "읽었지만 인용하지 않은 근거" 접이식 구역 (흐리게)
- `frontend/src/mail/pages/MailReviewPage.tsx`: "에이전트가 한 일 N" 접이식 목록 (시:분:초, 도구 이름, 인자 요약 한 줄 — 길면 말줄임, 마우스를 올리면 전체)
- `tests/test_mail_detail_trace.py`(신규), `tests/test_mail_list.py`(응답 키)

## 결정한 것
1. **cited와 read 구분:** `sources`는 B5 규칙(인용이 있으면 인용만)을 유지하고, 읽었지만 인용하지 않은 근거를 `read_sources`로 따로 준다. 화면은 두 구역으로 나눈다. `task_sources` 저장 형식은 바꾸지 않았다.
2. **trace는 가장 최근 실행만.** 반려 후 재작성이면 재작성 실행의 도구 호출만 보인다 (도구를 안 불렀으면 목록이 숨는다). 실행 이력 전체는 C 범위가 아니라고 보고 넣지 않았다.
3. 전체 메일 페이지(`MailInboxPage`)의 읽기 전용 상세에는 `read_sources`·trace를 넣지 않았다 (지시서 대상은 검토 화면).

## 테스트: 명령과 출력
```
.venv/Scripts/python.exe -m pytest tests/test_mail_detail_trace.py -v

tests/test_mail_detail_trace.py::test_detail_has_trace_validation_and_read_sources PASSED [ 50%]
tests/test_mail_detail_trace.py::test_detail_without_runs_has_empty_trace PASSED [100%]
============================== 2 passed in 5.50s ==============================
```
화면: `npx tsc -b`, `npx eslint src/mail` 통과. 개발 서버(`npm run dev`)에서 브라우저 `fetch`를 대역으로 바꿔 상세를 열었다. "답변이 인용한 근거 1 (guide.pdf p.2)", "읽었지만 인용하지 않은 근거 1 (p.1)", "에이전트가 한 일 2 (graph_search, read_pages, 시각·인자)"가 나오는 것을 확인했다. 실제 서버로는 요청을 보내지 않았다.

## 확인하지 못한 것 / Gemini에게 요청할 검증
- 실제 서버 데이터로 화면을 보지 않았다 (`frontend/dist` 미빌드, 서버 미재시작).

## 커밋 해시
- `507e2d0`
