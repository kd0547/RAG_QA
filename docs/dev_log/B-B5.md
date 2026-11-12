# B-B5 list_evidence 도구와 출처 수집 교체

## 변경 파일
- `tools/tool.py`: `list_evidence()` — 현재 소유자의 근거를 `evidence_id | 파일명 p페이지 | 원천 | rev 버전 | 앞 60자`로 한 줄씩
- `agent/agent.py`: `_collect_sources`·`_graph_sources` 제거, `evidence_sources(run_id)`: cite가 있으면 cite, 없으면 read. 항목 `{evidence_id, file_id, source, page, text(500자), origin_type, cited}`. `run_agent*` 반환에 `run_id`
- `repository/task_repository.py`: `_replace_sources`가 `evidence_id`를 `chunk_id` 자리에, `cited` 저장. `_dedupe_sources`는 evidence_id 우선
- `storage/schema.sql`, `repository/repo_connect.py`: `task_sources.cited` (기존 DB는 ALTER)
- `app/routers/mails.py`, `app/routers/questions.py`: sources에 `evidence_id`, `cited`
- `frontend/src/mail/types.ts`, `frontend/src/mail/ui.tsx`: `MailSource.evidence_id/cited`. 출처 제목을 "답변이 인용한 근거" / "근거 문서 · 에이전트가 읽은 페이지 (답변이 인용하지 않음)"로 구분
- `tests/test_evidence_sources.py`(신규), `tests/test_agent_sources.py`(삭제: A2의 `_collect_sources` 테스트), `tests/test_mail_list.py`

## 결정한 것
1. **A2의 그래프 출처 변환을 없앴다.** 지시서 2-3 "그래프 검색 결과는 evidence가 아니다 (trace에만 남긴다)"에 따라 그래프 결과는 출처가 아니다. 그래프로 찾은 페이지는 `read_pages`로 읽어야 출처가 된다.
2. **`cited`는 `task_sources` 컬럼으로 저장한다.** 검토 화면이 나중에 다시 열려도 인용인지 읽기인지 알 수 있어야 하기 때문이다.
3. **출처 화면 구분:** 한 목록 안의 항목은 모두 인용이거나 모두 읽기라서 항목별 배지 대신 제목으로 구분했다. 전체 구분 표시(목록 둘)는 C5에서 한다.
4. 검색 결과(청크)만 있고 읽은 페이지가 없으면 출처는 빈 목록이다.

## 테스트: 명령과 출력
```
.venv/Scripts/python.exe -m pytest tests/test_evidence_sources.py -v

tests/test_evidence_sources.py::test_sources_are_pages_read_in_run PASSED [ 16%]
tests/test_evidence_sources.py::test_search_hits_alone_are_not_sources PASSED [ 33%]
tests/test_evidence_sources.py::test_cited_evidence_takes_priority PASSED [ 50%]
tests/test_evidence_sources.py::test_list_evidence_shows_owner_rows_only PASSED [ 66%]
tests/test_evidence_sources.py::test_mail_draft_keeps_evidence_id_and_cited PASSED [ 83%]
tests/test_evidence_sources.py::test_tool_list_exposes_evidence_tools PASSED [100%]

============================== 6 passed in 5.99s ==============================
```
화면: `npx tsc -b`, `npx eslint src/mail` 통과. 개발 서버에서 `fetch` 대역으로 cited 출처를 넣어 "답변이 인용한 근거 1" 제목이 나오는 것을 확인했다 (B6 확인 때 함께).

## 확인하지 못한 것 / Gemini에게 요청할 검증
- `/ask` 화면(질의응답 페이지)은 `cited`를 아직 표시하지 않는다 (지시서상 프론트 변경 범위는 검토 화면).
- 예전 메일(`task_sources.cited` 기본 0, `chunk_id`=Chroma 청크 ID)은 "근거 문서"로 보이고 `evidence_id` 자리에 청크 ID가 나온다.

## 커밋 해시
- `aba524f`
