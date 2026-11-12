# 단계 B 요약 (Gemini B-B 검증 요청)

단계 B(B1~B7) 구현을 마쳤다. 지시서에 따라 **C는 시작하지 않았다.** Gemini의 B-B 판정을 기다린다.

| 항목 | dev_log | 커밋 |
|------|---------|------|
| B1 evidence 저장소·실행 컨텍스트 | [B-B1.md](B-B1.md) | `fe3fdc3` |
| B2 read_pages·list_documents·grep_documents | [B-B2.md](B-B2.md) | `d711294` |
| B3 search 스니펫화·rerank ID화 | [B-B3.md](B-B3.md) | `896f097` |
| B4 첨부를 도구 읽기로 | [B-B4.md](B-B4.md) | `21c01d0` |
| B5 list_evidence·출처 수집 교체 | [B-B5.md](B-B5.md) | `aba524f` |
| B6 서버 검증·실행 기록 (check_answerability 제거) | [B-B6.md](B-B6.md) | `c29e89d` |
| B7 프롬프트 v2·설정값 | [B-B7.md](B-B7.md) | `e51c16b` |

## 회귀: 전체 테스트
```
.venv/Scripts/python.exe -m pytest tests -q

........................................................................ [ 31%]
........................................................................ [ 62%]
........................................................................ [ 93%]
...............                                                          [100%]
231 passed in 29.14s
```
단계 B 시작 전: `190 passed`. 프론트 `npx tsc -b`, `npx eslint src/mail` 통과.

## Gemini B-B 항목 대응
| B-B 조건 | 근거 |
|----------|------|
| `read_pages`가 `file_page.text`를 돌려주고 검수 텍스트 즉시 반영 | `test_doc_tools.py::test_reviewed_text_is_reflected_immediately` |
| 페이지 없는 파일에 `parse_file` 호출 0회 | `test_doc_tools.py::test_file_without_pages_is_not_parsed` |
| evidence 행 필드, 다른 task의 ID 인용 거부 | `test_evidence.py::test_get_respects_owner`, `test_validation.py::test_other_owners_id_is_error` |
| `rerank_documents`가 evidence_id를 받고 본문을 받지 않음 | `tools/tool.py rerank_documents(query, evidence_ids, top_n)`, `test_search_tools.py` |
| 첨부 전문이 user 메시지에 없고 `read_attachment`는 제한된 분량 (50페이지 PDF) | `test_attachments.py::test_fifty_page_pdf_is_read_by_page`, `test_tool_message_has_no_full_attachment_text` |
| 실행 실패·예산 초과·빈 답변이 drafted로 저장되지 않음 | `test_validation.py::test_empty_answer_raises_and_records_error`, `test_recursion_limit_is_recorded_as_limit`, `test_consumer_marks_failed_not_drafted_when_run_fails` |

## 금지 사항 점검
- 메일 실제 발송: 없음.
- 운영 DB: **테스트는 쓰지 않았다** (`tests/conftest.py` 격리, 테스트로 만든 run/evidence 행 0건). 다만 운영 `storage/mail.db`의 수정 시각이 17:42로 바뀌었다. 확인해 보니 **사용자의 서버가 17:41:58에 B6까지의 코드로 재시작**되면서 새 테이블을 만들었다 (`logs/` "서버 준비 완료", access_log 마지막 기록 17:42:19).
- 쓰기 도구: 없음. 새 도구 8개는 모두 읽기다 (`read_pages`, `read_attachment`, `grep_documents`, `list_documents`, `list_evidence`, `search_documents`, `rerank_documents`, `graph_search`). 첨부 페이지 캐시(`attachment_page`)는 도구가 아니라 서버가 쓴다.
- `check_answerability`: B6 서버 검증이 동작한 뒤 제거했다 (같은 커밋, 검증 테스트 통과 후).
- 질의 시점 원본 재파싱: 등록 문서는 없음. 첨부만 지시서가 허용한 1회 파싱.
- 프롬프트만으로 해결: 근거 인용 규칙은 프롬프트에 있지만 소유자·읽음 검증은 `agent/validation.py`가 강제한다.

## 지시서와 다르게 하거나 지시서에 없던 것 (상세는 각 dev_log)
1. `evidence.source_name` 컬럼 추가, 같은 근거 판정 키에 본문 해시 등 추가 (B1)
2. `run.status`에 `running` (B1)
3. `read_pages` 분량 초과 시 페이지 앞부분만 보여 주되 근거는 페이지 전체 (B2)
4. 첨부는 메시지를 만들 때 한 번 파싱해 저장 (페이지 수 표기용, 파싱 1회는 유지) (B4)
5. 임시 첨부는 세션 안 음수 번호 (B4)
6. 그래프 결과를 출처에서 제거 (A2 기능을 지시서 2-3에 따라 되돌림) (B5)
7. `task_sources.cited`, `tasks.validation_json` 컬럼 (B5, B6)
8. 검증 경고 배지를 B6에서 화면에 넣음 (C5와 일부 겹침) (B6)

## 사용자 확인·결정이 필요한 것
- **서버 재시작:** 지금 떠 있는 서버는 B6 코드다. 선택된 프롬프트('테스트')는 없어진 도구를 설명한다. 재시작하면 v2가 들어가고 선택된다. `frontend` 빌드(`npm run build`)도 같이 해야 화면에 검증 배지·발송 상태가 보인다.
- **20000자를 넘는 한 페이지** (`SSD_성능_비교.xlsx` 49,933자일 가능성): `read_pages`에 시작 위치를 둘지 설계 결정이 필요하다 (B2).
- 단계 A에서 넘어온 `sending` 상태 처리 정책은 아직 답을 받지 못해 현행대로 유지한다.
