# A-A1 메일 상세 출처 복구

## 변경 파일
- `app/routers/mails.py` `view_mail_detail`: 주석 처리돼 있던 `sources` 조립을 살렸다. `task_repo.get_sources(task_id)` 결과를 `{"source", "page", "text"}`로 돌려준다.
- `tests/test_mail_list.py`: 픽스처가 `save_draft(..., sources=[...])`로 출처 2건을 넣고, 상세 응답의 `sources`를 필드 단위로 검사한다. 기존 `sources == []` 기대는 지웠다.

## 결정한 것
- 파일명 추출에 `Path(...).name` 대신 `PureWindowsPath(...).name`을 썼다. `task_sources.source`에는 윈도우 경로(`C:\...\a.pdf`)가 저장돼 있을 수 있는데, 서버를 Docker(리눅스)에서 띄우면 `Path`가 `\`를 구분자로 보지 않아 경로 전체가 나간다. `PureWindowsPath`는 `\`와 `/`를 모두 구분자로 본다. 테스트에 두 형식을 모두 넣었다.
- `source`가 NULL인 행은 빈 문자열로 처리한다 (스키마상 NOT NULL이지만 방어).

## 테스트: 명령과 출력
```
.venv/Scripts/python.exe -m pytest tests/test_mail_list.py -v -k "detail"

tests/test_mail_list.py::test_mail_detail_returns_mail_and_task_fields PASSED [ 33%]
tests/test_mail_list.py::test_mail_detail_returns_404_for_unknown_task_id PASSED [ 66%]
tests/test_mail_list.py::test_mail_uid_is_not_a_detail_identifier PASSED [100%]

====================== 3 passed, 11 deselected in 0.70s =======================
```

## 확인하지 못한 것 / Gemini에게 요청할 검증
- 운영 DB의 실제 task로 `GET /mails/{task_id}`를 호출해 보지 않았다 (운영 DB 쓰기 금지 + 실행 중인 서버는 구버전). 서버 재시작 후 출처가 저장된 task로 확인 요청.

## 커밋 해시
- `0849c2e`
